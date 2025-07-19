"""Temporal workflow definitions for durable task execution.

This module implements the core workflow logic for orchestrating
algorithm execution with fault tolerance, replay capabilities,
and dynamic versioning support.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from helixcore.interfaces.proto import task_pb2

logger = structlog.get_logger()


@dataclass
class WorkflowInput:
    """Input parameters for task workflow."""
    
    workflow_id: str
    tasks: List[Dict[str, Any]]
    metadata: Dict[str, str]


@dataclass
class WorkflowState:
    """Mutable workflow state for version management."""
    
    version: str = "v1"
    tasks_completed: int = 0
    experiment_results: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.experiment_results is None:
            self.experiment_results = []


@workflow.defn(name="TaskWorkflow")
class TaskWorkflow:
    """Durable workflow for executing algorithm tasks.
    
    This workflow orchestrates the execution of multiple algorithm tasks
    with support for:
    - Fault tolerance and automatic replay
    - Dynamic versioning through signals
    - Compensation logic for failures
    - Human-in-the-loop experiment result integration
    """
    
    def __init__(self) -> None:
        """Initialize workflow state."""
        self.state = WorkflowState()
        self.logger = logger.bind(
            workflow_id=workflow.info().workflow_id,
            run_id=workflow.info().run_id,
        )
    
    @workflow.run
    async def run(self, input_data: WorkflowInput) -> Dict[str, Any]:
        """Execute the main workflow logic.
        
        Parameters
        ----------
        input_data : WorkflowInput
            The workflow input containing tasks to execute.
            
        Returns
        -------
        Dict[str, Any]
            The workflow execution results.
        """
        self.logger.info(
            "workflow_started",
            task_count=len(input_data.tasks),
            metadata=input_data.metadata,
        )
        
        results = []
        
        for idx, task in enumerate(input_data.tasks):
            try:
                # Execute algorithm with retry policy
                result = await workflow.execute_activity(
                    "execute_algorithm",
                    task,
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(minutes=1),
                        maximum_attempts=3,
                        non_retryable_error_types=["ValidationError"],
                    ),
                )
                
                results.append(result)
                self.state.tasks_completed += 1
                
                self.logger.info(
                    "task_completed",
                    task_index=idx,
                    task_id=task.get("task_id"),
                    progress=f"{self.state.tasks_completed}/{len(input_data.tasks)}",
                )
                
                # Check for experiment results after each task
                if self.state.experiment_results:
                    await self._process_experiment_results()
                
            except ApplicationError as e:
                self.logger.error(
                    "task_failed",
                    task_index=idx,
                    error=str(e),
                    will_compensate=True,
                )
                
                # Execute compensation logic
                await self._compensate_failure(task, idx, results)
                raise
            
            except Exception as e:
                self.logger.error(
                    "unexpected_error",
                    task_index=idx,
                    error=str(e),
                    exc_info=True,
                )
                raise
        
        return {
            "workflow_id": input_data.workflow_id,
            "version": self.state.version,
            "tasks_completed": self.state.tasks_completed,
            "results": results,
            "experiment_integrations": len(self.state.experiment_results),
        }
    
    @workflow.signal(name="on_experiment_result")
    async def on_experiment_result(self, result: Dict[str, Any]) -> None:
        """Handle incoming experiment results from wet-lab.
        
        This signal allows human operators to inject experimental
        data into the running workflow, potentially triggering
        version updates or workflow continuation.
        
        Parameters
        ----------
        result : Dict[str, Any]
            The experiment result data.
        """
        self.logger.info(
            "experiment_result_received",
            experiment_id=result.get("experiment_id"),
            pass_qc=result.get("pass_qc"),
        )
        
        self.state.experiment_results.append(result)
        
        # If QC passed and we have new insights, consider version update
        if result.get("pass_qc") and result.get("requires_update"):
            await self._trigger_version_update(result)
    
    async def _trigger_version_update(self, experiment_result: Dict[str, Any]) -> None:
        """Trigger workflow version update based on experiment results.
        
        Parameters
        ----------
        experiment_result : Dict[str, Any]
            The experiment result that triggered the update.
        """
        new_version = experiment_result.get("suggested_version", "v2")
        
        self.logger.info(
            "triggering_version_update",
            current_version=self.state.version,
            new_version=new_version,
        )
        
        # Use Temporal's continue-as-new to maintain history
        # while updating to new version
        workflow.continue_as_new(
            WorkflowInput(
                workflow_id=workflow.info().workflow_id,
                tasks=experiment_result.get("updated_tasks", []),
                metadata={
                    "previous_version": self.state.version,
                    "update_reason": "experiment_result",
                    "experiment_id": experiment_result.get("experiment_id"),
                },
            )
        )
    
    async def _process_experiment_results(self) -> None:
        """Process accumulated experiment results.
        
        This method integrates experiment data into the workflow
        execution, potentially modifying subsequent task parameters.
        """
        for result in self.state.experiment_results:
            if result.get("modifies_parameters"):
                # Update parameters for remaining tasks
                self.logger.info(
                    "updating_task_parameters",
                    experiment_id=result.get("experiment_id"),
                )
                # Implementation depends on specific requirements
    
    async def _compensate_failure(
        self,
        failed_task: Dict[str, Any],
        task_index: int,
        completed_results: List[Dict[str, Any]],
    ) -> None:
        """Execute compensation logic for failed tasks.
        
        Parameters
        ----------
        failed_task : Dict[str, Any]
            The task that failed.
        task_index : int
            Index of the failed task.
        completed_results : List[Dict[str, Any]]
            Results from successfully completed tasks.
        """
        self.logger.info(
            "executing_compensation",
            failed_task_id=failed_task.get("task_id"),
            completed_tasks=len(completed_results),
        )
        
        # Compensate in reverse order
        for idx in range(len(completed_results) - 1, -1, -1):
            try:
                await workflow.execute_activity(
                    "compensate_algorithm",
                    {
                        "original_task": completed_results[idx],
                        "failure_context": {
                            "failed_task_id": failed_task.get("task_id"),
                            "failed_at_index": task_index,
                        },
                    },
                    start_to_close_timeout=timedelta(minutes=10),
                )
                
                self.logger.info(
                    "compensation_completed",
                    compensated_index=idx,
                )
                
            except Exception as e:
                self.logger.error(
                    "compensation_failed",
                    compensated_index=idx,
                    error=str(e),
                )
                # Continue with other compensations
    
    @workflow.query(name="get_workflow_state")
    def get_workflow_state(self) -> Dict[str, Any]:
        """Query handler to retrieve current workflow state.
        
        Returns
        -------
        Dict[str, Any]
            Current workflow state information.
        """
        return {
            "version": self.state.version,
            "tasks_completed": self.state.tasks_completed,
            "experiment_results_count": len(self.state.experiment_results),
            "workflow_id": workflow.info().workflow_id,
            "run_id": workflow.info().run_id,
        }
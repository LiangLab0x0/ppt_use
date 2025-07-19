"""Planner agent implementation using AutoGen framework.

This module implements the PlannerAgent that decomposes high-level
goals into executable TaskSpec DAGs using LLM-powered reasoning.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from autogen import AssistantAgent, UserProxyAgent
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from helixcore.agents.base import BaseAgent, AgentMessage
from helixcore.interfaces.proto import task_pb2

logger = structlog.get_logger()


class PlannerAgent(BaseAgent):
    """LLM-powered planner agent for task decomposition.
    
    The PlannerAgent takes high-level research goals and decomposes
    them into a directed acyclic graph (DAG) of executable tasks.
    It uses AutoGen for multi-turn reasoning and refinement.
    
    Attributes
    ----------
    llm_model : str
        The LLM model to use for planning.
    temperature : float
        Temperature setting for LLM creativity.
    """
    
    def __init__(
        self,
        agent_id: str = "planner_001",
        name: str = "PlannerAgent",
        llm_model: str = "gpt-4",
        temperature: float = 0.7,
    ) -> None:
        """Initialize the planner agent.
        
        Parameters
        ----------
        agent_id : str, optional
            Unique agent ID, by default "planner_001".
        name : str, optional
            Agent name, by default "PlannerAgent".
        llm_model : str, optional
            LLM model name, by default "gpt-4".
        temperature : float, optional
            LLM temperature, by default 0.7.
        """
        super().__init__(
            agent_id=agent_id,
            name=name,
            capabilities=[
                "goal_decomposition",
                "task_planning",
                "dependency_analysis",
                "resource_estimation",
            ],
        )
        
        self.llm_model = llm_model
        self.temperature = temperature
        self._setup_autogen_agents()
        self._setup_planning_chain()
    
    def _setup_autogen_agents(self) -> None:
        """Configure AutoGen assistant and user proxy agents."""
        # System prompt for the assistant
        system_prompt = """You are an expert R&D planner for interdisciplinary research.
        Your role is to decompose high-level research goals into concrete, executable tasks.
        
        For each goal, you must:
        1. Identify the key steps required
        2. Determine dependencies between steps
        3. Select appropriate algorithms from the registry
        4. Estimate resource requirements
        5. Consider wet-lab and simulation constraints
        
        Output your plan as a structured JSON with:
        - tasks: Array of task specifications
        - dependencies: Task dependency graph
        - estimated_duration: Total time estimate
        - required_resources: Resource summary
        """
        
        self.assistant = AssistantAgent(
            name="planner_assistant",
            system_message=system_prompt,
            llm_config={
                "model": self.llm_model,
                "temperature": self.temperature,
            },
        )
        
        self.user_proxy = UserProxyAgent(
            name="planner_proxy",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=5,
            code_execution_config={"use_docker": False},
        )
    
    def _setup_planning_chain(self) -> None:
        """Configure the planning prompt chain."""
        self.planning_prompt = ChatPromptTemplate.from_template("""
        Research Goal: {goal}
        Available Algorithms: {algorithms}
        Constraints: {constraints}
        
        Create a detailed execution plan that:
        1. Breaks down the goal into specific tasks
        2. Identifies which algorithms to use for each task
        3. Specifies input/output data flow between tasks
        4. Estimates resource requirements
        5. Highlights any experimental validation steps needed
        
        Return a valid JSON structure.
        """)
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Process incoming planning requests.
        
        Parameters
        ----------
        message : AgentMessage
            The incoming message containing planning request.
            
        Returns
        -------
        Optional[AgentMessage]
            Response with the generated plan.
        """
        self.add_to_history(message)
        
        if message.message_type == "plan_request":
            plan = await self.execute_task(message.content)
            
            response = AgentMessage(
                sender=self.agent_id,
                recipient=message.sender,
                content=plan,
                message_type="plan_response",
                correlation_id=message.correlation_id,
                timestamp=datetime.utcnow().isoformat(),
            )
            
            self.add_to_history(response)
            return response
        
        return None
    
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute planning task to decompose research goals.
        
        Parameters
        ----------
        task : Dict[str, Any]
            Planning task containing:
            - goal: High-level research goal
            - algorithms: Available algorithm registry
            - constraints: Execution constraints
            
        Returns
        -------
        Dict[str, Any]
            Generated execution plan with task DAG.
        """
        self.set_status("planning")
        
        try:
            # Extract planning parameters
            goal = task.get("goal", "")
            algorithms = task.get("algorithms", [])
            constraints = task.get("constraints", {})
            
            self.logger.info(
                "starting_planning",
                goal_summary=goal[:100],
                algorithm_count=len(algorithms),
            )
            
            # Use AutoGen for multi-turn planning refinement
            planning_request = self.planning_prompt.format(
                goal=goal,
                algorithms=json.dumps(algorithms, indent=2),
                constraints=json.dumps(constraints, indent=2),
            )
            
            # Initiate chat between agents
            self.user_proxy.initiate_chat(
                self.assistant,
                message=planning_request,
            )
            
            # Extract the final plan from conversation
            plan_json = self._extract_plan_from_conversation()
            
            # Convert to TaskSpec list
            task_specs = self._create_task_specs(plan_json)
            
            result = {
                "plan_id": str(uuid.uuid4()),
                "goal": goal,
                "tasks": task_specs,
                "dependencies": plan_json.get("dependencies", {}),
                "estimated_duration": plan_json.get("estimated_duration", "unknown"),
                "required_resources": plan_json.get("required_resources", {}),
                "confidence_score": self._calculate_confidence(plan_json),
            }
            
            self.update_memory(f"plan_{result['plan_id']}", result)
            self.set_status("idle")
            
            self.logger.info(
                "planning_completed",
                plan_id=result["plan_id"],
                task_count=len(task_specs),
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                "planning_failed",
                error=str(e),
                exc_info=True,
            )
            self.set_status("error")
            raise
    
    def _extract_plan_from_conversation(self) -> Dict[str, Any]:
        """Extract structured plan from AutoGen conversation.
        
        Returns
        -------
        Dict[str, Any]
            Extracted plan as JSON structure.
        """
        # Get the last message from assistant
        messages = self.assistant.chat_messages[self.user_proxy]
        
        for message in reversed(messages):
            if message.get("role") == "assistant":
                content = message.get("content", "")
                
                # Extract JSON from the content
                try:
                    # Find JSON block in the response
                    start_idx = content.find("{")
                    end_idx = content.rfind("}") + 1
                    
                    if start_idx >= 0 and end_idx > start_idx:
                        json_str = content[start_idx:end_idx]
                        return json.loads(json_str)
                except (json.JSONDecodeError, ValueError):
                    continue
        
        # Fallback to empty plan
        return {"tasks": [], "dependencies": {}}
    
    def _create_task_specs(self, plan_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert plan JSON to TaskSpec list.
        
        Parameters
        ----------
        plan_json : Dict[str, Any]
            The structured plan from LLM.
            
        Returns
        -------
        List[Dict[str, Any]]
            List of task specifications.
        """
        task_specs = []
        
        for idx, task_data in enumerate(plan_json.get("tasks", [])):
            task_spec = {
                "task_id": f"task_{uuid.uuid4().hex[:8]}",
                "algorithm_name": task_data.get("algorithm", "unknown"),
                "input_payload": task_data.get("inputs", {}),
                "labels": {
                    "step": str(idx + 1),
                    "description": task_data.get("description", ""),
                    "priority": task_data.get("priority", "medium"),
                },
                "resources": task_data.get("resources", {}),
            }
            task_specs.append(task_spec)
        
        return task_specs
    
    def _calculate_confidence(self, plan_json: Dict[str, Any]) -> float:
        """Calculate confidence score for the generated plan.
        
        Parameters
        ----------
        plan_json : Dict[str, Any]
            The generated plan.
            
        Returns
        -------
        float
            Confidence score between 0 and 1.
        """
        score = 0.5  # Base score
        
        # Check for completeness
        if plan_json.get("tasks"):
            score += 0.2
        
        if plan_json.get("dependencies"):
            score += 0.1
        
        if plan_json.get("estimated_duration"):
            score += 0.1
        
        if plan_json.get("required_resources"):
            score += 0.1
        
        return min(score, 1.0)
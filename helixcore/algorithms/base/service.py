"""Base algorithm service implementation.

This module provides the abstract base class for all algorithm microservices
in the HelixCore framework. Each algorithm must implement the predict method
and provide health check and manifest capabilities.
"""

import asyncio
import os
from abc import ABC, abstractmethod
from concurrent import futures
from typing import Any, Dict, Optional

import grpc
import structlog
from google.protobuf import empty_pb2, struct_pb2
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from helixcore.interfaces.proto import task_pb2, task_pb2_grpc

logger = structlog.get_logger()


class BaseAlgorithmService(task_pb2_grpc.AlgorithmServiceServicer, ABC):
    """Abstract base class for algorithm microservices.
    
    This class provides the foundational structure for all algorithm
    implementations in HelixCore. It handles gRPC service setup,
    observability, health checks, and manifest management.
    
    Attributes
    ----------
    name : str
        The unique name of the algorithm.
    version : str
        The semantic version of the algorithm.
    manifest_path : str
        Path to the algorithm's manifest.yaml file.
    """
    
    def __init__(
        self,
        name: str,
        version: str,
        manifest_path: str = "manifest.yaml",
    ) -> None:
        """Initialize the base algorithm service.
        
        Parameters
        ----------
        name : str
            The unique name of the algorithm.
        version : str
            The semantic version of the algorithm.
        manifest_path : str, optional
            Path to the algorithm's manifest.yaml file, by default "manifest.yaml".
        """
        self.name = name
        self.version = version
        self.manifest_path = manifest_path
        self._setup_telemetry()
        self._tracer = trace.get_tracer(__name__)
        self._health_status = task_pb2.SERVICE_HEALTH_HEALTHY
        self._manifest = self._load_manifest()
        
    def _setup_telemetry(self) -> None:
        """Configure OpenTelemetry instrumentation."""
        resource = Resource(attributes={
            "service.name": self.name,
            "service.version": self.version,
        })
        
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
                insecure=True,
            )
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        
        # Instrument gRPC
        GrpcInstrumentorServer().instrument()
        
    def _load_manifest(self) -> task_pb2.AlgorithmManifest:
        """Load algorithm manifest from YAML file.
        
        Returns
        -------
        task_pb2.AlgorithmManifest
            The loaded algorithm manifest.
        """
        from .manifest import ManifestLoader
        return ManifestLoader.load(self.manifest_path, self.name, self.version)
    
    @abstractmethod
    async def predict(self, task_spec: task_pb2.TaskSpec) -> Dict[str, Any]:
        """Execute the algorithm's prediction logic.
        
        This method must be implemented by each algorithm service.
        It receives a TaskSpec with input data and returns the results.
        
        Parameters
        ----------
        task_spec : task_pb2.TaskSpec
            The task specification containing input data.
            
        Returns
        -------
        Dict[str, Any]
            The prediction results as a dictionary.
            
        Raises
        ------
        NotImplementedError
            If the method is not implemented by a subclass.
        """
        raise NotImplementedError("Subclasses must implement predict()")
    
    def Predict(
        self,
        request: task_pb2.TaskSpec,
        context: grpc.ServicerContext,
    ) -> struct_pb2.Struct:
        """gRPC endpoint for algorithm prediction.
        
        Parameters
        ----------
        request : task_pb2.TaskSpec
            The incoming task specification.
        context : grpc.ServicerContext
            The gRPC context.
            
        Returns
        -------
        struct_pb2.Struct
            The prediction results as a protobuf Struct.
        """
        with self._tracer.start_as_current_span("predict") as span:
            span.set_attribute("task.id", request.task_id)
            span.set_attribute("algorithm.name", request.algorithm_name)
            
            try:
                logger.info(
                    "processing_task",
                    task_id=request.task_id,
                    algorithm=request.algorithm_name,
                )
                
                # Run async predict in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.predict(request))
                
                # Convert result to protobuf Struct
                response = struct_pb2.Struct()
                response.update(result)
                
                logger.info(
                    "task_completed",
                    task_id=request.task_id,
                    result_keys=list(result.keys()),
                )
                
                return response
                
            except Exception as e:
                logger.error(
                    "task_failed",
                    task_id=request.task_id,
                    error=str(e),
                    exc_info=True,
                )
                context.abort(grpc.StatusCode.INTERNAL, str(e))
    
    def Health(
        self,
        request: empty_pb2.Empty,
        context: grpc.ServicerContext,
    ) -> task_pb2.HealthStatus:
        """gRPC endpoint for health checks.
        
        Parameters
        ----------
        request : empty_pb2.Empty
            Empty request (unused).
        context : grpc.ServicerContext
            The gRPC context.
            
        Returns
        -------
        task_pb2.HealthStatus
            The current health status of the service.
        """
        return task_pb2.HealthStatus(
            status=self._health_status,
            version=self.version,
            message="Service is operational",
        )
    
    def GetManifest(
        self,
        request: empty_pb2.Empty,
        context: grpc.ServicerContext,
    ) -> task_pb2.AlgorithmManifest:
        """gRPC endpoint to retrieve algorithm manifest.
        
        Parameters
        ----------
        request : empty_pb2.Empty
            Empty request (unused).
        context : grpc.ServicerContext
            The gRPC context.
            
        Returns
        -------
        task_pb2.AlgorithmManifest
            The algorithm's manifest.
        """
        return self._manifest
    
    def Cancel(
        self,
        request: task_pb2.TaskSpec,
        context: grpc.ServicerContext,
    ) -> empty_pb2.Empty:
        """gRPC endpoint to cancel a running task.
        
        Parameters
        ----------
        request : task_pb2.TaskSpec
            The task to cancel.
        context : grpc.ServicerContext
            The gRPC context.
            
        Returns
        -------
        empty_pb2.Empty
            Empty response.
        """
        logger.info(
            "task_cancelled",
            task_id=request.task_id,
        )
        # Implementation depends on specific algorithm requirements
        return empty_pb2.Empty()
    
    def serve(self, port: int = 50051, max_workers: int = 10) -> None:
        """Start the gRPC server.
        
        Parameters
        ----------
        port : int, optional
            The port to listen on, by default 50051.
        max_workers : int, optional
            Maximum number of worker threads, by default 10.
        """
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
        task_pb2_grpc.add_AlgorithmServiceServicer_to_server(self, server)
        
        server_address = f"[::]:{port}"
        server.add_insecure_port(server_address)
        
        logger.info(
            "starting_server",
            address=server_address,
            algorithm=self.name,
            version=self.version,
        )
        
        server.start()
        
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            logger.info("shutting_down_server")
            server.stop(grace_period=10)
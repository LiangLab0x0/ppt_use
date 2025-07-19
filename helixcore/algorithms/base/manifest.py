"""Manifest loader for algorithm services.

This module provides utilities for loading and validating algorithm
manifest files that describe the capabilities and requirements of
each algorithm microservice.
"""

import os
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field, ValidationError

from helixcore.interfaces.proto import task_pb2


class IOSpecModel(BaseModel):
    """Input/Output specification model."""
    
    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Data type")
    required: bool = Field(True, description="Whether the parameter is required")
    description: str = Field("", description="Parameter description")
    default: Any = Field(None, description="Default value if not required")


class ResourceRequirementsModel(BaseModel):
    """Resource requirements model."""
    
    cpu: float = Field(1.0, description="CPU cores required")
    memory: str = Field("1Gi", description="Memory required (e.g., 1Gi, 512Mi)")
    gpu: int = Field(0, description="Number of GPUs required")
    gpu_type: str = Field("", description="Specific GPU type if required")


class ManifestModel(BaseModel):
    """Algorithm manifest model."""
    
    name: str = Field(..., description="Algorithm name")
    version: str = Field(..., description="Algorithm version")
    description: str = Field("", description="Algorithm description")
    entrypoint: str = Field(..., description="Command to start the service")
    inputs: List[IOSpecModel] = Field(default_factory=list)
    outputs: List[IOSpecModel] = Field(default_factory=list)
    resources: ResourceRequirementsModel = Field(default_factory=ResourceRequirementsModel)
    license: str = Field("MIT", description="License type")
    tags: List[str] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)


class ManifestLoader:
    """Utility class for loading algorithm manifests."""
    
    @staticmethod
    def load(
        manifest_path: str,
        algorithm_name: str,
        algorithm_version: str,
    ) -> task_pb2.AlgorithmManifest:
        """Load and validate an algorithm manifest.
        
        Parameters
        ----------
        manifest_path : str
            Path to the manifest YAML file.
        algorithm_name : str
            Expected algorithm name (for validation).
        algorithm_version : str
            Expected algorithm version (for validation).
            
        Returns
        -------
        task_pb2.AlgorithmManifest
            The loaded and validated manifest as a protobuf message.
            
        Raises
        ------
        FileNotFoundError
            If the manifest file doesn't exist.
        ValidationError
            If the manifest content is invalid.
        ValueError
            If the manifest name/version doesn't match expected values.
        """
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
        
        with open(manifest_path, "r") as f:
            manifest_data = yaml.safe_load(f)
        
        # Validate with Pydantic
        try:
            manifest_model = ManifestModel(**manifest_data)
        except ValidationError as e:
            raise ValidationError(f"Invalid manifest format: {e}")
        
        # Verify name and version match
        if manifest_model.name != algorithm_name:
            raise ValueError(
                f"Manifest name '{manifest_model.name}' doesn't match "
                f"algorithm name '{algorithm_name}'"
            )
        
        if manifest_model.version != algorithm_version:
            raise ValueError(
                f"Manifest version '{manifest_model.version}' doesn't match "
                f"algorithm version '{algorithm_version}'"
            )
        
        # Convert to protobuf
        return ManifestLoader._to_protobuf(manifest_model)
    
    @staticmethod
    def _to_protobuf(manifest: ManifestModel) -> task_pb2.AlgorithmManifest:
        """Convert Pydantic model to protobuf message.
        
        Parameters
        ----------
        manifest : ManifestModel
            The validated manifest model.
            
        Returns
        -------
        task_pb2.AlgorithmManifest
            The protobuf representation of the manifest.
        """
        pb_manifest = task_pb2.AlgorithmManifest(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            entrypoint=manifest.entrypoint,
            license=manifest.license,
            tags=manifest.tags,
            environment=manifest.environment,
        )
        
        # Convert inputs
        for input_spec in manifest.inputs:
            pb_input = task_pb2.IOSpec(
                name=input_spec.name,
                type=ManifestLoader._get_data_type(input_spec.type),
                required=input_spec.required,
                description=input_spec.description,
            )
            pb_manifest.inputs.append(pb_input)
        
        # Convert outputs  
        for output_spec in manifest.outputs:
            pb_output = task_pb2.IOSpec(
                name=output_spec.name,
                type=ManifestLoader._get_data_type(output_spec.type),
                required=True,  # Outputs are always required
                description=output_spec.description,
            )
            pb_manifest.outputs.append(pb_output)
        
        # Convert resources
        pb_manifest.resources.CopyFrom(
            task_pb2.ResourceRequirements(
                cpu=manifest.resources.cpu,
                memory=manifest.resources.memory,
                gpu=manifest.resources.gpu,
                gpu_type=manifest.resources.gpu_type,
            )
        )
        
        return pb_manifest
    
    @staticmethod
    def _get_data_type(type_str: str) -> task_pb2.DataType:
        """Convert string type to protobuf DataType enum.
        
        Parameters
        ----------
        type_str : str
            The type as a string.
            
        Returns
        -------
        task_pb2.DataType
            The corresponding protobuf enum value.
        """
        type_map = {
            "string": task_pb2.DATA_TYPE_STRING,
            "integer": task_pb2.DATA_TYPE_INTEGER,
            "float": task_pb2.DATA_TYPE_FLOAT,
            "boolean": task_pb2.DATA_TYPE_BOOLEAN,
            "array": task_pb2.DATA_TYPE_ARRAY,
            "object": task_pb2.DATA_TYPE_OBJECT,
            "file": task_pb2.DATA_TYPE_FILE,
        }
        return type_map.get(type_str.lower(), task_pb2.DATA_TYPE_UNSPECIFIED)
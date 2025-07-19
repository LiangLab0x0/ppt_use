"""Unit tests for algorithm manifest schema validation.

This module tests the manifest loading and validation functionality
to ensure algorithm services declare proper contracts.
"""

import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from helixcore.algorithms.base.manifest import ManifestLoader, ManifestModel


class TestManifestModel:
    """Test cases for ManifestModel validation."""
    
    def test_valid_manifest(self):
        """Test that a valid manifest passes validation."""
        manifest_data = {
            "name": "test_algorithm",
            "version": "1.0.0",
            "entrypoint": "python -m test",
            "inputs": [
                {
                    "name": "data",
                    "type": "array",
                    "required": True,
                    "description": "Input data array",
                }
            ],
            "outputs": [
                {
                    "name": "result",
                    "type": "float",
                    "description": "Computation result",
                }
            ],
            "resources": {
                "cpu": 2.0,
                "memory": "4Gi",
            },
        }
        
        manifest = ManifestModel(**manifest_data)
        assert manifest.name == "test_algorithm"
        assert manifest.version == "1.0.0"
        assert len(manifest.inputs) == 1
        assert len(manifest.outputs) == 1
    
    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors."""
        with pytest.raises(ValidationError) as exc_info:
            ManifestModel(version="1.0.0")  # Missing name and entrypoint
        
        errors = exc_info.value.errors()
        assert len(errors) >= 2
        field_names = [error["loc"][0] for error in errors]
        assert "name" in field_names
        assert "entrypoint" in field_names
    
    def test_invalid_resource_format(self):
        """Test that invalid resource formats are handled."""
        manifest_data = {
            "name": "test",
            "version": "1.0.0",
            "entrypoint": "python -m test",
            "resources": {
                "cpu": "invalid",  # Should be float
                "memory": "4Gi",
            },
        }
        
        with pytest.raises(ValidationError) as exc_info:
            ManifestModel(**manifest_data)
        
        errors = exc_info.value.errors()
        assert any("cpu" in str(error) for error in errors)
    
    def test_default_values(self):
        """Test that default values are applied correctly."""
        manifest_data = {
            "name": "minimal",
            "version": "0.1.0",
            "entrypoint": "python -m minimal",
        }
        
        manifest = ManifestModel(**manifest_data)
        assert manifest.description == ""
        assert manifest.license == "MIT"
        assert manifest.tags == []
        assert manifest.environment == {}
        assert manifest.resources.cpu == 1.0
        assert manifest.resources.memory == "1Gi"


class TestManifestLoader:
    """Test cases for ManifestLoader functionality."""
    
    def test_load_valid_manifest(self, tmp_path):
        """Test loading a valid manifest file."""
        manifest_content = """
name: test_algorithm
version: 0.1.0
entrypoint: "python -m test"
inputs:
  - name: input_data
    type: string
    required: true
outputs:
  - name: result
    type: float
resources:
  cpu: 2
  memory: "4Gi"
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)
        
        pb_manifest = ManifestLoader.load(
            str(manifest_file),
            "test_algorithm",
            "0.1.0",
        )
        
        assert pb_manifest.name == "test_algorithm"
        assert pb_manifest.version == "0.1.0"
        assert len(pb_manifest.inputs) == 1
        assert pb_manifest.inputs[0].name == "input_data"
    
    def test_load_nonexistent_file(self):
        """Test that loading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ManifestLoader.load(
                "/nonexistent/manifest.yaml",
                "test",
                "1.0.0",
            )
    
    def test_name_mismatch(self, tmp_path):
        """Test that name mismatch raises ValueError."""
        manifest_content = """
name: different_name
version: 0.1.0
entrypoint: "python -m test"
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)
        
        with pytest.raises(ValueError) as exc_info:
            ManifestLoader.load(
                str(manifest_file),
                "expected_name",
                "0.1.0",
            )
        
        assert "doesn't match" in str(exc_info.value)
    
    def test_version_mismatch(self, tmp_path):
        """Test that version mismatch raises ValueError."""
        manifest_content = """
name: test_algorithm
version: 0.2.0
entrypoint: "python -m test"
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)
        
        with pytest.raises(ValueError) as exc_info:
            ManifestLoader.load(
                str(manifest_file),
                "test_algorithm",
                "0.1.0",
            )
        
        assert "doesn't match" in str(exc_info.value)
    
    def test_invalid_yaml(self, tmp_path):
        """Test that invalid YAML raises appropriate error."""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text("invalid: yaml: content:")
        
        with pytest.raises(Exception):  # Could be yaml.YAMLError or ValidationError
            ManifestLoader.load(
                str(manifest_file),
                "test",
                "1.0.0",
            )
    
    def test_data_type_conversion(self):
        """Test conversion of string types to protobuf enums."""
        from helixcore.interfaces.proto import task_pb2
        
        # Test valid conversions
        assert ManifestLoader._get_data_type("string") == task_pb2.DATA_TYPE_STRING
        assert ManifestLoader._get_data_type("integer") == task_pb2.DATA_TYPE_INTEGER
        assert ManifestLoader._get_data_type("float") == task_pb2.DATA_TYPE_FLOAT
        assert ManifestLoader._get_data_type("boolean") == task_pb2.DATA_TYPE_BOOLEAN
        assert ManifestLoader._get_data_type("array") == task_pb2.DATA_TYPE_ARRAY
        assert ManifestLoader._get_data_type("object") == task_pb2.DATA_TYPE_OBJECT
        assert ManifestLoader._get_data_type("file") == task_pb2.DATA_TYPE_FILE
        
        # Test invalid type
        assert ManifestLoader._get_data_type("invalid") == task_pb2.DATA_TYPE_UNSPECIFIED
    
    @pytest.mark.parametrize("gpu_count,gpu_type", [
        (0, ""),
        (1, "nvidia-t4"),
        (2, "nvidia-a100"),
    ])
    def test_gpu_resource_handling(self, tmp_path, gpu_count, gpu_type):
        """Test that GPU resources are handled correctly."""
        manifest_content = f"""
name: gpu_test
version: 1.0.0
entrypoint: "python -m gpu_test"
resources:
  cpu: 4
  memory: "16Gi"
  gpu: {gpu_count}
  gpu_type: "{gpu_type}"
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)
        
        pb_manifest = ManifestLoader.load(
            str(manifest_file),
            "gpu_test",
            "1.0.0",
        )
        
        assert pb_manifest.resources.gpu == gpu_count
        assert pb_manifest.resources.gpu_type == gpu_type
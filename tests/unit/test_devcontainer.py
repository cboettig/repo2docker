"""Unit tests for the DevContainerBuildPack."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from repo2docker.buildpacks.devcontainer import DevContainerBuildPack


@pytest.fixture
def temp_repo():
    """Create a temporary directory for test repositories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(original_cwd)


@pytest.fixture
def base_image():
    return "docker.io/library/buildpack-deps:jammy"


class TestDevContainerDetection:
    """Tests for devcontainer.json detection."""

    def test_detect_root_devcontainer_json(self, temp_repo, base_image):
        """Test detection of devcontainer.json in root."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is True

    def test_detect_dotdevcontainer_json(self, temp_repo, base_image):
        """Test detection of .devcontainer.json in root."""
        config = {"image": "python:3.11"}
        with open(".devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is True

    def test_detect_nested_devcontainer(self, temp_repo, base_image):
        """Test detection of .devcontainer/devcontainer.json."""
        os.makedirs(".devcontainer")
        config = {"image": "python:3.11"}
        with open(".devcontainer/devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is True

    def test_no_detect_without_devcontainer(self, temp_repo, base_image):
        """Test that detection fails without devcontainer.json."""
        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is False

    def test_detect_in_binder_dir(self, temp_repo, base_image):
        """Test detection in binder/ directory."""
        os.makedirs("binder")
        config = {"image": "python:3.11"}
        with open("binder/devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is True


class TestDevContainerConfig:
    """Tests for devcontainer.json parsing."""

    def test_parse_simple_config(self, temp_repo, base_image):
        """Test parsing a simple devcontainer.json."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        parsed = bp._devcontainer_config()
        assert parsed["image"] == "python:3.11"

    def test_parse_config_with_comments(self, temp_repo, base_image):
        """Test parsing devcontainer.json with JSONC comments."""
        content = """{
            // This is a comment
            "image": "python:3.11"
            /* Multi-line
               comment */
        }"""
        with open("devcontainer.json", "w") as f:
            f.write(content)

        bp = DevContainerBuildPack(base_image)
        parsed = bp._devcontainer_config()
        assert parsed["image"] == "python:3.11"

    def test_container_env(self, temp_repo, base_image):
        """Test parsing containerEnv variables."""
        config = {
            "image": "python:3.11",
            "containerEnv": {
                "MY_VAR": "value1",
                "ANOTHER_VAR": "value2"
            }
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        build_env = bp.get_build_env()
        env_dict = dict(build_env)
        assert env_dict.get("MY_VAR") == "value1"
        assert env_dict.get("ANOTHER_VAR") == "value2"

    def test_container_env_skips_local_env_refs(self, temp_repo, base_image):
        """Test that ${localEnv:...} references are skipped."""
        config = {
            "image": "python:3.11",
            "containerEnv": {
                "VALID_VAR": "valid_value",
                "LOCAL_VAR": "${localEnv:HOME}"
            }
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        build_env = bp.get_build_env()
        env_dict = dict(build_env)
        assert env_dict.get("VALID_VAR") == "valid_value"
        assert "LOCAL_VAR" not in env_dict


class TestDevContainerLifecycle:
    """Tests for lifecycle command handling."""

    def test_postcreate_command_string(self, temp_repo, base_image):
        """Test postCreateCommand as a string."""
        config = {
            "image": "python:3.11",
            "postCreateCommand": "echo 'hello'"
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        cmd = bp._format_lifecycle_command(config["postCreateCommand"])
        assert cmd == "echo 'hello'"

    def test_postcreate_command_list(self, temp_repo, base_image):
        """Test postCreateCommand as a list."""
        config = {
            "image": "python:3.11",
            "postCreateCommand": ["echo", "hello", "world"]
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        cmd = bp._format_lifecycle_command(config["postCreateCommand"])
        assert "echo" in cmd
        assert "hello" in cmd
        assert "world" in cmd

    def test_postcreate_command_dict(self, temp_repo, base_image):
        """Test postCreateCommand as a dict (named commands)."""
        config = {
            "image": "python:3.11",
            "postCreateCommand": {
                "install": "pip install -r requirements.txt",
                "setup": "python setup.py develop"
            }
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        cmd = bp._format_lifecycle_command(config["postCreateCommand"])
        assert "pip install" in cmd
        assert "setup.py" in cmd


class TestDevContainerRender:
    """Tests for Dockerfile rendering."""

    def test_render_uses_image(self, temp_repo, base_image):
        """Test that rendered Dockerfile uses specified image."""
        config = {"image": "python:3.11-slim"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render()
        assert "python:3.11-slim" in dockerfile

    def test_render_includes_jupyterlab(self, temp_repo, base_image):
        """Test that rendered Dockerfile installs JupyterLab."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render()
        assert "jupyterlab" in dockerfile.lower()


class TestDevContainerDockerfile:
    """Tests for custom Dockerfile handling."""

    def test_has_custom_dockerfile(self, temp_repo, base_image):
        """Test detection of custom Dockerfile."""
        os.makedirs(".devcontainer")
        config = {
            "build": {
                "dockerfile": "Dockerfile"
            }
        }
        with open(".devcontainer/devcontainer.json", "w") as f:
            json.dump(config, f)
        with open(".devcontainer/Dockerfile", "w") as f:
            f.write("FROM python:3.11\n")

        bp = DevContainerBuildPack(base_image)
        assert bp._has_custom_dockerfile() is True

    def test_custom_dockerfile_path(self, temp_repo, base_image):
        """Test resolving custom Dockerfile path."""
        os.makedirs(".devcontainer")
        config = {
            "build": {
                "dockerfile": "Dockerfile",
                "context": "."
            }
        }
        with open(".devcontainer/devcontainer.json", "w") as f:
            json.dump(config, f)
        with open(".devcontainer/Dockerfile", "w") as f:
            f.write("FROM python:3.11\n")

        bp = DevContainerBuildPack(base_image)
        path = bp._get_dockerfile_path()
        assert "Dockerfile" in path

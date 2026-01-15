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


class TestJupyterHubCompatibility:
    """
    Tests for JupyterHub compatibility requirements.
    
    These tests verify the three critical "gotchas" for JupyterHub:
    1. jupyterhub-singleuser must be installed and on PATH
    2. User must have UID 1000
    3. Packages must be installed to /opt/venv (not /home which gets bind-mounted)
    """

    def test_standalone_dockerfile_installs_jupyterhub(self, temp_repo, base_image):
        """Test that render_standalone installs jupyterhub package (provides jupyterhub-singleuser)."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Must install jupyterhub (not just jupyterlab)
        assert "jupyterhub" in dockerfile.lower()
        # CMD should use jupyterhub-singleuser
        assert "jupyterhub-singleuser" in dockerfile

    def test_standalone_dockerfile_uses_uid_1000(self, temp_repo, base_image):
        """Test that user is created with UID 1000 (required by JupyterHub)."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Must use UID 1000
        assert "NB_UID=1000" in dockerfile
        assert "--uid 1000" in dockerfile
        assert "--gid 1000" in dockerfile

    def test_standalone_dockerfile_installs_to_opt_venv(self, temp_repo, base_image):
        """
        Test that packages install to /opt/venv, NOT ~/.local.
        
        JupyterHub bind-mounts /home/jovyan, so anything in ~/.local/bin
        gets wiped at runtime. We must install to /opt/venv instead.
        """
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Must create virtualenv in /opt
        assert "VIRTUAL_ENV=/opt/venv" in dockerfile
        # Must add /opt/venv/bin to PATH
        assert "$VIRTUAL_ENV/bin" in dockerfile
        # PATH must include venv bin directory
        assert "PATH=$VIRTUAL_ENV/bin" in dockerfile

    def test_standalone_dockerfile_chowns_opt_venv(self, temp_repo, base_image):
        """Test that /opt/venv is owned by UID 1000 so user can write to it."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Must chown the venv to user 1000
        assert "chown -R 1000:1000 $VIRTUAL_ENV" in dockerfile

    def test_standalone_dockerfile_copies_repo_with_correct_ownership(self, temp_repo, base_image):
        """Test that repository files are copied with UID 1000 ownership."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Must COPY with correct ownership
        assert "COPY --chown=1000:1000" in dockerfile

    def test_standalone_dockerfile_exposes_port_8888(self, temp_repo, base_image):
        """Test that port 8888 is exposed for JupyterHub."""
        config = {"image": "python:3.11"}
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        assert "EXPOSE 8888" in dockerfile


class TestBuildArgsSupport:
    """Tests for build.args support in devcontainer.json."""

    def test_build_args_parsed(self, temp_repo, base_image):
        """Test that build.args are parsed from devcontainer.json."""
        config = {
            "build": {
                "dockerfile": "Dockerfile",
                "args": {
                    "MY_ARG": "my_value",
                    "ANOTHER_ARG": "another_value"
                }
            }
        }
        os.makedirs(".devcontainer")
        with open(".devcontainer/devcontainer.json", "w") as f:
            json.dump(config, f)
        with open(".devcontainer/Dockerfile", "w") as f:
            f.write("FROM python:3.11\n")

        bp = DevContainerBuildPack(base_image)
        parsed_config = bp._devcontainer_config()
        assert parsed_config["build"]["args"]["MY_ARG"] == "my_value"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_devcontainer_json(self, temp_repo, base_image):
        """Test handling of empty devcontainer.json (uses default image)."""
        with open("devcontainer.json", "w") as f:
            json.dump({}, f)

        bp = DevContainerBuildPack(base_image)
        assert bp.detect() is True
        # Should fall back to base image
        assert bp._get_base_image() == base_image

    def test_respects_custom_image(self, temp_repo, base_image):
        """Test that any user-specified image is respected."""
        # Test with various real-world base images
        test_images = [
            "mcr.microsoft.com/devcontainers/python:3.11",
            "nvidia/cuda:12.0-devel-ubuntu22.04",
            "rocker/rstudio:latest",
            "continuumio/miniconda3",
            "ghcr.io/prefix-dev/pixi:latest",
        ]
        
        for image in test_images:
            config = {"image": image}
            with open("devcontainer.json", "w") as f:
                json.dump(config, f)

            bp = DevContainerBuildPack(base_image)
            # Clear cache
            bp._devcontainer_config.cache_clear()
            bp._get_base_image.cache_clear()
            
            assert bp._get_base_image() == image, f"Failed for image: {image}"

    def test_lifecycle_command_with_special_characters(self, temp_repo, base_image):
        """Test lifecycle commands with shell special characters."""
        config = {
            "image": "python:3.11",
            "postCreateCommand": "echo 'hello $USER' && pip install --upgrade pip"
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        dockerfile = bp.render_standalone()
        
        # Command should be included
        assert "echo 'hello $USER'" in dockerfile

    def test_container_env_with_equals_sign(self, temp_repo, base_image):
        """Test containerEnv with values containing equals signs."""
        config = {
            "image": "python:3.11",
            "containerEnv": {
                "DATABASE_URL": "postgres://user:pass@host:5432/db?sslmode=require"
            }
        }
        with open("devcontainer.json", "w") as f:
            json.dump(config, f)

        bp = DevContainerBuildPack(base_image)
        # Clear cache from previous tests
        bp._devcontainer_config.cache_clear()
        bp.get_build_env.cache_clear()
        
        build_env = bp.get_build_env()
        env_dict = dict(build_env)
        assert env_dict.get("DATABASE_URL") == "postgres://user:pass@host:5432/db?sslmode=require"


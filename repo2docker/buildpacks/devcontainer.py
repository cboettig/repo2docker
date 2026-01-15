"""BuildPack for DevContainer environments (.devcontainer/devcontainer.json)

This buildpack supports the Development Containers specification:
https://containers.dev/

It enables users to leverage existing devcontainer.json configurations
with JupyterHub/repo2docker by automatically installing JupyterLab
on top of the devcontainer environment.
"""

import json
import os
import re
import textwrap
from functools import lru_cache

from .base import BaseImage, BuildPack

# Default devcontainer paths to check in order of priority
DEVCONTAINER_PATHS = [
    ".devcontainer/devcontainer.json",
    ".devcontainer.json",
    "devcontainer.json",
]


class DevContainerBuildPack(BuildPack):
    """
    A BuildPack for Development Container (devcontainer.json) configurations.

    Supports the Development Containers specification to enable repo2docker
    users to leverage existing devcontainer configurations. Automatically
    installs JupyterLab/notebook for JupyterHub compatibility.

    Supported devcontainer.json properties:
    - image: Base container image
    - build.dockerfile: Path to a Dockerfile
    - build.context: Docker build context
    - containerEnv: Environment variables for the container
    - postCreateCommand: Commands run after container creation
    - onCreateCommand: Commands run when container is created
    - features: (Phase 2 - partial support)
    """

    @lru_cache
    def _devcontainer_path(self):
        """
        Find the devcontainer.json file in the repository.

        Checks multiple possible locations in order of priority:
        1. .devcontainer/devcontainer.json (standard location)
        2. .devcontainer.json (root level, hidden)
        3. devcontainer.json (root level)

        Also checks within binder/ or .binder/ directories.

        Returns:
            str or None: Path to the devcontainer.json file, or None if not found.
        """
        # First check in binder directory
        for path in DEVCONTAINER_PATHS:
            full_path = self.binder_path(path)
            if os.path.exists(full_path):
                return full_path

        # Then check in root (if not using binder dir)
        if not self.binder_dir:
            for path in DEVCONTAINER_PATHS:
                if os.path.exists(path):
                    return path

        return None

    @lru_cache
    def _devcontainer_config(self):
        """
        Parse and return the devcontainer.json configuration.

        Returns:
            dict: Parsed devcontainer.json contents, or empty dict if not found.
        """
        config_path = self._devcontainer_path()
        if config_path is None:
            return {}

        with open(config_path) as f:
            # Handle JSON with comments (JSONC) - strip comments safely
            content = f.read()
            content = self._strip_jsonc_comments(content)
            return json.loads(content)

    def _strip_jsonc_comments(self, content):
        """
        Strip JSONC comments while respecting quoted strings.
        
        Simple regex like `//.*$` incorrectly strips // inside strings (like URLs).
        This method properly handles:
        - Single-line comments: // comment
        - Multi-line comments: /* comment */
        - Strings containing // or /* (e.g., URLs)
        """
        result = []
        i = 0
        in_string = False
        escape_next = False
        
        while i < len(content):
            char = content[i]
            
            if escape_next:
                result.append(char)
                escape_next = False
                i += 1
                continue
            
            if char == '\\' and in_string:
                result.append(char)
                escape_next = True
                i += 1
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                result.append(char)
                i += 1
                continue
            
            if not in_string:
                # Check for single-line comment
                if content[i:i+2] == '//':
                    # Skip until end of line
                    while i < len(content) and content[i] != '\n':
                        i += 1
                    continue
                
                # Check for multi-line comment
                if content[i:i+2] == '/*':
                    # Skip until */
                    i += 2
                    while i < len(content) - 1:
                        if content[i:i+2] == '*/':
                            i += 2
                            break
                        i += 1
                    continue
            
            result.append(char)
            i += 1
        
        return ''.join(result)

    @lru_cache
    def _devcontainer_dir(self):
        """
        Return the directory containing devcontainer.json.

        This is needed for resolving relative paths in the config
        (like build.dockerfile and build.context).
        """
        config_path = self._devcontainer_path()
        if config_path:
            return os.path.dirname(config_path)
        return ""

    def detect(self):
        """
        Check if current repo should be built with the DevContainer BuildPack.

        Returns:
            bool: True if a devcontainer.json file exists.
        """
        return self._devcontainer_path() is not None

    @lru_cache
    def _get_base_image(self):
        """
        Determine the base image to use from devcontainer.json.

        Priority:
        1. Direct 'image' property
        2. Falls back to default buildpack-deps if neither specified

        Returns:
            str: Docker image reference
        """
        config = self._devcontainer_config()

        # Direct image specification
        if "image" in config:
            return config["image"]

        # Check for build.dockerfile - we'll handle this separately
        if "build" in config and "dockerfile" in config.get("build", {}):
            # When using Dockerfile, we'll use a different render path
            return None

        # Default fallback
        return self.base_image

    def _has_custom_dockerfile(self):
        """Check if the devcontainer specifies a custom Dockerfile."""
        config = self._devcontainer_config()
        return "build" in config and "dockerfile" in config.get("build", {})

    def _get_dockerfile_path(self):
        """Get the path to the custom Dockerfile if specified."""
        config = self._devcontainer_config()
        build_config = config.get("build", {})

        if "dockerfile" not in build_config:
            return None

        dockerfile = build_config["dockerfile"]
        context = build_config.get("context", ".")
        devcontainer_dir = self._devcontainer_dir()

        # Resolve the Dockerfile path relative to the devcontainer directory
        # and the context
        if devcontainer_dir:
            # If context is specified, it's relative to devcontainer.json location
            full_context = os.path.join(devcontainer_dir, context)
            dockerfile_path = os.path.normpath(
                os.path.join(full_context, dockerfile)
            )
        else:
            dockerfile_path = os.path.normpath(os.path.join(context, dockerfile))

        return dockerfile_path

    @lru_cache
    def get_build_env(self):
        """
        Return environment variables for the build phase.

        Includes variables from containerEnv in devcontainer.json.
        """
        env = super().get_build_env()

        # Add containerEnv variables
        config = self._devcontainer_config()
        container_env = config.get("containerEnv", {})

        for key, value in container_env.items():
            # Skip variables that use unsupported variable substitutions
            # ${localEnv:...} and similar won't work in container context
            if "${localEnv:" not in value and "${localWorkspaceFolder" not in value:
                env.append((key, value))

        return env

    @lru_cache
    def get_env(self):
        """Return environment variables to be set after build."""
        env = super().get_env()

        # Add remoteEnv variables if present
        config = self._devcontainer_config()
        remote_env = config.get("remoteEnv", {})

        for key, value in remote_env.items():
            if "${localEnv:" not in value and "${localWorkspaceFolder" not in value:
                env.append((key, value))

        return env

    @lru_cache
    def get_base_packages(self):
        """
        Base set of apt packages for devcontainer builds.

        Includes packages commonly needed for development environments.
        """
        packages = super().get_base_packages()
        # Add common development packages
        packages.update({
            "git",
            "curl",
            "wget",
            "ca-certificates",
        })
        return packages

    @lru_cache
    def get_path(self):
        """Return paths to be added to PATH."""
        return super().get_path() + ["/usr/local/bin"]

    @lru_cache
    def get_build_scripts(self):
        """
        Return build scripts for setting up the devcontainer environment.

        This includes:
        1. Installing pip and JupyterLab for JupyterHub compatibility
        2. Running onCreateCommand if specified
        """
        scripts = super().get_build_scripts()

        # Install Python and JupyterLab for JupyterHub compatibility
        # This is essential since JupyterHub expects these to be present
        scripts.append((
            "root",
            r"""
            apt-get -qq update && \
            apt-get -qq install --yes --no-install-recommends \
                python3 \
                python3-pip \
                python3-venv \
                > /dev/null && \
            apt-get -qq purge && \
            apt-get -qq clean && \
            rm -rf /var/lib/apt/lists/*
            """
        ))

        return scripts

    @lru_cache
    def get_assemble_scripts(self):
        """
        Return scripts to assemble the devcontainer environment.

        Handles lifecycle commands from devcontainer.json:
        - onCreateCommand: Run when container is created
        - postCreateCommand: Run after container creation
        """
        scripts = super().get_assemble_scripts()

        config = self._devcontainer_config()

        # Install JupyterLab as the user (for JupyterHub compatibility)
        scripts.append((
            "${NB_USER}",
            r"""
            python3 -m pip install --no-cache-dir \
                jupyterlab \
                notebook
            """
        ))

        # Run onCreateCommand if specified
        on_create = config.get("onCreateCommand")
        if on_create:
            cmd = self._format_lifecycle_command(on_create)
            if cmd:
                scripts.append(("${NB_USER}", cmd))

        # Run postCreateCommand if specified
        post_create = config.get("postCreateCommand")
        if post_create:
            cmd = self._format_lifecycle_command(post_create)
            if cmd:
                scripts.append(("${NB_USER}", cmd))

        return scripts

    def _format_lifecycle_command(self, command):
        """
        Format a lifecycle command from devcontainer.json.

        Commands can be:
        - A string: executed in shell
        - A list: executed directly
        - A dict: multiple named commands (run sequentially)

        Args:
            command: The command specification from devcontainer.json

        Returns:
            str: Formatted shell command, or None if invalid
        """
        if command is None:
            return None

        if isinstance(command, str):
            # Simple string command
            return command

        if isinstance(command, list):
            # Array of command parts - join with spaces
            # Escape each part properly
            import shlex
            return " ".join(shlex.quote(str(part)) for part in command)

        if isinstance(command, dict):
            # Named commands - run sequentially
            commands = []
            for name, cmd in command.items():
                formatted = self._format_lifecycle_command(cmd)
                if formatted:
                    commands.append(f"# {name}")
                    commands.append(formatted)
            return " && \\\n".join(commands) if commands else None

        return None

    @lru_cache
    def get_post_build_scripts(self):
        """
        Return post-build scripts.

        Handles postStartCommand as a post-build script since it's meant
        to run after the container is fully set up.
        """
        scripts = super().get_post_build_scripts()

        config = self._devcontainer_config()

        # Handle updateContentCommand if specified
        update_content = config.get("updateContentCommand")
        if update_content:
            # For now, we don't have a good way to run this as a script
            # since it needs to be in the repo. Skip for now.
            pass

        return scripts

    # Known proprietary extensions not available on Open VSX
    PROPRIETARY_EXTENSIONS = {
        "ms-python.vscode-pylance",
        "ms-vscode.cpptools",
        "ms-dotnettools.csharp",
        "ms-vscode-remote.remote-ssh",
        "ms-vscode-remote.remote-containers",
        "ms-vscode-remote.remote-wsl",
        "github.copilot",
        "github.copilot-chat",
    }

    # Extension ID mappings from devcontainer.json to Open VSX
    # Most extensions use the same ID, but some differ
    EXTENSION_MAPPINGS = {
        # Add any known mappings here if publishers differ on Open VSX
    }

    def _get_vscode_extensions(self):
        """
        Extract VS Code extensions from devcontainer.json.
        
        Supports the customizations.vscode.extensions property per the
        Dev Container specification.
        
        Returns:
            list: List of extension IDs to install
        """
        config = self._devcontainer_config()
        customizations = config.get("customizations", {})
        vscode = customizations.get("vscode", {})
        return vscode.get("extensions", [])

    def _map_extension_to_openvsx(self, extension_id):
        """
        Map a VS Code extension ID to its Open VSX equivalent.
        
        Args:
            extension_id: The extension ID from devcontainer.json
            
        Returns:
            tuple: (mapped_id, warning_message or None)
        """
        # Check if it's a known proprietary extension
        if extension_id in self.PROPRIETARY_EXTENSIONS:
            return None, f"Extension '{extension_id}' is proprietary and not available on Open VSX"
        
        # Check if we have a specific mapping
        if extension_id in self.EXTENSION_MAPPINGS:
            mapped_id = self.EXTENSION_MAPPINGS[extension_id]
            return mapped_id, f"Extension '{extension_id}' mapped to '{mapped_id}' for Open VSX"
        
        # Most extensions use the same ID on Open VSX
        return extension_id, None

    def _generate_extension_install_commands(self):
        """
        Generate Dockerfile RUN commands to install VS Code extensions.
        
        Returns:
            tuple: (dockerfile_commands, warnings)
        """
        extensions = self._get_vscode_extensions()
        if not extensions:
            return "", []
        
        warnings = []
        valid_extensions = []
        
        for ext in extensions:
            mapped_id, warning = self._map_extension_to_openvsx(ext)
            if warning:
                warnings.append(warning)
            if mapped_id:
                valid_extensions.append(mapped_id)
        
        if not valid_extensions:
            return "", warnings
        
        # Generate installation commands
        install_cmds = " && \\\n    ".join(
            f"openvscode-server --install-extension {ext}" 
            for ext in valid_extensions
        )
        
        dockerfile_cmds = f"""
# Install VS Code extensions from Open VSX registry
# Note: Extensions are sourced from https://open-vsx.org (not Microsoft marketplace)
RUN {install_cmds}
"""
        return dockerfile_cmds, warnings

    def render_standalone(self, build_args=None):
        """
        Render a standalone Dockerfile that works without repo2docker infrastructure.

        This generates a Dockerfile that can be committed to a repo and built
        by standard Docker/BinderHub without requiring this fork of repo2docker.
        It doesn't rely on repo2docker's helper files (entrypoint scripts, etc.)

        Args:
            build_args: Build arguments dict

        Returns:
            str: Complete, self-contained Dockerfile content
        """
        build_args = build_args or {}
        config = self._devcontainer_config()

        # Get base image
        base_image = self._get_base_image() or self.base_image

        nb_user = build_args.get("NB_USER", "jovyan")
        nb_uid = build_args.get("NB_UID", "1000")

        # Container environment variables
        container_env = config.get("containerEnv", {})
        env_lines = ""
        for key, value in container_env.items():
            if "${localEnv:" not in value and "${localWorkspaceFolder" not in value:
                env_lines += f"ENV {key}={value}\n"

        # Lifecycle commands
        on_create = config.get("onCreateCommand")
        post_create = config.get("postCreateCommand")

        lifecycle_cmds = ""
        if on_create:
            cmd = self._format_lifecycle_command(on_create)
            if cmd:
                lifecycle_cmds += f"RUN {cmd}\n\n"
        if post_create:
            cmd = self._format_lifecycle_command(post_create)
            if cmd:
                lifecycle_cmds += f"RUN {cmd}\n\n"

        # Generate VS Code extension installation commands
        extension_cmds, extension_warnings = self._generate_extension_install_commands()
        
        # Print warnings about extension mappings/unavailability
        for warning in extension_warnings:
            print(f"Warning: {warning}")

        dockerfile = f'''FROM {base_image}

# =============================================================================
# NOTE: This Dockerfile assumes a Debian/Ubuntu-based image with apt-get.
# Alpine (apk), RHEL (yum/dnf), or other distros will require modifications.
# =============================================================================

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Set up locales properly
RUN apt-get -qq update && \\
    apt-get -qq install --yes --no-install-recommends locales > /dev/null && \\
    apt-get -qq purge && \\
    apt-get -qq clean && \\
    rm -rf /var/lib/apt/lists/*

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \\
    locale-gen

ENV LC_ALL=en_US.UTF-8 \\
    LANG=en_US.UTF-8 \\
    LANGUAGE=en_US.UTF-8

# Use bash as default shell
ENV SHELL=/bin/bash

# Set up user - MUST be UID 1000 for JupyterHub compatibility
ARG NB_USER={nb_user}
ARG NB_UID=1000
ENV USER=${{NB_USER}} \\
    HOME=/home/${{NB_USER}} \\
    NB_USER=${{NB_USER}} \\
    NB_UID=1000

RUN groupadd --gid 1000 ${{NB_USER}} && \\
    useradd --comment "Default user" --create-home --gid 1000 \\
            --no-log-init --shell /bin/bash --uid 1000 ${{NB_USER}}

# Install base packages
RUN apt-get -qq update && \\
    apt-get -qq install --yes --no-install-recommends \\
        ca-certificates \\
        curl \\
        git \\
        less \\
        unzip \\
        wget \\
        python3 \\
        python3-pip \\
        python3-venv \\
        > /dev/null && \\
    apt-get -qq purge && \\
    apt-get -qq clean && \\
    rm -rf /var/lib/apt/lists/*

# Ensure pip scripts are on PATH (required for jupyterhub-singleuser)
ENV PATH=${{HOME}}/.local/bin:$PATH

# Create Python virtual environment in /opt (survives JupyterHub bind-mount of /home)
# JupyterHub bind-mounts /home/jovyan, wiping ~/.local/bin - so we install to /opt
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV && \\
    chown -R 1000:1000 $VIRTUAL_ENV
ENV PATH=$VIRTUAL_ENV/bin:$PATH

EXPOSE 8888

# Install openvscode-server for VS Code in browser (must run as root to write to /opt)
# Using openvscode-server (Gitpod) for better upstream VS Code alignment
# Note: We query GitHub API to get correct download URL (filename includes version)
RUN OVSCODE_VERSION=$(curl -sL https://api.github.com/repos/gitpod-io/openvscode-server/releases/latest | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\\1/') && \\
    curl -fsSL "https://github.com/gitpod-io/openvscode-server/releases/download/${{OVSCODE_VERSION}}/${{OVSCODE_VERSION}}-linux-x64.tar.gz" | \\
    tar -xz -C /opt && \\
    mv /opt/openvscode-server-* /opt/openvscode-server && \\
    chown -R 1000:1000 /opt/openvscode-server

ENV PATH=/opt/openvscode-server/bin:$PATH

# Configure openvscode-server to use Open VSX registry (not Microsoft marketplace)
ENV OPENVSCODE_SERVER_EXTENSIONS_DIR=/opt/openvscode-server/extensions

# Environment variables from devcontainer.json
{env_lines}
# Set working directory
ARG REPO_DIR=${{HOME}}
ENV REPO_DIR=${{REPO_DIR}}
WORKDIR ${{REPO_DIR}}

# Copy repository contents
COPY --chown=1000:1000 . ${{REPO_DIR}}/

# Switch to user for pip installs and extensions
USER ${{NB_USER}}

# Install JupyterHub requirements to /opt/venv (not ~/.local which gets bind-mounted)
# jupyterhub provides jupyterhub-singleuser which is REQUIRED for JupyterHub
# jupyter-vscode-proxy enables VS Code (openvscode-server) in JupyterHub
RUN pip install --no-cache-dir \\
    jupyterhub \\
    jupyterlab \\
    notebook \\
    jupyter-vscode-proxy
{extension_cmds}

# Run lifecycle commands from devcontainer.json
{lifecycle_cmds}
# JupyterHub will provide the start command (jupyterhub-singleuser)
# This CMD is a fallback for standalone usage
CMD ["jupyterhub-singleuser", "--ip=0.0.0.0", "--port=8888"]
'''
        return dockerfile

    def render(self, build_args=None):
        """
        Render the BuildPack into a Dockerfile.

        If a custom Dockerfile is specified in devcontainer.json,
        we extend it with our JupyterHub-required additions.
        Otherwise, we use the standard buildpack rendering with
        the specified base image.
        """
        build_args = build_args or {}

        if self._has_custom_dockerfile():
            # Custom Dockerfile mode - read and extend the user's Dockerfile
            return self._render_with_custom_dockerfile(build_args)

        # Standard mode - use the image from devcontainer.json
        base_image = self._get_base_image()
        if base_image:
            self.base_image = base_image

        return super().render(build_args)

    def _render_with_custom_dockerfile(self, build_args):
        """
        Render a Dockerfile that extends the user's custom Dockerfile.

        This approach:
        1. Uses a multi-stage build
        2. First stage uses the user's Dockerfile
        3. Second stage adds JupyterHub requirements
        """
        dockerfile_path = self._get_dockerfile_path()
        config = self._devcontainer_config()
        build_config = config.get("build", {})

        # Read the user's Dockerfile
        with open(dockerfile_path) as f:
            user_dockerfile = f.read()

        # Get build args from devcontainer.json
        devcontainer_build_args = build_config.get("args", {})

        # Build the extended Dockerfile
        nb_user = build_args.get("NB_USER", "jovyan")
        nb_uid = build_args.get("NB_UID", "1000")

        # We need to extend the user's Dockerfile with our additions
        dockerfile = f"""{user_dockerfile}

# --- repo2docker additions for JupyterHub compatibility ---

# Set up user if not already set
ARG NB_USER={nb_user}
ARG NB_UID={nb_uid}
ENV USER=${{NB_USER}} \\
    HOME=/home/${{NB_USER}}

# Create user if it doesn't exist
RUN if ! id -u ${{NB_USER}} > /dev/null 2>&1; then \\
        groupadd --gid ${{NB_UID}} ${{NB_USER}} && \\
        useradd --comment "Default user" --create-home --gid ${{NB_UID}} \\
                --no-log-init --shell /bin/bash --uid ${{NB_UID}} ${{NB_USER}}; \\
    fi

# Ensure Python and JupyterLab are installed
RUN apt-get -qq update && \\
    apt-get -qq install --yes --no-install-recommends \\
        python3 python3-pip python3-venv > /dev/null && \\
    apt-get -qq purge && apt-get -qq clean && \\
    rm -rf /var/lib/apt/lists/*

USER ${{NB_USER}}

RUN python3 -m pip install --no-cache-dir jupyterlab notebook

# Set working directory
ARG REPO_DIR=${{HOME}}
ENV REPO_DIR=${{REPO_DIR}}
WORKDIR ${{REPO_DIR}}

EXPOSE 8888

CMD ["jupyter", "notebook", "--ip", "0.0.0.0"]
"""

        # Add lifecycle commands
        on_create = config.get("onCreateCommand")
        if on_create:
            cmd = self._format_lifecycle_command(on_create)
            if cmd:
                dockerfile += f"\nRUN {cmd}\n"

        post_create = config.get("postCreateCommand")
        if post_create:
            cmd = self._format_lifecycle_command(post_create)
            if cmd:
                dockerfile += f"\nRUN {cmd}\n"

        return dockerfile

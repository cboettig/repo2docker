# DevContainer + OpenVSCode Server Walkthrough

This guide covers running repo2docker-generated images with JupyterLab and OpenVSCode Server.

## Quick Start

### Generate Dockerfile from devcontainer.json

```bash
python -m repo2docker --write-dockerfile Dockerfile ./your-repo
cd your-repo
docker build -t myimage:latest .
```

---

## Running Locally

### Option 1: JupyterLab with VS Code Proxy

Run JupyterLab with full VS Code integration:

```bash
docker run --rm -p 8888:8888 myimage:latest \
  jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --ServerApp.token=''
```

| Service | URL |
|---------|-----|
| JupyterLab | http://localhost:8888/lab |
| VS Code (proxy) | http://localhost:8888/vscode/ |

---

### Option 2: OpenVSCode Server Direct

Run VS Code in browser directly (bypasses JupyterHub):

```bash
docker run --rm -p 3000:3000 myimage:latest \
  openvscode-server --host 0.0.0.0 --port 3000 --without-connection-token
```

| Service | URL |
|---------|-----|
| VS Code | http://localhost:3000 |

> **Tip**: This mode is ideal for pure VS Code development without JupyterLab/Notebook.

---

### Option 3: JupyterHub (Production)

The default `CMD` uses `jupyterhub-singleuser`, which requires JupyterHub environment variables:

```bash
# Requires: JUPYTERHUB_SERVICE_URL, JUPYTERHUB_API_TOKEN, etc.
jupyterhub-singleuser --ip=0.0.0.0 --port=8888
```

---

## Features Verified

| Feature | Status |
|---------|--------|
| VS Code Extensions (from Open VSX) | ✅ |
| jupyter-vscode-proxy integration | ✅ |
| containerEnv variables | ✅ |
| postCreateCommand execution | ✅ |
| JupyterLab + Notebook | ✅ |

---

## Example devcontainer.json

```json
{
    "name": "Python DevContainer",
    "image": "python:3.11-slim",
    "containerEnv": {
        "MY_VAR": "hello"
    },
    "postCreateCommand": "pip install numpy",
    "customizations": {
        "vscode": {
            "extensions": [
                "ms-python.python",
                "charliermarsh.ruff"
            ]
        }
    }
}
```

---

## Notes

- **Proprietary extensions** (pylance, copilot) are not available on Open VSX
- **Alpine images** not currently supported (requires apt-get)
- **UID 1000** is required for JupyterHub compatibility

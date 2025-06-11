# KGCompass
<div align="center">

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![arXiv](https://img.shields.io/badge/arXiv-2503.21710-b31b1b.svg)](https://arxiv.org/abs/2503.21710)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

</div>

KGCompass is a novel approach for repository-level software repair that accurately links code structure with repository metadata using a knowledge graph, enabling more precise bug localization and patch generation.

Paper link: https://arxiv.org/abs/2503.21710

![KGCompass Trajectory Visualization](https://gcdnb.pbrd.co/images/pXnwAe3e5YlQ.png?o=1)

## Fully Containerized Workflow with GPU Support

This project uses Docker and Docker Compose to provide a fully reproducible environment. The setup includes:
- A base image with CUDA and Python pre-installed.
- A service for the Neo4j database with necessary plugins.
- An application service with all Python dependencies and access to the host's GPU.

### Prerequisites

1.  **NVIDIA GPU & Drivers**: A compatible NVIDIA GPU with recent drivers installed on your host machine.
2.  **NVIDIA Container Toolkit**: You must install this on your host to allow Docker to use the GPU. For Debian/Ubuntu-based systems, you can do so by running the following command block in your terminal:
    ```bash
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
    && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
      sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list \
    && sudo apt-get update \
    && sudo apt-get install -y nvidia-container-toolkit \
    && sudo nvidia-ctk runtime configure --runtime=docker \
    && sudo systemctl restart docker
    ```
3.  **Docker & Docker Compose**: This project uses Docker Compose V1.
    *   Ensure Docker is installed on your system.
    *   Install Docker Compose V1 (if not already present) by running:
    ```bash
    LATEST_COMPOSE_V1="1.29.2"
    sudo curl -L "https://github.com/docker/compose/releases/download/${LATEST_COMPOSE_V1}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    ```
4.  **API Keys**: Create a `.env` file in the project root by copying the example:
    ```bash
    cp .env.example .env
    ```
    Then, edit the `.env` file and fill in your `GITHUB_TOKEN`, and `BAILIAN_API_KEY`.

**Step 1: Build and Start All Services**

This single command will build the base CUDA image, the Neo4j image, and the final application image, then start all services in the background.

```bash
docker-compose up -d --build
```

**Step 2: Run the Repair Pipeline**

Execute the repair script *inside* the application container. The container will have access to the GPU.

```bash
docker-compose exec app bash run_repair.sh <instance_id>

# Example:
docker-compose exec app bash run_repair.sh astropy__astropy-12907
```

**Step 3: Stopping the Environment**
```bash
docker-compose down -v
```

# Use an official NVIDIA CUDA runtime image as a parent image
# This provides the necessary CUDA and cuDNN libraries and Python 3.10
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Set environment variables to prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# The base image comes with Python 3.10. We install pip, git, and build tools.
# python3.10-dev is required for building C++ extensions that need Python.h
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    git \
    build-essential \
    python3.10-dev \
    && rm -rf /var/lib/apt/lists/* 
# Use the pre-built base image with CUDA and Python
FROM kgcompass-base:latest

# Set the working directory in the container
WORKDIR /opt/KGCompass

# First, install PyTorch and its related packages for CUDA 12.1
# This ensures we get a compatible version for the GPU
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Copy the requirements file into the container
COPY requirements.txt .

# Install the rest of the packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY . .

# Keep the container running to allow for exec commands
CMD ["tail", "-f", "/dev/null"] 
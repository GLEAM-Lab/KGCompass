# Use the pre-built base image with CUDA and Python
FROM kgcompass-base:latest

# Set the working directory in the container
WORKDIR /opt/KGCompass

# First, install torch and torchvision from the official index to ensure GPU compatibility.
# We specify versions to prevent pip from trying to resolve multiple versions.
COPY requirements.txt .
RUN pip install torch==2.3.1+cu121 torchvision==0.18.1+cu121 torchaudio --index-url https://download.pytorch.org/whl/cu121

# Second, install the remaining requirements.
# The `--no-deps` flag could be used if there are irresolvable conflicts,
# but for now, we let pip handle the dependencies, which should be fine
# now that torch is pinned.
RUN pip install -r requirements.txt

# Copy the rest of the application's code into the container
COPY . .

# Keep the container running to allow for exec commands
CMD ["tail", "-f", "/dev/null"] 
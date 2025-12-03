# This Dockerfile sets up a Python application.
# Note: This image alone won't allow connections to a Lavalink server running on your *host* machine via 'localhost'.
#       If you're using a local Lavalink server, either use the option '-e LAVALINK_HOST=host.docker.internal' when running the container 
#       or use the host machine's IP address instead of 'LAVALINK_HOST=localhost' or the docker internale network 'LAVALINK_HOST=host.docker.internal' in your bot's config.

# Docker causes more buffering issues with the audio. Running directly on the host is recommended for best performance. Same goes for running Lavalink in Docker.

# Build the Docker image with: docker build -t molten-musicbot .
# After building the image, run the container with: docker run -d -e LAVALINK_HOST=host.docker.internal --name molten-musicbot molten-musicbot
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "src/main.py"]
# This Dockerfile sets up a Python application.
# Note: This image alone won't allow connections to a Lavalink server running on your *host* machine via 'localhost'.
#       If you're using a local Lavalink server, either run it in the same Docker network (via Docker Compose),
#       or use the host machine's IP address instead of 'localhost' in your bot's config.

FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install -r requirements.txt

CMD ["python", "src/main.py"]

RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    gcc \
    build-essential \
    python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


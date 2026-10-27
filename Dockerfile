FROM python:3.10-slim

# Install system dependencies required for OpenCV, ffmpeg, and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download NudeNet model weights during build so the service boots immediately without download delays
RUN python -c "from nudenet import NudeDetector; NudeDetector()"

# Copy application source code
COPY . .

# Set default port (Railway overrides with $PORT at runtime)
ENV PORT=5003
EXPOSE 5003

# Run gunicorn: 1 worker with 2 threads prevents excessive RAM usage from ML models
# Timeout is set to 180s to allow complete video frame extraction and scanning without 502/504 errors
CMD exec gunicorn -w 1 --threads 2 -b 0.0.0.0:${PORT:-5003} --timeout 180 main:app

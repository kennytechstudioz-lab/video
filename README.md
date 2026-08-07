# NudNet Video & Image Moderation Service

This Python microservice uses **NudeNet** to process videos and images for nudity and explicit content moderation, replacing Amazon Rekognition.

## Setup & Running

1. **Create virtual environment & install dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Start the server**:
   ```bash
   python main.py
   ```
   The service will start on port `5001`.

## Endpoints

- `GET /health`: Health check endpoint.
- `POST /moderate-video`: Moderates a video by downloading and sampling frames with OpenCV and scanning with NudeNet.
  Payload:
  ```json
  {
    "url": "https://schooling-bucket1.s3.amazonaws.com/uploads/video.mp4",
    "key": "uploads/video.mp4"
  }
  ```
- `POST /moderate-image`: Moderates an image with NudeNet.
  Payload:
  ```json
  {
    "url": "https://schooling-bucket1.s3.amazonaws.com/uploads/image.jpg",
    "key": "uploads/image.jpg"
  }
  ```

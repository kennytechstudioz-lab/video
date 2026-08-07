import os
import tempfile
import urllib.request
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NudNetVideoService")

app = Flask(__name__)

# Configurable thresholds
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.40"))
MAX_FRAMES_TO_SAMPLE = int(os.getenv("MAX_FRAMES_TO_SAMPLE", "60"))

# Unsafe label keywords for NudeNet v3
UNSAFE_KEYWORDS = [
    "GENITALIA",
    "ANUS",
    "BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
]


def is_unsafe_label(label: str) -> bool:
    if not label:
        return False
    label_upper = label.upper()
    return any(keyword in label_upper for keyword in UNSAFE_KEYWORDS)


# Lazy loading detector
_detector = None


def get_detector():
    global _detector
    if _detector is None:
        try:
            from nudenet import NudeDetector
            logger.info("Initializing NudeNet NudeDetector...")
            _detector = NudeDetector()
            logger.info("NudeNet NudeDetector initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize NudeNet detector: {e}")
            _detector = False
    return _detector if _detector is not False else None


def download_file(url, target_path):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (NudNetModerationService)"}
    )
    with urllib.request.urlopen(req) as response, open(target_path, "wb") as out_file:
        out_file.write(response.read())


def process_image(image_path):
    detector = get_detector()
    if not detector:
        logger.warning("Detector unavailable, returning default safe=True")
        return {"is_safe": True, "score": 0.0, "violations": []}

    try:
        detections = detector.detect(image_path)
        violations = []
        max_score = 0.0

        for item in detections:
            # NudeNet v3 uses key "class", fallback to "label"
            label = item.get("class") or item.get("label") or ""
            score = item.get("score", 0.0)
            logger.info(f"Image Detection: class='{label}' score={score:.3f}")

            if is_unsafe_label(label) and score >= CONFIDENCE_THRESHOLD:
                violations.append({"label": label, "score": score, "box": item.get("box")})
                if score > max_score:
                    max_score = score

        is_safe = len(violations) == 0
        return {
            "is_safe": is_safe,
            "score": max_score,
            "violations": violations,
        }
    except Exception as e:
        logger.error(f"Error processing image {image_path}: {e}")
        return {"is_safe": True, "score": 0.0, "violations": [], "error": str(e)}


def process_video(video_path):
    detector = get_detector()
    if not detector:
        logger.warning("Detector unavailable, returning default safe=True")
        return {"is_safe": True, "score": 0.0, "violations": [], "frames_processed": 0}

    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video file: {video_path}")
        return {"is_safe": True, "score": 0.0, "violations": [], "frames_processed": 0}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

    if total_frames <= 0:
        total_frames = 300  # Fallback estimate

    step = max(1, total_frames // MAX_FRAMES_TO_SAMPLE)
    logger.info(f"Processing video: total_frames={total_frames}, fps={fps:.1f}, sampling_step={step}")

    frames_processed = 0
    violations = []
    max_score = 0.0

    temp_dir = tempfile.mkdtemp()

    try:
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                frame_filename = os.path.join(temp_dir, f"frame_{frame_idx}.jpg")
                cv2.imwrite(frame_filename, frame)

                detections = detector.detect(frame_filename)
                for item in detections:
                    # NudeNet v3 dictionary key is "class"
                    label = item.get("class") or item.get("label") or ""
                    score = item.get("score", 0.0)
                    timestamp = round(frame_idx / fps, 2)
                    logger.info(f"Frame {frame_idx} ({timestamp}s): class='{label}' score={score:.3f}")

                    if is_unsafe_label(label) and score >= CONFIDENCE_THRESHOLD:
                        violations.append({
                            "frame": frame_idx,
                            "timestamp_sec": timestamp,
                            "label": label,
                            "score": score
                        })
                        if score > max_score:
                            max_score = score

                if os.path.exists(frame_filename):
                    os.remove(frame_filename)
                frames_processed += 1

                if len(violations) >= 2 or max_score >= 0.70:
                    logger.warning(f"Early exit: unsafe content detected at frame {frame_idx} (timestamp={round(frame_idx/fps, 2)}s, class='{violations[-1]['label']}', score={violations[-1]['score']:.3f})")
                    break

            frame_idx += 1
            if frames_processed >= MAX_FRAMES_TO_SAMPLE:
                break

    except Exception as e:
        logger.error(f"Error during video frame processing: {e}")
    finally:
        cap.release()
        try:
            for f in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, f))
            os.rmdir(temp_dir)
        except Exception:
            pass

    is_safe = len(violations) == 0
    logger.info(f"Video processing finished: frames_processed={frames_processed}, violations_found={len(violations)}, is_safe={is_safe}, max_score={max_score:.3f}")
    return {
        "is_safe": is_safe,
        "score": max_score,
        "violations": violations,
        "frames_processed": frames_processed,
    }


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "NudNet Video & Image Moderation Service",
        "detector_loaded": get_detector() is not None
    })


@app.route("/moderate-image", methods=["POST"])
def moderate_image_route():
    data = request.get_json() or {}
    url = data.get("url")
    key = data.get("key", "")

    if not url:
        return jsonify({"error": "url is required"}), 400

    logger.info(f"Moderating image url={url} key={key}")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_file(url, tmp_path)
        res = process_image(tmp_path)
        return jsonify(res)
    except Exception as e:
        logger.error(f"Image moderation failed for url={url}: {e}")
        return jsonify({"is_safe": True, "error": str(e)}), 200
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.route("/moderate-video", methods=["POST"])
def moderate_video_route():
    data = request.get_json() or {}
    url = data.get("url")
    key = data.get("key", "")

    if not url:
        return jsonify({"error": "url is required"}), 400

    logger.info(f"Moderating video url={url} key={key}")

    ext = ".mp4"
    if url.lower().endswith(".mov"):
        ext = ".mov"
    elif url.lower().endswith(".avi"):
        ext = ".avi"

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_file(url, tmp_path)
        res = process_video(tmp_path)
        return jsonify(res)
    except Exception as e:
        logger.error(f"Video moderation failed for url={url}: {e}")
        return jsonify({"is_safe": True, "error": str(e)}), 200
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8002))
    logger.info(f"Starting NudNet Moderation Server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)

"""
MARK-XX — Screen & Webcam Capture
Returns raw bytes suitable for sending to Gemini vision.
"""

import io
import base64
from typing import Optional, Tuple
import numpy as np


def capture_screen(monitor_index: int = 1) -> Optional[bytes]:
    """
    Capture the primary screen using mss.
    Returns PNG bytes or None on error.
    """
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 1
            monitor = monitors[monitor_index]
            screenshot = sct.grab(monitor)
            # Convert to PNG bytes
            from PIL import Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=False)
            return buf.getvalue()
    except Exception as e:
        print(f"Screenshot error: {e}")
        return None


def capture_screen_base64(monitor_index: int = 1) -> Optional[str]:
    """Returns base64-encoded PNG string."""
    data = capture_screen(monitor_index)
    if data:
        return base64.b64encode(data).decode("utf-8")
    return None


def capture_webcam(camera_index: int = 0) -> Optional[bytes]:
    """
    Capture a single frame from the webcam using OpenCV.
    Returns JPEG bytes or None on error.
    """
    try:
        import cv2
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        # Encode as JPEG
        success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if success:
            return bytes(buf)
        return None
    except Exception as e:
        print(f"Webcam error: {e}")
        return None


def capture_webcam_base64(camera_index: int = 0) -> Optional[str]:
    """Returns base64-encoded JPEG string."""
    data = capture_webcam(camera_index)
    if data:
        return base64.b64encode(data).decode("utf-8")
    return None


def get_screen_thumbnail(monitor_index: int = 1, max_size: Tuple[int, int] = (1280, 720)) -> Optional[bytes]:
    """
    Capture a resized screenshot (saves tokens / bandwidth).
    """
    try:
        from PIL import Image
        raw = capture_screen(monitor_index)
        if not raw:
            return None
        img = Image.open(io.BytesIO(raw))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"Thumbnail error: {e}")
        return None


def list_cameras() -> list[int]:
    """Return indices of available cameras."""
    available = []
    try:
        import cv2
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
    except Exception:
        pass
    return available

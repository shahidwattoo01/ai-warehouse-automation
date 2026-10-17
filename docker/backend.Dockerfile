FROM python:3.11-slim

WORKDIR /app
# YOLO_OFFLINE: no usage analytics or online checks from Ultralytics (Phase 5 detector).
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/apps/backend \
    YOLO_OFFLINE=1

# OpenCV (installed with Ultralytics for the Phase 5 detector) needs these system libraries;
# the slim image does not have them, and `import cv2` would fail at the first detection.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch keeps the image small; GPU training happens on Colab/Kaggle/Azure.
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY simulation ./simulation
COPY ai ./ai
COPY configs ./configs
COPY apps/backend ./apps/backend

# Run without root privileges.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "apps/backend", "--host", "0.0.0.0", "--port", "8000"]

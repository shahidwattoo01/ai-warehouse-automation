FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/apps/backend

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

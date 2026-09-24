FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

COPY backend ./backend
COPY frontend ./frontend
COPY uploads ./uploads

WORKDIR /app/backend

CMD gunicorn --bind 0.0.0.0:$PORT app:app
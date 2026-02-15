FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 2 --timeout 120 main:app

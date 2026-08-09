FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app/src
ENV DATA_DIR=/data
ENV MONITOR_DIR=/photos

EXPOSE 5000

CMD ["python", "src/monitor.py"]

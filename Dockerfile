FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ollama_cloud_gateway.py .
RUN mkdir -p /app/config

CMD ["python", "ollama_cloud_gateway.py"]
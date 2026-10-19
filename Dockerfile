FROM python:3.12-alpine

RUN apk add --no-cache tzdata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

ENV PORT=8085 \
    PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config

EXPOSE 8085

# Web UI + scheduler. For a one-off resync without the UI:
#   docker exec rom-mapper python /app/server.py --resync
CMD ["python", "/app/server.py"]

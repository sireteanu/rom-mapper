FROM python:3.12-alpine

RUN apk add --no-cache bash coreutils sed grep tzdata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rom-mapper.sh /usr/local/bin/rom-mapper.sh
COPY app/ /app/
RUN chmod +x /usr/local/bin/rom-mapper.sh

ENV PORT=8085 \
    PYTHONUNBUFFERED=1 \
    INPUT_CSV=/config/Rom_Mapping.csv

EXPOSE 8085

# Web UI + scheduler. For a one-off sync without the UI:
#   docker exec rom-mapper rom-mapper.sh
CMD ["python", "/app/server.py"]

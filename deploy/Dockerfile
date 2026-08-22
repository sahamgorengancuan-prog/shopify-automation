# ARCHIVIST — apparel design pipeline (Gradio)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g libwebp7 libopenjp2-7 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY archivist ./archivist
COPY README.md ./

# Runs and the style lock live on a volume so a redeploy never loses a collection.
VOLUME ["/app/runs"]
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS http://localhost:7860/ >/dev/null || exit 1

CMD ["python", "-m", "archivist.app", "--host", "0.0.0.0", "--port", "7860"]

FROM python:3.12-slim AS base
ARG TESSERACT_LANGS="deu eng"
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr \
      $(for l in $TESSERACT_LANGS; do echo tesseract-ocr-$l; done) \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# docker build --target test . && docker run --rm <image>
FROM base AS test
RUN pip install --no-cache-dir ".[test]"
COPY tests ./tests
COPY examples ./examples
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/vtietz/paperless-ai-extract" \
      org.opencontainers.image.description="LLM metadata extraction for Paperless-ngx via its REST API" \
      org.opencontainers.image.licenses="MIT"
RUN pip install --no-cache-dir . \
 && useradd --system --uid 1000 --home-dir /data extractor \
 && mkdir -p /data /config && chown extractor /data
USER extractor
VOLUME ["/data"]
ENV PYTHONUNBUFFERED=1
ENV PAE_CONFIG=/config/config.yaml
ENTRYPOINT ["paperless-ai-extract"]
CMD ["serve"]
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s \
  CMD ["paperless-ai-extract", "health"]

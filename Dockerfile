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
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
RUN pip install --no-cache-dir . && useradd --system --uid 1000 --home-dir /data extractor
USER extractor
VOLUME ["/data"]
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["paperless-ai-extract", "--config", "/config/config.yaml"]
CMD ["serve"]
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s \
  CMD ["paperless-ai-extract", "--config", "/config/config.yaml", "health"]

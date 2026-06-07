FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

ARG EXTRAS=embeddings
RUN if echo ",${EXTRAS}," | grep -q ",embeddings,"; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    fi \
    && pip install --no-cache-dir ".[${EXTRAS}]"

ENV CONF_DOC_CONFIG_PATH=/config/config.yaml \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["conf-doc"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]

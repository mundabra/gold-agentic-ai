# NVIDIA NeMo Guardrails server with GOLD's rails configuration (config id "gold").
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "nemoguardrails[server]==0.24.1" && useradd --system --uid 10001 rails
COPY entrypoint.sh /entrypoint.sh
COPY gold /config/gold
USER 10001
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]

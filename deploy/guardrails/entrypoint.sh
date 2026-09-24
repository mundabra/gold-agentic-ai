#!/bin/sh
# Start the NeMo Guardrails server. GUARDRAILS_MODEL_BASE_URL (usually the same endpoint
# GOLD uses) replaces the model base_url in config.yml, so one setting serves both.
set -eu
mkdir -p /tmp/rails
cp -r "${GUARDRAILS_CONFIG_DIR:-/config}/." /tmp/rails/
if [ -n "${GUARDRAILS_MODEL_BASE_URL:-}" ]; then
  sed -i "s|base_url: .*|base_url: ${GUARDRAILS_MODEL_BASE_URL}|" /tmp/rails/gold/config.yml
fi
exec nemoguardrails server --config /tmp/rails --default-config-id gold --port 8000 --disable-chat-ui

#!/usr/bin/env bash
# Stage 3 serving benchmark: send GOLD's real SQL requests to the SQL model with NVIDIA AIPerf.
#
#   pipx install aiperf                        # or: pip install aiperf
#   scripts/aiperf.sh                          # concurrency 1,4,8; 24 requests per level; 3 s target
#   CONCURRENCY=1,8,32 REQUESTS=64 SLO_MS=2000 scripts/aiperf.sh
#
# Reads GOLD_LLM_BASE_URL, GOLD_LLM_API_KEY and GOLD_SQL_MODEL from the environment or .env,
# and the database from GOLD_DATABASE_URL (default: the Compose database on localhost:5432).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${GOLD_LLM_BASE_URL:?set GOLD_LLM_BASE_URL (an OpenAI-compatible endpoint, e.g. http://localhost:4000/v1)}"
MODEL="${GOLD_SQL_MODEL:-gold-sql}"
CONCURRENCY="${CONCURRENCY:-1,4,8}"
REQUESTS="${REQUESTS:-24}"
SLO_MS="${SLO_MS:-3000}"
GOLD="${GOLD:-gold}"
AIPERF="$(command -v aiperf || echo "$HOME/.local/bin/aiperf")"
[ -x "$AIPERF" ] || { echo "aiperf not found. Install it with: pipx install aiperf" >&2; exit 1; }

OUT="results/aiperf-${MODEL##*/}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
trap 'pkill -f "^aiperf " >/dev/null 2>&1 || true' EXIT   # leave no AIPerf workers behind on Ctrl+C

$GOLD aiperf-payloads --model "$MODEL" --out "$OUT/payloads.jsonl"

# AIPerf appends /v1/chat/completions itself, so pass the base URL without /v1.
# --record-processor-service-count 1 starts AIPerf's record processor before the dataset loads;
# without it, repeat runs can hang at "Processing Records: 0/N" when the dataset comes from cache.
"$AIPERF" profile \
  --model "$MODEL" \
  --url "${GOLD_LLM_BASE_URL%/v1}" \
  --endpoint-type chat --streaming \
  ${GOLD_LLM_API_KEY:+--api-key "$GOLD_LLM_API_KEY"} \
  --input-file "$OUT/payloads.jsonl" --custom-dataset-type raw-payload \
  --tokenizer builtin --use-server-token-count \
  --concurrency "$CONCURRENCY" --request-count "$REQUESTS" \
  --goodput "request_latency:$SLO_MS" \
  --request-timeout-seconds 120 \
  --record-processor-service-count 1 \
  --artifact-dir "$OUT" \
  --ui-type simple --log-level error

$GOLD aiperf-summary "$OUT" --slo-ms "$SLO_MS" | tee "$OUT/summary.md"
echo "Saved in $OUT"

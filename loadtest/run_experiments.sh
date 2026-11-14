#!/usr/bin/env bash
# Run one server configuration through the load test protocol:
#   30 s warm-up (discarded), then 2 min at 1, 8 and 32 users, each run twice,
#   while sampling peak GPU memory.
#
# Usage:  loadtest/run_experiments.sh <label> [host]
#   e.g.  loadtest/run_experiments.sh batching_on
#         loadtest/run_experiments.sh cloud_t4 https://api.example.com
#
# Change ONE server setting between labels and restart the API, e.g.:
#   batching_off : MAX_BATCH_SIZE=1
#   batching_on  : MAX_BATCH_SIZE=8 MAX_BATCH_WAIT_MS=10
#   cache_off    : CACHE_ENABLED=false
# Always run the server with RATE_LIMIT_FREE_PER_MIN=100000.
#
# Then: uv run python loadtest/summarize.py

set -euo pipefail

LABEL="${1:?usage: $0 <label> [host]}"
HOST="${2:-http://localhost:8000}"
DURATION="${DURATION:-2m}"
USER_COUNTS="${USER_COUNTS:-1 8 32}"
REPEATS="${REPEATS:-2}"
OUT="loadtest/results/${LABEL}"
LOCUST=(uv run --group loadtest locust -f loadtest/locustfile.py --headless --host "$HOST" --only-summary)

mkdir -p "$OUT"
echo "== ${LABEL}: warm-up (first CUDA calls are slow; not measured)"
"${LOCUST[@]}" -u 8 -r 8 -t 30s > /dev/null 2>&1 || true

for users in $USER_COUNTS; do
  for run in $(seq 1 "$REPEATS"); do
    name="u${users}_r${run}"
    echo "== ${LABEL}: ${users} users, run ${run}"

    # Sample GPU memory every 500 ms in the background (local GPU only).
    vram_log="$OUT/${name}_vram.txt"
    if command -v nvidia-smi > /dev/null; then
      nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -lms 500 > "$vram_log" &
      smi_pid=$!
    fi

    "${LOCUST[@]}" -u "$users" -r "$users" -t "$DURATION" --csv "$OUT/${name}" > /dev/null 2>&1 || true

    if [[ -n "${smi_pid:-}" ]]; then
      kill "$smi_pid" 2> /dev/null || true
      unset smi_pid
    fi
  done
done
echo "Results in $OUT"

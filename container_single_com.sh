#!/usr/bin/env bash
set -a
source env.base
set +a

for i in $(seq 1 31); do
  port=$((20000 + i * 2))

  container="openclaw-bot${i}-mebsclaw-com-${port}-openclaw-gateway-1"

  echo ">>> $container"
#   docker restart $container
  docker exec -i "$container" \
    openclaw onboard --non-interactive --accept-risk --openrouter-api-key "$OPENROUTER_KEY"

done
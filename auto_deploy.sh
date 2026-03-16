#!/usr/bin/env bash
set -e

# Kullanım:
# ./deploy_openclaw.sh BASE_DOMAIN OPENROUTER_KEY COUNT
#
# Örnek:
# ./deploy_openclaw.sh bot or-v1-xxxxx 50
#
# bot1.mebsclaw.com
# bot2.mebsclaw.com
# ...

BASE_NAME="bot"
OPENROUTER_KEY="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"
COUNT="${3:-50}"

if [[ -z "$BASE_NAME" || -z "$OPENROUTER_KEY" ]]; then
  echo "Usage: $0 BASE_NAME OPENROUTER_KEY [COUNT]"
  exit 1
fi

for i in $(seq 31 "$COUNT"); do
  DOMAIN="${BASE_NAME}${i}"

  echo "--------------------------------------"
  echo "Deploying instance $i -> $DOMAIN"
  echo "--------------------------------------"

  ./deploy_openclaw.sh \
    --domain "$DOMAIN" \
    --openrouter-api-key "$OPENROUTER_KEY"

done

echo "All deployments completed."
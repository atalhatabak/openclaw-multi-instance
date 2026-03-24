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

BASE_NAME="v"
set -a
source env.base
set +a

COUNT="${4:-10}"

if [[ -z "$BASE_NAME" || -z "$OPENROUTER_API_KEY" ]]; then
  echo "Usage: $0 BASE_NAME OPENROUTER_KEY [COUNT]"
  exit 1
fi

for i in $(seq 4 "$COUNT"); do
  DOMAIN="${BASE_NAME}${i}"

  echo "--------------------------------------"
  echo "Deploying instance $i -> $DOMAIN"
  echo "--------------------------------------"

  ./deploy_openclaw.sh \
    --domain "$DOMAIN" \
    --openrouter-api-key "$OPENROUTER_API_KEY"

done

echo "All deployments completed."
#!/usr/bin/env sh
set -eu

export HOME=/home/node
export OPENCLAW_HOME=/opt/openclaw-home-template

/usr/local/bin/openclaw config set gateway.mode local >/dev/null
/usr/local/bin/openclaw config set tools.profile coding >/dev/null
/usr/local/bin/openclaw models set openrouter/xiaomi/mimo-v2-pro >/dev/null
/usr/local/bin/openclaw models fallbacks add openrouter/stepfun/step-3.5-flash:free
/usr/local/bin/openclaw models fallbacks add openrouter/stepfun/step-3.5-flash:free
/usr/local/bin/openclaw models fallbacks add openrouter/qwen/qwen3.6-plus:free
/usr/local/bin/openclaw models set-image openrouter/xiaomi/mimo-v2-omni

/usr/local/bin/openclaw models fallbacks add openrouter/moonshotai/kimi-k2.5


/usr/local/bin/openclaw config set browser.enabled true >/dev/null
/usr/local/bin/openclaw config set tools.exec.security full >/dev/null
/usr/local/bin/openclaw config set tools.exec.ask off >/dev/null
/usr/local/bin/openclaw config set tools.web.search.provider duckduckgo
BROWSER_PATH="$(find /home/node/.cache/ms-playwright -path '*/chrome-linux64/chrome' | head -n 1)"
if [ -n "$BROWSER_PATH" ]; then
  /usr/local/bin/openclaw config set browser.executablePath "$BROWSER_PATH" >/dev/null
fi

/usr/local/bin/openclaw config set browser.headless true >/dev/null
/usr/local/bin/openclaw config set browser.noSandbox true >/dev/null
/usr/local/bin/openclaw config set browser.defaultProfile openclaw >/dev/null
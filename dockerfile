FROM ghcr.io/openclaw/openclaw:latest

LABEL org.opencontainers.image.source="https://github.com/atalhatabak/openclaw-multi-instance"
LABEL org.opencontainers.image.description="OpenClaw image with Chrome, ClawHub and some tools preinstalled"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    unzip \
    vim \
    fonts-liberation \
    libasound2 \
    libnss3 \
    libxss1 \
    xdg-utils \
    && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && npm install -g clawhub \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

USER node
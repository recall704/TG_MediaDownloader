# Build stage
FROM python:3.13-slim AS builder

ENV PLAYWRIGHT_BROWSERS_PATH="/ms-playwright"

WORKDIR /app
COPY . /app/

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

RUN uv sync
RUN uv run patchright install chromium

# Final stage
FROM python:3.13-slim

ENV TG_SESSION="tg_downloader"
ENV TG_MAX_PARALLEL=4
ENV TG_DL_TIMEOUT=5400
ENV PLAYWRIGHT_BROWSERS_PATH="/ms-playwright"

WORKDIR /app
RUN <<EOF
cat > /etc/apt/sources.list.d/debian.sources <<'EOT'
Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb
URIs: http://mirrors.tuna.tsinghua.edu.cn/debian-security
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
EOT
EOF

RUN apt update && apt install -y --no-install-recommends \
    curl \
    tzdata \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libxss1 \
    libgtk-3-0 \
    libu2f-udev \
    libvulkan1 \
    fonts-liberation && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

COPY --from=builder /root/.local/share/uv /root/.local/share/uv
COPY --from=builder /root/.local/bin/uv /root/.local/bin/uv
COPY --from=builder /app/pyproject.toml /app/uv.lock /app/
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /ms-playwright /ms-playwright

COPY . /app/
RUN chmod +x tg_downloader.py

ENV TZ="Asia/Shanghai"

CMD ["uv", "run", "python", "/app/tg_downloader.py"]

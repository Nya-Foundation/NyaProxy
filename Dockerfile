FROM python:3.13-alpine AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src

COPY pyproject.toml README.md LICENSE ./
COPY nya ./nya
RUN python -m pip install .


FROM python:3.13-alpine AS runtime

LABEL org.opencontainers.image.description="NyaProxy: a lightweight API gateway with credential rotation" \
      org.opencontainers.image.source="https://github.com/Nya-Foundation/nyaproxy" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN addgroup -S nya && \
    adduser -S -G nya -s /sbin/nologin -h /app nya && \
    mkdir -p /app && \
    chown nya:nya /app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
USER nya
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O - http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["nyaproxy"]
# Hot-reload stays on: restarting is how a configuration change is applied, so
# --no-reload silently strands every edit made through the config UI. Rate-limit
# windows and key cool-downs survive the restart (see nya/services/state.py).
CMD ["--config", "/app/config.yaml", "--host", "0.0.0.0"]

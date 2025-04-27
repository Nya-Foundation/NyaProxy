# Use Python 3.12 slim as the base image for smaller size and reduced attack surface
FROM python:3.12-slim AS builder

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies in a separate layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY . .

# Build the package
RUN pip install --no-cache-dir -e .

# Create a non-privileged system user and group for running the application
RUN groupadd --system nya && \
    useradd --system --no-log-init --gid nya --shell /usr/sbin/nologin --comment "Non-privileged app user" nya

# Create a runtime stage to minimize the final image size
FROM python:3.12-slim AS runtime

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy installed packages and the application from the builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /app /app
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group

# Create necessary directories with proper permissions
RUN mkdir -p /app/logs && \
    chown -R nya:nya /app

# Install curl for health check
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER nya

# Expose the proxy port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/info || exit 1

# Command to run the application
ENTRYPOINT ["python", "-m", "nya_proxy.server.app"]
CMD ["--config", "config.yaml"]
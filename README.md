# NyaProxy

[![PyPI version](https://img.shields.io/pypi/v/nyaproxy.svg)](https://pypi.org/project/nyaproxy/)
[![Python versions](https://img.shields.io/pypi/pyversions/nyaproxy.svg)](https://pypi.org/project/nyaproxy/)
[![License](https://img.shields.io/github/license/Nya-Foundation/nyaproxy.svg)](https://github.com/Nya-Foundation/nyaproxy/blob/main/LICENSE)
[![Code Coverage](https://codecov.io/gh/Nya-Foundation/nyaproxy/branch/main/graph/badge.svg)](https://codecov.io/gh/Nya-Foundation/nyaproxy)
[![CI/CD](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml/badge.svg)](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml)
[![Docker](https://img.shields.io/docker/pulls/Nya-Foundation/nyaproxy)](https://hub.docker.com/r/Nya-Foundation/nyaproxy)

A lightweight, flexible API proxy with dynamic token rotation, load balancing, and rate limiting capabilities.

## Table of Contents
- [Overview](#overview)
- [Key Features](#key-features)
- [Installation](#installation)
  - [Using PyPI](#from-pypi-recommended)
  - [From Source](#from-source)
  - [Using Docker](#using-docker)
  - [Using Docker Compose](#using-docker-compose)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Starting the Proxy](#starting-the-proxy)
  - [Making Requests](#making-requests)
  - [Routing Logic](#routing-logic)
  - [NekoConf Guide](#dashboard-guide)
  - [Dashboard Guide](#dashboard-guide)
- [Advanced Features](#advanced-features)
- [Docker Usage](#docker-usage)
  - [Environment Variables](#environment-variables)
  - [Volume Mounts](#volume-mounts)
  - [Custom Configuration](#custom-configuration)
  - [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Community and Support](#community-and-support)
- [Contributing](#contributing)
- [License](#license)

## Overview

NyaProxy is a Python-based low-level proxy server that simplifies working with multiple API services by:

- Transparently intercepting and forwarding HTTP requests to various API endpoints
- Automatically rotating API keys/tokens from a configurable pool
- Providing multiple load balancing strategies with smart key selection
- Implementing rate limiting at both endpoint and key levels
- Supporting request queuing for handling rate-limited requests
- Providing a metrics dashboard for monitoring performance

## Key Features

### Dynamic Token Rotation

Automatically rotate between multiple API keys or tokens to:
- Avoid rate limits by distributing requests across multiple credentials
- Improve reliability with automatic failover
- Maximize throughput for high-volume applications
- Track usage statistics per token for optimization

### Custom Headers with Dynamic Variable Substitution

NyaProxy supports dynamic variable substitution in headers, allowing you to inject values from your configuration into request headers:

```yaml
apis:
  example_api:
    // ...existing code...
    headers:
      Authorization: "Bearer ${{keys}}"
      User-Agent: "${{user_agents}}"
      X-Custom-Header: "static-value"
      X-App-Version: "${{version}}"
    variables:
      keys:
        - "api_key_1"
        - "api_key_2"
      user_agents:
        - "NyaProxy/1.0"
        - "CustomAgent/2.0"
      version: "v1.2.3"  # Single values are also supported
```

#### Features and Capabilities

- **Variable Rotation**: Variables with multiple values (like API keys or user agents) will rotate according to your load balancing strategy
- **Static Headers**: Headers without variables are passed through unchanged
- **Multiple Variables**: Use multiple dynamic variables in a single header value
- **Variable Formats**:
  - Array variables: `keys: ["key1", "key2"]` for rotation
  - Single value variables: `version: "1.0.0"` for static substitution
- **Conditional Variables**: Use with routing rules to change headers based on request patterns

#### Example Use Cases

1. **Authentication Rotation**:
   ```yaml
   headers:
     Authorization: "Bearer ${{keys}}"
   ```

2. **Browser Fingerprint Rotation**:
   ```yaml
   headers:
     User-Agent: "${{user_agents}}"
     Accept-Language: "${{languages}}"
     X-Forwarded-For: "${{ip_addresses}}"
   ```

3. **Custom API Parameters**:
   ```yaml
   headers:
     X-Api-Version: "${{versions}}"
     X-Organization: "org-${{org_ids}}"
   ```

4. **Mixed Static and Dynamic Values**:
   ```yaml
   headers:
     Authorization: "ApiKey ${{keys}}"
     X-Request-Source: "NyaProxy-${{version}}-${{environment}}"
   ```

### Smart Load Balancing

Multiple strategies for distributing requests:
- **Round Robin**: Rotates through keys sequentially (default)
- **Random**: Selects a random key for each request
- **Least Connections**: Uses the key with the fewest recent requests
- **Fastest Response**: Prioritizes keys with fastest historical response times
- **Weighted**: Distributes requests based on assigned weights to each key

### Robust Rate Limiting

Configure rate limits at both the endpoint and key levels:
```yaml
rate_limit:
  endpoint_rate_limit: "500/m"  # 500 requests per minute for the entire endpoint
  key_rate_limit: "100/m"       # 100 requests per minute per key
```

Supported time units: `/s` (seconds), `/m` (minutes), `/h` (hours), `/d` (days)

### Intelligent Request Queuing

When rate limits are hit, automatically queue requests:
- Prioritize based on queuing time
- Implement automatic retries when rate limits reset
- Configure queue size and request expiry
- Monitor queue status through the dashboard

### Real-time Metrics Dashboard

Monitor your API usage through a web-based dashboard:
- Track request volume, errors, and response times
- Monitor key usage and effectiveness
- View rate limit incidents and queued requests
- Clear queues and reset metrics from the UI
- Filter metrics by API and time range

### Configuration Management UI (via NekoConf)
- Form-based visual editor
- JSON/YAML editors with syntax highlighting
- Real-time updates via WebSockets
- Dark and light theme support


## Installation

### From PyPI (Recommended)

```bash
pip install nya-proxy
```

### From Source

1. Clone the repository
   ```bash
   git clone https://github.com/Nya-Foundation/nyaproxy.git
   cd nyaproxy
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install the package:
   ```bash
   pip install -e .
   ```

### Using Docker

NyaProxy is available as a Docker image, optimized for security and performance:

```bash
# Pull the official image
docker pull Nya-Foundation/nyaproxy:latest

# Run with a custom config
docker run -p 8080:8080 -v $(pwd)/config.yaml:/app/config.yaml Nya-Foundation/nyaproxy
```

### Using Docker Compose

For a more comprehensive setup with proper networking and volume management:

1. Create a docker-compose.yml file (or use the one provided in the repository)
2. Run NyaProxy with Docker Compose:

```bash
docker-compose up -d
```

## Configuration

NyaProxy uses NekoConf for configuration management. You'll need to create a `config.yaml` file or modify the provided example.

### Basic Configuration Structure

```yaml
# NyaProxy Configuration
nya_proxy:
  host: 0.0.0.0                      # Host for NyaProxy to bind to
  port: 8080                           # Port for NyaProxy to listen on
  api_key: ""                          # API key for authenticating requests (optional)
  logging:
    enabled: true                      # Enable logging
    level: INFO                       # Log level (DEBUG, INFO, WARNING, ERROR)
    log_file: nya_proxy.log            # Log file name
  proxy:
    enabled: false                     # Enable outbound proxy
    address: socks5://username:password@proxy.example.com:1080
  dashboard:
    enabled: true                      # Enable/disable the metrics dashboard
  queue:
    enabled: true                      # Enable request queuing when rate limits are hit
    max_size: 200                      # Maximum queue size per API
    expiry_seconds: 300                # How long to keep requests in queue before expiry

# Default settings for all endpoints
default_settings:
  key_variable: keys                   # Default variable name for API keys
  load_balancing_strategy: "round_robin"  # Default strategy
  rate_limit:
    endpoint_rate_limit: "10/s"        # Default global rate limit
    key_rate_limit: "10/m"             # Default per-key rate limit
  retry:
    enabled: true                      # Enable automatic retries
    attempts: 3                        # Max retry attempts
    retry_after_seconds: 10            # Delay between retries
    retry_status_codes: [429, 500, 502, 503, 504]  # HTTP status codes to retry
  timeouts:
    request_timeout_seconds: 30        # Request timeout
    

# API-specific configurations
apis:
  openai:                              # API name (used in routing)
    name: "OpenAI API"                 # Human-readable name
    endpoint: "https://api.openai.com" # Target API endpoint
    key_variable: "keys"               # Variable name for API keys in config
    headers:
      Authorization: "Bearer ${{keys}}"  # Header template with variable
    variables:
      keys:                            # Your API keys/tokens
        - "your_openai_key_1"
        - "your_openai_key_2"
    load_balancing_strategy: "least_requests"
    rate_limit:
      endpoint_rate_limit: "500/m"
      key_rate_limit: "250/m"
    
  gemini:
    name: "Google Gemini API"
    endpoint: "https://generativelanguage.googleapis.com/v1beta/openai"
    aliases: ["/gemini"]
    key_variable: "keys"
    headers:
      Authorization: "Bearer ${{keys}}"
    variables:
      keys:
        - "your_gemini_key_1"
        - "your_gemini_key_2"
        - "your_gemini_key_3"
    load_balancing_strategy: "round_robin"
    rate_limit:
      endpoint_rate_limit: "10/m"
      key_rate_limit: "10/m"
```

## Usage

### Starting the Proxy

Run NyaProxy using one of these methods:

```bash
# Using the entry point
nyaproxy

# Or using Python module
python -m nya_proxy.app

# Specify a custom config file
nyaproxy --config my_config.yaml

# Override the port
nyaproxy --port 9000

# Enable debug logging
nyaproxy --log-level debug
```

### Making Requests

Once the proxy is running, you can make requests to it as if it were the actual API, and NyaProxy will handle authentication and routing:

```bash
# Example: Request to OpenAI API
curl http://localhost:8080/api/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello!"}]}'
```

If you enable API key authentication for NyaProxy itself, include it in your requests:

```bash
curl http://localhost:8080/api/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello!"}]}'
```

### Routing Logic

NyaProxy routes requests based on the URL path:

1. If the path starts with a configured API name (e.g., `/openai`), it routes to that API
2. If the path starts with a configured aliases (e.g., `/r` for Reddit), it routes to the associated API
3. The routing prefix is removed before forwarding the request to the actual API


### NekoConf Guide

Access the Configuraiton Managment UI via with default username: nya, password: <api-key>

```
http://localhost:[port]/config
```


### Dashboard Guide

Access the dashboard to monitor usage, performance, and queue status:

```
http://localhost:[port]/dashboard
```

#### Dashboard Features

1. **Global Statistics**
   - Total requests processed
   - Success rate and error counts
   - Average response time
   - System uptime

2. **API Traffic Overview**
   - Filter metrics by specific API
   - Select time range for analysis
   - Search specific API endpoints
   - Reset metrics with one click

3. **API Details**
   - Per-API request counts and error rates
   - Average response times
   - Key utilization statistics
   - Current queue status

4. **Request History**
   - View recent API calls
   - See response times and status codes
   - Track which API keys were used
   - Identify failed requests

5. **Queue Management**
   - Monitor queued requests
   - Clear individual queues or all queues
   - View queue sizes and wait times

## Docker Usage

### Environment Variables

The Docker image supports the following environment variables:

- `CONFIG_PATH`: Path to the configuration file (default: `/app/config.yaml`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `HOST`: Host to bind to (default: `0.0.0.0`)
- `PORT`: Port to listen on (default: `8080`)

Example:
```bash
docker run -p 8080:8080 \
  -e LOG_LEVEL=DEBUG \
  -e PORT=9000 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  Nya-Foundation/nyaproxy
```

### Volume Mounts

Important volume mounts when running NyaProxy in Docker:

- `/app/config.yaml`: Mount your configuration file here
- `/app/logs`: Mount a volume for persistent logs

Example with persistent logs:
```bash
docker run -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v nyaproxy_logs:/app/logs \
  Nya-Foundation/nyaproxy
```

### Custom Configuration

For a more comprehensive setup with Docker Compose:

```yaml
version: '3.8'

services:
  nyaproxy:
    image: Nya-Foundation/nyaproxy:latest
    container_name: nyaproxy
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - nyaproxy_logs:/app/logs
    environment:
      - CONFIG_PATH=/app/config.yaml
      - LOG_LEVEL=INFO
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/info", "||", "exit", "1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s

volumes:
  nyaproxy_logs:
    driver: local
```

### Security Notes

The Docker image follows security best practices:

- Runs as a non-root user `nyaproxy`
- Uses a multi-stage build to minimize image size
- Includes only necessary dependencies
- Implements health checks to monitor application health
- Mounts configuration as read-only

## Advanced Features

### Dynamic Variable Substitution

NyaProxy supports dynamic variable substitution in headers:

```yaml
headers:
  Authorization: "Bearer ${{tokens}}"
  User-Agent: "${{agents}}"
variables:
  tokens:
    - "token1"
    - "token2"
  agents:
    - "Agent1"
    - "Agent2"
```

### Weighted Load Balancing

Assign different weights to keys to control request distribution:

```yaml
variables:
  keys:
    - "key1"
    - "key2"
  weights:
    - 3  # key1 gets 3x more requests than key2
    - 1
load_balancing_strategy: "weighted"
```

### Multi-Tier Proxying

NyaProxy can use another proxy for outbound connections:

```yaml
proxy:
  enabled: true
  address: socks5://username:password@proxy.example.com:1080
```

This allows for:
- Chain multiple proxies for additional anonymity
- Route traffic through different geographic locations
- Implement connection redundancy
- Apply additional security measures at each proxy level

### Custom Response Handling

Configure how NyaProxy handles specific response scenarios:

```yaml
retry:
  enabled: true
  attempts: 3                      # Maximum number of retry attempts
  retry_after_seconds: 10          # Initial delay in seconds between retries
  etry_status_codes: [429, 500, 502, 503, 504]  # HTTP status codes to trigger retries
```

## Troubleshooting

### Common Issues

1. **Rate Limit Errors**: If you're still seeing rate limit errors:
   - Check your key_rate_limit and endpoint_rate_limit settings
   - Ensure you have enough API keys configured
   - Verify queue settings are enabled and sized appropriately
   - Consider implementing backoff strategies in your retry configuration

2. **Connection Errors**:
   - Check network connectivity to the target APIs
   - Verify proxy configuration if using multi-tier proxying
   - Ensure your API keys are valid
   - Verify firewall rules allow outbound connections

3. **Dashboard Not Loading**:
   - Confirm dashboard.enabled is set to true
   - Check if the dashboard port (default 8082) is accessible
   - Look for errors in the NyaProxy logs
   - Verify browser console for JavaScript errors

4. **Docker-specific Issues**:
   - Check container logs: `docker logs nyaproxy`
   - Ensure proper volume mounts for configuration
   - Verify network connectivity from within the container
   - Check port mappings if the service isn't accessible
   - Make sure Docker has the necessary permissions

### Log Analysis

When troubleshooting, increase the log level for more detailed information:

```yaml
logging:
  enabled: true
  level: DEBUG  # Change from INFO to DEBUG
  log_file: nya_proxy.log
```

Or start NyaProxy with increased logging:

```bash
nyaproxy --log-level debug
```

### Health Checks

You can use the `/info` endpoint to verify if NyaProxy is running correctly:

```bash
curl http://localhost:8080/info
```

## Community and Support

### Getting Help

- **GitHub Issues**: Report bugs or request features on our [GitHub repository](https://github.com/Nya-Foundation/nyaproxy/issues)
- **Discussion Forum**: Join discussions on our [GitHub Discussions](https://github.com/Nya-Foundation/nyaproxy/discussions)
- **Discord**: Join our community [Discord server](https://discord.gg/XU5qRyVyhm) for real-time support

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request to `dev` branch

### Development Environment Setup

```bash
# Clone the repository
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

### Code Style

We use [Black](https://github.com/psf/black) for code formatting and [isort](https://pycqa.github.io/isort/) for import sorting:

```bash
# Format code
black .

# Sort imports
isort .
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Nya-Foundation/nyaproxy&type=Date)](https://star-history.com/#Nya-Foundation/nyaproxy&Date)
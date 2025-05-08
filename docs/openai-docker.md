# NyaProxy Deployment via Docker with OpenAI API Support

This guide helps you deploy NyaProxy using Docker with OpenAI API configuration.

## Table of Contents

- [Why Choose Docker?](#why-choose-docker)
- [Prerequisites](#prerequisites)
- [Deployment Options](#deployment-options)
  - [Option 1: Quick Start (Docker Run)](#option-1-quick-start-docker-run)
  - [Option 2: Docker Compose (Recommended)](#option-2-docker-compose-recommended)
- [Configuring OpenAI API](#configuring-openai-api)
- [Testing Your Deployment](#testing-your-deployment)
- [Troubleshooting](#troubleshooting)

## Why Choose Docker?

Docker provides these benefits for running NyaProxy:

- **Isolation**: Runs in its own container without affecting your system
- **Consistency**: Works the same across all operating systems
- **Easy Updates**: Simple to upgrade to newer versions
- **No Dependencies**: No need to install Python or other software

## Prerequisites

Before starting, you'll need:

1. **Docker installed** on your computer
   - [Docker Desktop for Windows/Mac](https://www.docker.com/products/docker-desktop/)
   - [Docker Engine for Linux](https://docs.docker.com/engine/install/)

2. **OpenAI API Key**
   - Get one from [OpenAI's platform](https://platform.openai.com/api-keys)
   - Or get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey) (OpenAI-compatible)

> [!NOTE]
> If you're completely new to Docker, don't worry! This guide includes simple copy-paste commands.

## Deployment Options

### Option 1: Quick Start (Docker Run)

This is the fastest way to get started:

1. Open a terminal or command prompt

2. Run this command to start NyaProxy:

```bash
docker run -d -p 8080:8080 k3scat/nya-proxy:latest
```

3. Open `http://localhost:8080` in your web browser

> [!TIP]
> The `-p 8080:8080` part maps the container's port to your computer. If port 8080 is already in use, you can change the first number (e.g., `-p 9000:8080` would make NyaProxy available at http://localhost:9000).


### Option 2: Docker Compose (Recommended)

Docker Compose gives you more control and makes future management easier:

1. Create a new folder on your computer for NyaProxy

2. Inside that folder, create a file named `docker-compose.yml` with this content:

```yaml
services:
  nya-proxy:
    image: k3scat/nya-proxy:latest
    container_name: nya-proxy
    restart: unless-stopped
    ports:
      - "8080:8080"
    networks:
      - nya-proxy-network

networks:
  nya-proxy-network:
    driver: bridge
```

3. In the same folder, open a terminal or command prompt and run:

```bash
docker-compose up -d
```

4. Open `http://localhost:8080` in your web browser

> [!NOTE]
> No need to supply any configuration files! NyaProxy will automatically create a basic configuration that works out of the box. You can customize it later through the web interface.

## Configuring OpenAI API

Now let's configure NyaProxy to work with your OpenAI API key:

### 1. Access the Configuration Interface

1. Go to `http://localhost:8080/config` in your web browser
   
2. The first time you access this page, you won't need a password as no master API key is configured yet. Simply click "Authenticate":

> [!NOTE]
> When no master API key is configured, NyaProxy doesn't show a login page. This is convenient for initial setup but not secure for production use.

### 2. Configure OpenAI API

1. In the configuration editor, you'll see the automatically generated config

2. Find or add your OpenAI configuration in the `apis` section:

```yaml
apis:
  openai:
    name: OpenAI API
    endpoint: https://generativelanguage.googleapis.com/v1beta/openai
    aliases:
      - /openai
    key_variable: api_keys
    headers:
      Authorization: 'Bearer ${{api_keys}}'
    variables:
      api_keys:
        - sk-your-openai-key-1
        - sk-your-openai-key-2  # Optional: add more keys if you have them
    load_balancing_strategy: round_robin
    rate_limit:
      endpoint_rate_limit: 500/m
      key_rate_limit: 250/m
```

3. Replace `sk-your-openai-key-1` with your actual OpenAI API key

> [!TIP]
> You can use Gemini AI Studio to get a free API key that works with OpenAI-compatible interfaces. [Get a Gemini API key here](https://aistudio.google.com/app/apikey). Just make sure to use the Gemini endpoint if you're using a Gemini key.

4. Under the `server` section, add a secure API key to protect your instance:

```yaml
server:
  # ...existing settings...
  api_key:
    - your-secure-master-key  # Choose a strong password
```

5. Click "Save Configuration"


> [!IMPORTANT]
> After adding an API key, you'll need to use it the next time you access the dashboard or config UI.

## Testing Your Deployment

Let's verify everything is working correctly:

### 1. Check the Dashboard

1. Visit `http://localhost:8080/dashboard` in your web browser
   
2. Enter your master API key when prompted

3. You should see the NyaProxy dashboard with metrics


### 2. Test an API Request

Make a test request to OpenAI through your proxy:

1. Using curl (from terminal/command prompt):

```bash
curl http://localhost:8080/api/openai/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secure-master-key" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Say hello!"}]
  }'
```

2. Or using Python:

```python
import requests

response = requests.post(
    "http://localhost:8080/api/openai/chat/completions",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer your-secure-master-key"
    },
    json={
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Say hello!"}]
    }
)

print(response.json())
```

3. You should receive a response from OpenAI, and see the request in your dashboard

## Troubleshooting

### Common Issues

1. **Port Already In Use**
   - Error: `port is already allocated`
   - Solution: Change the port mapping in your docker run or docker-compose.yml file

2. **Container Stops Immediately**
   - Check logs: `docker logs nya-proxy`
   - Look for configuration errors or crashes

3. **Can't Access Dashboard or Config UI**
   - Make sure your browser can connect to localhost:8080
   - Check that the container is running: `docker ps`

4. **OpenAI API Errors**
   - Verify your OpenAI API key is valid and active
   - Check if you've reached your OpenAI rate limits

> [!CAUTION]
> Always stop your container when not in use to prevent unauthorized access:
> `docker-compose down` or `docker stop nya-proxy`

---

Congratulations! You now have NyaProxy running in a Docker container, serving as a proxy for OpenAI's API with load balancing and rate limiting capabilities.
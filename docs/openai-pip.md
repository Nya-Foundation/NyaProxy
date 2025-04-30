# NyaProxy Deployment via PIP with OpenAI API Support

This guide helps you deploy NyaProxy using Python's PIP package manager with OpenAI API configuration.

## Table of Contents

- [Why Choose PIP Installation?](#why-choose-pip-installation)
- [Prerequisites](#prerequisites)
- [Installation Steps](#installation-steps)
- [Configuring OpenAI API](#configuring-openai-api)
- [Running NyaProxy](#running-nyaproxy)
- [Testing Your Deployment](#testing-your-deployment)
- [Troubleshooting](#troubleshooting)

## Why Choose PIP Installation?

Installing NyaProxy directly with PIP offers these advantages:

- **Direct Integration**: Runs natively on your operating system
- **Customizability**: Easier access to all configurations and features
- **Development**: Good option if you plan to modify or contribute to NyaProxy
- **Simplicity**: No containerization or cloud accounts needed

## Prerequisites

Before starting, you'll need:

1. **Python Installed** (version 3.8 or higher)
   - [Download Python](https://www.python.org/downloads/)
   - During installation, check "Add Python to PATH" (Windows)

2. **OpenAI API Key**
   - Get one from [OpenAI's platform](https://platform.openai.com/api-keys)
   - Or get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey) (OpenAI-compatible)

> [!NOTE]
> If you're not sure which Python version you have, open a terminal or command prompt and run `python --version` or `python3 --version`.

## Installation Steps

### 1. Install NyaProxy Package

1. Open a terminal (Linux/Mac) or command prompt (Windows)

2. Install NyaProxy using pip:

```bash
# On most systems:
pip install nya-proxy

# If that doesn't work, try:
pip3 install nya-proxy

# Or for a user-only installation:
pip install --user nya-proxy
```

3. Verify the installation:

```bash
nyaproxy --version
```

You should see the version number of NyaProxy displayed.

## Running NyaProxy

Now let's start NyaProxy:

1. In your terminal or command prompt, simply run:

```bash
nyaproxy
```

2. That's it! NyaProxy will automatically create a basic configuration file and start up.

3. You should see output indicating that NyaProxy has started successfully

> [!NOTE]
> NyaProxy automatically creates a working configuration file when it starts up for the first time. No need to create one yourself!

## Configuring OpenAI API

Now let's configure NyaProxy to work with your OpenAI API key:

### 1. Access the Configuration Interface

1. Open your web browser and go to `http://localhost:8080/config`

2. The first time you access this page, you won't need a password as no master API key is configured yet. Simply click "Authenticate":

> [!NOTE]
> When no master API key is configured, NyaProxy doesn't show a login page. This is convenient for initial setup but not secure for production use.

### 2. Add Your OpenAI API Key

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
> You can use Gemini AI Studio to get a free API key that works with OpenAI-compatible interfaces. [Get a Gemini API key here](https://aistudio.google.com/app/apikey). Just make sure to use the Gemini endpoint instead of OpenAI's if you're using a Gemini key.

4. Under the `nya_proxy` section, add a secure API key to protect your instance:

```yaml
nya_proxy:
  # ...existing settings...
  api_key:
    - your-secure-master-key  # Choose a strong password
```

5. Click "Save Configuration"


> [!IMPORTANT]
> After adding an API key, you'll need to use it the next time you access the dashboard or config UI.

## Testing Your Deployment

Let's verify everything is working correctly:

### 1. Access the Dashboard

1. In your browser, go to `http://localhost:8080/dashboard`

2. Enter your API key if prompted

3. You should see the NyaProxy dashboard with metrics

### 2. Test an API Request

Make a test request to OpenAI through your proxy:

1. Using curl (if you have it installed):

```bash
curl http://localhost:8080/api/openai/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secure-master-key" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Say hello!"}]
  }'
```

2. Or using Python in a new terminal:

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

3. You should receive a response from OpenAI, and see the request appear in your dashboard


## Troubleshooting

### Common Issues

1. **"Command not found" Error**
   - Make sure Python is in your PATH
   - Try using `python -m nya_proxy.server.app` instead

2. **Can't Access Dashboard/Config UI**
   - Make sure NyaProxy is running (check terminal output)
   - Try a different browser or clear your browser cache
   - Check if port 8080 is already in use by another program

3. **OpenAI API Errors**
   - Verify your OpenAI API key is correct and active
   - Check if you've reached your OpenAI rate limits

> [!TIP]
> If you close the terminal window, NyaProxy will stop. To keep it running in the background, see the "Advanced Configuration" section in the full documentation.

---

Congratulations! You now have a working NyaProxy installation that can proxy requests to OpenAI's API with load balancing and rate limiting capabilities.
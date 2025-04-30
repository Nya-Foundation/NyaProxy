# 🐾 NyaProxy - Universal API Proxy

[![PyPI version](https://img.shields.io/pypi/v/nya-proxy.svg)](https://pypi.org/project/nya-proxy/)
[![Python versions](https://img.shields.io/pypi/pyversions/nya-proxy.svg)](https://pypi.org/project/nya-proxy/)
[![License](https://img.shields.io/github/license/Nya-Foundation/nyaproxy.svg)](https://github.com/Nya-Foundation/nyaproxy/blob/main/LICENSE)
[![Code Coverage](https://codecov.io/gh/Nya-Foundation/nyaproxy/branch/main/graph/badge.svg)](https://codecov.io/gh/Nya-Foundation/nyaproxy)
[![CodeQL & Dependencies Scan](https://github.com/nya-foundation/nyaproxy/actions/workflows/scan.yml/badge.svg)](https://github.com/nya-foundation/nyaproxy/actions/workflows/scan.yml)
[![CI/CD Builds](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml/badge.svg)](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml)
[![Docker](https://img.shields.io/docker/pulls/k3scat/nya-proxy)](https://hub.docker.com/r/k3scat/nya-proxy)

<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/images/banner.png" alt="NyaProxy Banner"/>

## 🌈 Introduction

*Your purr-fect Swiss Army Knife for API Proxy Management~*

NyaProxy is a versatile API proxy that goes beyond just OpenAI APIs! Whether you're working with AI models (OpenAI, Gemini, Anthropic), image generation services, or any other REST API that needs robust key management - NyaProxy has your back.

The possibilities are limited only by your imagination! Use NyaProxy to:
- Balance loads across multiple API keys
- Create resilient API systems with automatic failover
- Build cost-effective solutions by optimizing key usage
- Secure your API keys behind a proxy layer
- Monitor and analyze your API usage in real-time

## 🌟 Core Capabilities
| Feature               | Description                                                                 | Config Reference          |
|-----------------------|-----------------------------------------------------------------------------|---------------------------|
| 🔄 Token Rotation     | Automatic key cycling across multiple providers                             | `variables.keys`          |
| ⚖️ Load Balancing    | 5 strategies: Round Robin, Random, Least Request, Fastest Response, Weighted | `load_balancing_strategy` |
| 🚦 Rate Limiting     | Granular controls per endpoint/key with smart queuing                       | `rate_limit`              |
| 🕵️ Request Masking   | Dynamic header substitution across multiple identity providers              | `headers` + `variables`   |
| 📊 Real-time Metrics | Interactive dashboard with request analytics and system health              | `dashboard`               |
| 🔧 Body Substitution | Dynamic JSON payload transformation using JSONPath                          | `request_body_substitution` |
| 🔄 Simulated Streaming | Stream chunked responses for better UX                                    | `simulated_streaming`     |


## 📥 Quick Start

### One-Click Deployment (No Fuss, No Muss!)

Pick your favorite platform and let's go!

<table>
  <tr>
    <td align="center">
      <a href="https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FNya-Foundation%2Fnyaproxy">
        <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render">
        <br>Deploy to Render
      </a>
    </td>
    <td align="center">
      <a href="https://railway.com/template/TqUoxN?referralCode=9cfC7m">
        <img src="https://railway.com/button.svg" alt="Deploy on Railway">
        <br>Deploy to Railway
      </a>
    </td>
  </tr>
</table>

### Local Deployment (For the DIY Enthusiasts!)

#### Prerequisites
- Python 3.8 or higher
- Docker (optional, for containerized deployment)

#### Installation

##### 1. Install from PyPI (the easiest way!)
```bash
pip install nya-proxy
```

##### 2. Run NyaProxy

This creates a basic configuration file in your current folder:

```bash
nyaproxy
```

...or provide your own config file:

```bash
nyaproxy --config config.yaml
```

##### 3. Verify Your Setup

Visit `http://localhost:8080/config` to access the configuration UI.  
**Note:** Please secure your master API key for safety!

Check out `http://localhost:8080/dashboard` for the snazzy management dashboard with all your API traffic visualizations.

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy

# Install dependencies
pip install -e .

# Run NyaProxy
nyaproxy
```

#### Docker
```bash
docker run -d \
  -p 8080:8080 \
  # -v ${PWD}/config.yaml:/app/config.yaml \
  # -v nya-proxy-logs:/app/logs \
  k3scat/nya-proxy:latest
```

## Configuration

Configuration reference can be found under [Configs folder](configs/) folder

```yaml
# Basic config.yaml example for Gemini API
nya_proxy:
  host: 0.0.0.0
  port: 8080
  api_key: 
  logging:
    enabled: true
    level: info
    log_file: app.log
  proxy:
    enabled: false
    address: socks5://username:password@proxy.example.com:1080
  dashboard:
    enabled: true
  queue:
    enabled: true
    max_size: 200
    expiry_seconds: 300

# Default settings for the all apis if not specified
default_settings:
  key_variable: keys
  load_balancing_strategy: round_robin
  rate_limit:
    endpoint_rate_limit: 10/s
    key_rate_limit: 10/m
    rate_limit_paths: 
      - "*"
  retry:
    enabled: true
    mode: key_rotation
    attempts: 3
    retry_after_seconds: 1
    retry_request_methods: [ POST, GET, PUT, DELETE, PATCH, OPTIONS ]
    retry_status_codes: [ 429, 500, 502, 503, 504 ]
  timeouts:
    request_timeout_seconds: 300
  # Simulated streaming settings
  simulated_streaming:
    enabled: false
    delay_seconds: 0.2 # Delay between chunks in seconds
    init_delay_seconds: 0.5 # Initial delay before starting streaming in seconds
    chunk_size_bytes: 256 # Size of each chunk in bytes
    apply_to: ["application/json", "application/xml", "text/plain", "image/png", "image/jpeg"] # Response content types to apply simulated streaming to
  
# API configurations, each API can have its own settings, but will inherit from default_settings if not specified
apis:
  gemini: 
    name: Google Gemini API
    endpoint: https://generativelanguage.googleapis.com/v1beta/openai
    aliases:
    - /gemini
    key_variable: keys
    headers:
      Authorization: 'Bearer ${{keys}}'
    variables:
      keys:
      - your_gemini_key_1
      - your_gemini_key_2
      - your_gemini_key_3
    load_balancing_strategy: least_requests
    rate_limit:
      # For Gemini, the rate limits (gemini-2.5-pro-exp-03-25) for each key are 5 RPM and 25 RPD
      # Ideally, the endpoint rate limit should be n x Per-Key-RPD, where n is the number of keys
      endpoint_rate_limit: 75/d
      key_rate_limit: 5/m
      # Rate limit paths are optional, but you can configure which paths to apply the rate limits to (regex supported), default is all paths "*"
      rate_limit_paths:
        - "/chat/*"
        - "/images/*"

    # [Advanced] Request body substitution settings, do not enable unless you know what you are doing
    request_body_substitution: 
      enabled: true 
      # Substitution rules for request body with JMEPath
      rules: # JMEPath rules for request body substitution
        - name: "Remove frequency_penalty" # if frequency_penalty is present, remove it from the request body since Gemini does not support it
          operation: remove
          path: "frequency_penalty"
          conditions:
            - field: "frequency_penalty"
              operator: "exists"
        - name: "Remove presence_penalty" # if presence_penalty is present, remove it from the request body since Gemini does not support it
          operation: remove
          path: "presence_penalty"
          conditions:
            - field: "presence_penalty"
              operator: "exists"

  # feel free to add more APIs here, just follow the same structure as above
```

## 📡 Service Endpoints

| Service    | Endpoint                          | Description                        |
|------------|-----------------------------------|------------------------------------|
| API Proxy  | `http://localhost:8080/api/<endpoint_name>` | Main proxy endpoint for API requests |
| Dashboard  | `http://localhost:8080/dashboard` | Real-time metrics and monitoring   |
| Config UI  | `http://localhost:8080/config`    | Visual configuration interface     |

**Note**: Replace `8080` with your configured port if different

## 🔧 API Configuration

### OpenAI-Compatible APIs (Gemini, Anthropic, etc)
```yaml
gemini:
  name: Google Gemini API
  endpoint: https://generativelanguage.googleapis.com/v1beta/openai
  aliases:
    - /gemini
  key_variable: keys
  headers:
    Authorization: 'Bearer ${{keys}}'
  variables:
    keys:
      - your_gemini_key_1
      - your_gemini_key_2
  load_balancing_strategy: least_requests
  rate_limit:
    endpoint_rate_limit: 75/d     # Total endpoint limit
    key_rate_limit: 5/m          # Per-key limit
    rate_limit_paths:
      - "/chat/*"            # Apply limits to specific paths
      - "/images/*"
```

### Generic REST APIs
```yaml
novelai:
  name: NovelAI API
  endpoint: https://image.novelai.net
  aliases:
    - /novelai
  key_variable: tokens
  headers:
    Authorization: 'Bearer ${{tokens}}'
  variables:
    tokens:
      - your_novelai_token_1
      - your_novelai_token_2
  load_balancing_strategy: round_robin
  rate_limit:
    endpoint_rate_limit: 10/s
    key_rate_limit: 2/s
```

## 🖥️ Management Interfaces

### Real-time Metrics Dashboard
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/images/dashboard_ui.png" width="800" alt="Dashboard UI"/>

Monitor at `http://localhost:8080/dashboard`:
- Request volumes and response times
- Rate limit status and queue depth
- Key usage and performance metrics
- Error rates and status codes

### Visual Configuration Interface
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/images/config_ui.png" width="800" alt="Configuration UI"/>

Manage at `http://localhost:8080/config`:
- Live configuration editing
- Syntax validation
- Variable management
- Rate limit adjustments
- Auto reload on save

## Advanced Features

### Request Body Substitution
Dynamically transform JSON payloads using JMESPath expressions to add, replace, or remove fields:

```yaml
request_body_substitution:
  enabled: true
  rules:
    - name: "Default to GPT-4"
      operation: set
      path: "model"
      value: "gpt-4"
      conditions:
        - field: "model"
          operator: "exists"

```

For detailed configuration options and examples, see the [Request Body Substitution Guide](docs/request_body_substitution.md).


## 🛡️ Reference Architecture
```mermaid
graph TD
    A[Client] --> B[Nginx]
    B --> C[NyaProxyAuth]
    C --> D[NyaProxyApp]
    D --> E[API Providers]
    F[Monitoring] --> D
```

## 🌌 Future Roadmap

```mermaid
graph LR
A[Q1 2025] --> B[📡 Documentation Enhancement ]
A --> C[🔄 Border Test Coverage ]
B --> D[📈 API Key Usage/Balance Tracking]
C --> E[📊 UI/UX Enhancement ]
F[Q2 2025] --> G[🧩 Plugin System]
F --> H[🔍 Custom Metrics API]
```

## ❤️ Community

[![Discord](https://img.shields.io/discord/1365929019714834493)](https://discord.gg/jXAxVPSs7K)

*Need enterprise support? Contact [k3scat@gmail.com](mailto:k3scat@gmail.com)*

## 📈 Project Growth

[![Star History Chart](https://api.star-history.com/svg?repos=Nya-Foundation/NyaProxy&type=Date)](https://star-history.com/#Nya-Foundation/NyaProxy&Date)

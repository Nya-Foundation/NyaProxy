# 🐾 NyaProxy - Universal API Proxy

[![PyPI version](https://img.shields.io/pypi/v/nya-proxy.svg)](https://pypi.org/project/nya-proxy/)
[![Python versions](https://img.shields.io/pypi/pyversions/nya-proxy.svg)](https://pypi.org/project/nya-proxy/)
[![License](https://img.shields.io/github/license/Nya-Foundation/nyaproxy.svg)](https://github.com/Nya-Foundation/nyaproxy/blob/main/LICENSE)
[![Code Coverage](https://codecov.io/gh/Nya-Foundation/nyaproxy/branch/main/graph/badge.svg)](https://codecov.io/gh/Nya-Foundation/nyaproxy)
[![CI/CD](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml/badge.svg)](https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml)
[![Docker](https://img.shields.io/docker/pulls/k3scat/nya-proxy)](https://hub.docker.com/r/k3scat/nya-proxy)

<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/images/banner.png" alt="NyaProxy Banner"/>

*Your Swiss Army Knife for API Proxy Management*

## 🌟 Core Capabilities
| Feature               | Description                                                                 | Config Reference          |
|-----------------------|-----------------------------------------------------------------------------|---------------------------|
| 🔄 Token Rotation     | Automatic key cycling across multiple providers                             | `variables.keys`          |
| ⚖️ Load Balancing    | 5 strategies: Round Robin, Random, Least Connections, Fastest Response, Weighted | `load_balancing_strategy` |
| 🚦 Rate Limiting     | Granular controls per endpoint/key with smart queuing                       | `rate_limit`              |
| 🕵️ Request Masking   | Dynamic header substitution across multiple identity providers              | `headers` + `variables`   |
| 📊 Real-time Metrics | Interactive dashboard with request analytics and system health              | `dashboard.enabled`       |

## 📥 Installation

### Prerequisites
- Python 3.8 or higher
- Docker (optional, for containerized deployment)

### Quick Start

#### 1. Install from PyPI
```bash
pip install nya-proxy
```

#### 2. Create a simple configuration file
Create a `config.yaml` file with your API settings:
```yaml
# Basic config.yaml example
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
    

apis:
  gemini:
    # Any OpenAI-Compatible API
    name: Google Gemini API
    # Gemini: https://generativelanguage.googleapis.com/v1beta/openai
    # OpenAI: https://api.openai.com/v1
    # Anthropic: https://api.anthropic.com/v1
    # DeepSeek: https://api.deepseek.com/v1
    # Mistral: https://api.mistral.ai/v1
    # OpenRouter: https://api.openrouter.ai/v1
    # Ollama: http://localhost:11434/v1
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
        - "/v1/chat/*"
        - "/v1/images/*"
```

#### 3. Run NyaProxy
```bash
nyaproxy --config config.yaml
```

#### 4. Verify the installation
Visit `http://localhost:8080/dashboard` to access the management dashboard.

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy

# Install dependencies
pip install -e .

# Run NyaProxy
nyaproxy --config config.yaml
```

### Docker (Production)
```bash
docker run -d \
  -p 8080:8080 \
  -v ${PWD}/config.yaml:/app/config.yaml \
  -v nya-proxy-logs:/app/logs \
  k3scat/nya-proxy:latest
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
      - "/v1/chat/*"            # Apply limits to specific paths
      - "/v1/images/*"
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

## 🛡️ Advanced Reference Architecture (Advanced Deployment)
```mermaid
graph TD
    A[Client] --> B[Nginx]
    B --> C[NyaProxy]
    C --> D[Auth Service]
    D --> E[API Providers]
    F[Monitoring] --> D
```

## 🌌 Future Roadmap

```mermaid
graph LR
A[Q3 2025] --> B[🔄 Smart Request Routing]
A --> C[📡 gRPC/WebSocket Support]
B --> D[📈 Auto-scaling Rules]
C --> E[📊 Protocol Analytics]
F[Q4 2025] --> G[🧩 Plugin System]
F --> H[🔍 Custom Metrics API]
```

## ❤️ Community

[![Discord](https://img.shields.io/discord/1365929019714834493)](https://discord.gg/jXAxVPSs7K)

*Need enterprise support? Contact [k3scat@gmail.com](mailto:k3scat@gmail.com)*

## 📈 Project Growth

[![Star History Chart](https://api.star-history.com/svg?repos=Nya-Foundation/NyaProxy&type=Date)](https://star-history.com/#Nya-Foundation/NyaProxy&Date)

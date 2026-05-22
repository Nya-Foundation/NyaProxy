# NyaProxy

**A lightweight, header-based API proxy for managing authenticated upstream services.**

[English](README.md) | [简体中文](README_zh.md) | [日本語](README_ja.md)

<div align="center">
  <img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/banner.png" alt="NyaProxy Banner" width="800" />

  <p>Centralize credential injection, quota-aware routing, rate limiting, retries, and observability for any HTTP API that uses keys or tokens.</p>

  <div>
    <a href="https://github.com/Nya-Foundation/nyaproxy/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Nya-Foundation/nyaproxy.svg" alt="License"/></a>
    <a href="https://pypi.org/project/nya-proxy/"><img src="https://img.shields.io/pypi/v/nya-proxy.svg" alt="PyPI version"/></a>
    <a href="https://pypi.org/project/nya-proxy/"><img src="https://img.shields.io/pypi/pyversions/nya-proxy.svg" alt="Python versions"/></a>
    <a href="https://pepy.tech/projects/nya-proxy"><img src="https://static.pepy.tech/badge/nya-proxy" alt="PyPI Downloads"/></a>
    <a href="https://hub.docker.com/r/k3scat/nya-proxy"><img src="https://img.shields.io/docker/pulls/k3scat/nya-proxy" alt="Docker Pulls"/></a>
    <a href="https://deepwiki.com/Nya-Foundation/NyaProxy"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"/></a>
  </div>

  <div>
    <a href="https://codecov.io/gh/Nya-Foundation/nyaproxy"><img src="https://codecov.io/gh/Nya-Foundation/nyaproxy/branch/main/graph/badge.svg" alt="Code Coverage"/></a>
    <a href="https://github.com/nya-foundation/nyaproxy/actions/workflows/scan.yml"><img src="https://github.com/nya-foundation/nyaproxy/actions/workflows/scan.yml/badge.svg" alt="CodeQL & Dependencies Scan"/></a>
    <a href="https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml"><img src="https://github.com/Nya-Foundation/nyaproxy/actions/workflows/publish.yml/badge.svg" alt="CI/CD Builds"/></a>
  </div>
</div>

## Overview

NyaProxy is a small API gateway for services that authenticate with API keys, bearer tokens, or custom request headers. Applications call NyaProxy with an internal proxy key, and NyaProxy forwards the request to the configured upstream service with the correct upstream credentials and policy controls.

It is useful when a team needs one place to manage access to external or internal APIs such as AI providers, image generation APIs, SaaS APIs, data vendor APIs, or private services.

Use NyaProxy only with credentials and traffic patterns that are allowed by the upstream service terms.

## Features

| Feature | Description | Config |
| --- | --- | --- |
| Credential injection | Add upstream credentials through headers without exposing them to clients | `headers`, `variables` |
| Credential pooling | Route traffic across multiple upstream keys or tokens | `variables.<name>` |
| Load balancing | Round robin, random, least requests, fastest response, and weighted selection | `load_balancing_strategy` |
| Rate limiting | Endpoint, upstream key, client IP, and proxy user limits | `rate_limit` |
| Queueing | Hold requests until configured quota becomes available | `queue` |
| Retry and failover | Retry selected status codes and temporarily cool down exhausted keys | `retry` |
| Request policy | Allow or block paths and methods before forwarding | `allowed_paths`, `allowed_methods` |
| Body transformation | Set or remove JSON fields with conditional JMESPath rules | `request_body_substitution` |
| Observability | Dashboard metrics, request history, queue status, and key usage | `dashboard` |
| Outbound proxy | Send upstream traffic through an optional HTTP/SOCKS proxy | `server.proxy` |

## Common Use Cases

- Central access gateway for third-party APIs used by multiple applications.
- Secure credential injection for browser, mobile, or internal clients that should not hold upstream secrets.
- Quota-aware routing for providers with per-key, per-minute, or per-day limits.
- Failover for services where a key or region may intermittently return `429` or `5xx`.
- Request normalization across API providers with slightly different JSON payload requirements.
- Usage monitoring for teams sharing paid API credentials.

## Quick Start

### Install From PyPI

```bash
pip install nya-proxy
nyaproxy
```

NyaProxy starts on `http://localhost:8080` by default.

Open:

- `http://localhost:8080/config` for the configuration UI
- `http://localhost:8080/dashboard` for metrics and queue status
- `http://localhost:8080/info` for configured API information

### Run With a Config File

```bash
nyaproxy --config config.yaml
```

### Install From Source

```bash
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy
pip install -e .
nyaproxy
```

### Docker

```bash
docker run -d \
  -p 8080:8080 \
  -v ${PWD}/config.yaml:/app/config.yaml \
  -v ${PWD}/app.log:/app/app.log \
  k3scat/nya-proxy:latest
```

## Configuration

NyaProxy is configured with YAML. Examples are available in [configs](configs/).

```yaml
server:
  api_key:
    - your_admin_proxy_key
    - your_application_proxy_key
  logging:
    enabled: true
    level: info
    log_file: app.log
  dashboard:
    enabled: true
  cors:
    allow_origins: ["*"]
    allow_credentials: true
    allow_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    allow_headers: ["*"]

default_settings:
  key_variable: keys
  key_concurrency: true
  load_balancing_strategy: round_robin
  allowed_paths:
    enabled: false
    mode: whitelist
    paths:
      - "*"
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
  queue:
    max_size: 200
    max_workers: 10
    expiry_seconds: 300
  rate_limit:
    enabled: true
    endpoint_rate_limit: 1000/h
    key_rate_limit: 60/m
    ip_rate_limit: 5000/d
    user_rate_limit: 5000/d
    rate_limit_paths:
      - "*"
  retry:
    enabled: true
    mode: key_rotation
    attempts: 3
    retry_after_seconds: 1
    retry_request_methods: [POST, GET, PUT, DELETE, PATCH, OPTIONS]
    retry_status_codes: [429, 500, 502, 503, 504]
  timeouts:
    request_timeout_seconds: 300

apis:
  example_service:
    name: Example Service
    endpoint: https://api.example.com/v1
    key_variable: keys
    headers:
      Authorization: "Bearer ${{keys}}"
    variables:
      keys:
        - upstream_key_1
        - upstream_key_2
    load_balancing_strategy: least_requests
```

### Request Format

Requests are forwarded through `/api/<api_name>/<path>`.

For this API config:

```yaml
apis:
  example_service:
    endpoint: https://api.example.com/v1
```

This proxy request:

```text
POST http://localhost:8080/api/example_service/messages
```

is forwarded to:

```text
POST https://api.example.com/v1/messages
```

## API Examples

### Generic Bearer Token API

```yaml
apis:
  data_vendor:
    name: Data Vendor API
    endpoint: https://api.vendor.example/v2
    key_variable: tokens
    headers:
      Authorization: "Bearer ${{tokens}}"
    variables:
      tokens:
        - vendor_token_1
        - vendor_token_2
    rate_limit:
      enabled: true
      endpoint_rate_limit: 5000/d
      key_rate_limit: 60/m
```

### Custom Header API

```yaml
apis:
  internal_service:
    name: Internal Service
    endpoint: https://internal.example.com
    key_variable: service_tokens
    headers:
      X-Service-Token: "${{service_tokens}}"
      X-Client-Name: "nyaproxy"
    variables:
      service_tokens:
        - service_token_1
        - service_token_2
```

### OpenAI-Compatible API

```yaml
apis:
  openai_compatible:
    name: OpenAI-Compatible Provider
    endpoint: https://api.provider.example/v1
    key_variable: keys
    headers:
      Authorization: "Bearer ${{keys}}"
    variables:
      keys:
        - provider_key_1
        - provider_key_2
    allowed_paths:
      enabled: true
      mode: whitelist
      paths:
        - "/chat/*"
        - "/images/*"
    request_body_substitution:
      enabled: true
      rules:
        - name: "Remove unsupported field"
          operation: remove
          path: "frequency_penalty"
          conditions:
            - field: "frequency_penalty"
              operator: "exists"
```

### Image Generation API

```yaml
apis:
  image_service:
    name: Image Generation Service
    endpoint: https://image.example.com
    key_variable: tokens
    headers:
      Authorization: "Bearer ${{tokens}}"
    variables:
      tokens:
        - image_token_1
        - image_token_2
    load_balancing_strategy: round_robin
    rate_limit:
      enabled: true
      endpoint_rate_limit: 100/h
      key_rate_limit: 10/m
```

## Security Notes

- Set `server.api_key` before exposing NyaProxy outside localhost.
- The first key in `server.api_key` is treated as the admin key for dashboard and configuration access.
- Additional proxy keys can be used by applications for regular proxied API requests.
- Do not share upstream provider credentials with clients. Store them in NyaProxy configuration or your deployment secret manager.
- Restrict `server.cors.allow_origins` to trusted origins when using credentials in browsers.
- Use `allowed_paths` and `allowed_methods` to limit what clients can call.
- Keep logs private. Debug logs may contain request metadata that should be treated as sensitive.

## Rate Limiting

NyaProxy supports multiple limiter scopes:

- `endpoint_rate_limit`: total request rate for one configured upstream API.
- `key_rate_limit`: request rate for each upstream credential.
- `ip_rate_limit`: request rate per client IP.
- `user_rate_limit`: request rate per proxy API key.

Supported formats:

```text
10/s     # 10 requests per second
60/m     # 60 requests per minute
1000/h   # 1000 requests per hour
5000/d   # 5000 requests per day
1/15s    # 1 request per 15 seconds
```

## Request Body Substitution

Request body substitution can set or remove JSON fields before forwarding the request. This is useful for provider compatibility, default values, and policy enforcement.

```yaml
request_body_substitution:
  enabled: true
  rules:
    - name: "Cap temperature"
      operation: set
      path: "temperature"
      value: 0.7
      conditions:
        - field: "temperature"
          operator: "gt"
          value: 0.7
```

See [Request Body Substitution](docs/request_body_substitution.md) for the full rule syntax.

## Management Endpoints

| Endpoint | Purpose |
| --- | --- |
| `/api/<api_name>/<path>` | Proxy requests to configured upstream APIs |
| `/config` | Edit and validate configuration |
| `/dashboard` | View metrics, request history, and queue state |
| `/info` | List configured APIs and service status |

## Deployment Guides

- [Docker Deployment Guide](docs/openai-docker.md)
- [PIP Installation Guide](docs/openai-pip.md)

## Project Status

NyaProxy is in active development. Configuration and behavior may change between releases. Pin a tested version for production deployments and review the [changelog](CHANGELOG.md) before upgrading.

## Community

- Issues: [GitHub Issues](https://github.com/Nya-Foundation/nyaproxy/issues)
- Discord: [Nya Foundation](https://discord.gg/jXAxVPSs7K)
- Contact: [k3scat@gmail.com](mailto:k3scat@gmail.com)

## License

NyaProxy is released under the [MIT License](LICENSE).

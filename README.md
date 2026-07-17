# NyaProxy

**A lightweight API gateway for services that authenticate with API keys, bearer tokens, or custom request headers.**

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

NyaProxy sits between your applications and upstream APIs. Applications call NyaProxy with an internal proxy key; NyaProxy forwards each request to the configured upstream with the correct upstream credentials, rotating across a pool of keys while enforcing rate limits, retries, and path policies.

It is useful when a team needs one place to manage access to external or internal APIs such as AI providers, image generation APIs, SaaS APIs, data vendors, or private services.

Use NyaProxy only with credentials and traffic patterns that are allowed by the upstream service terms.

## Features

| Feature | Description | Config |
| --- | --- | --- |
| Credential injection | Add upstream credentials through headers without exposing them to clients | `headers`, `variables` |
| Credential pooling | Route traffic across multiple upstream keys or tokens | `variables.<name>` |
| Load balancing | `round_robin`, `random`, `least_requests`, `fastest_response`, and `weighted` selection | `load_balancing_strategy`, `key_weights` |
| Rate limiting | Endpoint, upstream key, client IP, and proxy user limits | `rate_limit` |
| Queueing | Hold requests until configured quota becomes available | `queue` |
| Retry and failover | Retry selected status codes, cool down the failing key, and rotate to the next one | `retry` |
| Request policy | Allow or block paths and methods before forwarding | `allowed_paths`, `allowed_methods` |
| Body transformation | Set or remove JSON fields with conditional JMESPath rules | `request_body_substitution` |
| Observability | Web dashboard plus a Prometheus `/metrics` endpoint | `dashboard` |
| Outbound proxy | Send upstream traffic through an optional HTTP/SOCKS proxy | `server.proxy` |

## Quick Start

### Install From PyPI

```bash
pip install nya-proxy
nyaproxy
```

On first run, NyaProxy creates a default `config.yaml` in the current directory and listens on port `8080`, bound to **all interfaces** (`0.0.0.0`).

> **Important:** the generated default config has no `server.api_key`, which means **authentication is disabled** — anyone who can reach the port can use the proxy, dashboard, and config UI. NyaProxy logs a warning at startup in this state. Set `server.api_key` (or bind to `127.0.0.1` with `--host`) before doing anything else.

Then open:

- `http://<host>:8080/config` — configuration UI with validation
- `http://<host>:8080/dashboard` — metrics, request history, and queue status
- `http://<host>:8080/info` — configured API list and service status

### Run With Your Own Config

```bash
nyaproxy --config config.yaml
```

Config changes made through the `/config` UI (or to the file, once you re-save through the UI) trigger an automatic restart so they take effect immediately. Pass `--no-reload` to disable the file-watch supervisor for production setups where restarts should be explicit.

### Install From Source

```bash
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy
pip install -e .
nyaproxy          # or: python -m nya
```

### Docker

```bash
docker run -d \
  -p 8080:8080 \
  -v ${PWD}/config.yaml:/app/config.yaml \
  k3scat/nya-proxy:latest
```

### CLI Reference

| Flag | Description |
| --- | --- |
| `--config`, `-c` | Path to the configuration file |
| `--host`, `-H` / `--port`, `-p` | Bind address and port (defaults: `0.0.0.0` / `8080`) |
| `--no-reload` | Disable the config file-watch supervisor; config changes then require a manual restart |
| `--remote-url`, `-r` / `--remote-api-key`, `-k` / `--remote-app-name`, `-a` | Pull configuration from a remote config server instead of a local file (disables the local `/config` UI) |
| `--version` | Print the version and exit |

## Configuration

NyaProxy is configured with a single YAML file, validated against a bundled JSON schema. Ready-made examples live in [configs/](configs/).

Settings under `default_settings` apply to every API; any API block can override them. For IDE autocomplete and inline validation, keep this modeline as the first line of your config (the shipped examples already include it):

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/nya/schema.json
```

A minimal working config:

```yaml
server:
  api_key:
    - your_admin_proxy_key        # first key = master key (dashboard + config UI)
    - your_application_proxy_key  # additional keys for regular proxy traffic
  logging:
    enabled: true
    level: info
    log_file: app.log
  dashboard:
    enabled: true

default_settings:
  key_variable: keys
  load_balancing_strategy: round_robin
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
  retry:
    enabled: true
    attempts: 3
    retry_after_seconds: 1
    retry_status_codes: [429, 500, 502, 503, 504]
  timeouts:
    request_timeout_seconds: 300

apis:
  example_service:
    name: Example Service
    endpoint: https://api.example.com/v1
    aliases:
      - /example
    key_variable: keys
    headers:
      Authorization: "Bearer ${{keys}}"
    variables:
      keys:
        - upstream_key_1
        - upstream_key_2
```

### Request Format

Requests are forwarded through `/api/<api_name>/<path>` — or `/api/<alias>/<path>` for any alias listed under `aliases`.

With the config above, this proxy request:

```text
POST http://localhost:8080/api/example_service/messages
```

is forwarded to:

```text
POST https://api.example.com/v1/messages
```

with `Authorization: Bearer <one of your upstream keys>` injected, chosen by the load balancer.

## Load Balancing

Five strategies are available per API via `load_balancing_strategy`:

- `round_robin` (default) — cycle through keys in order
- `random` — pick a key at random
- `least_requests` — pick the key that has served the fewest requests
- `fastest_response` — pick the key with the lowest average response time
- `weighted` — distribute according to `key_weights`

For `weighted`, weights align with the order of the key list:

```yaml
apis:
  example_service:
    load_balancing_strategy: weighted
    key_weights: [3, 1, 1]   # first key gets 3x the traffic of the others
    variables:
      keys: [key_a, key_b, key_c]
```

## Rate Limiting

Four independent limiter scopes:

- `endpoint_rate_limit` — total request rate for one upstream API
- `key_rate_limit` — request rate for each upstream credential
- `ip_rate_limit` — request rate per client IP
- `user_rate_limit` — request rate per proxy API key

Formats: `10/s`, `60/m`, `1000/h`, `5000/d`, `1/15s` (one request per 15 seconds), or `"0"` for unlimited. Requests over the limit wait in a per-API queue (bounded by `queue.max_size`) until quota frees up or `queue.expiry_seconds` passes; clients that exceed the IP/user quota get `429` with a `Retry-After` header. `rate_limit_paths` restricts which paths count against the limits (prefix match with a trailing `*`).

## Retries and Failover

When an upstream response matches `retry_status_codes` (and the method is in `retry_request_methods`), NyaProxy cools the failing key down for `retry_after_seconds`, rotates to the next available key, and retries up to `attempts` times — without blocking other traffic on the same API. If every attempt fails, the client receives `429`; upstream connection failures and timeouts surface as `502` and `504` respectively.

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

Streaming responses (SSE and chunked transfer) are forwarded transparently, so OpenAI-style `stream: true` requests work as-is.

## Request Body Substitution

Substitution rules can set or remove JSON fields before forwarding — useful for provider compatibility, default values, and policy enforcement:

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

## Endpoints

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `/api/<api_name>/<path>` | proxy key | Proxy requests to configured upstream APIs |
| `/config` | master key | Edit and validate configuration in the browser |
| `/dashboard` | master key | Metrics, request history, key usage, and queue state; queues can be cleared and metrics reset |
| `/health` | none | Liveness check for load balancers and orchestrators |
| `/info` | none | Configured API list and service status |
| `/metrics` | none | Prometheus exposition endpoint |

## Operations

- **Logging** — configured under `server.logging`; the log file rotates at 10 MB with the last 5 files retained. `debug` level logs request/response metadata (with secrets redacted) — treat debug logs as sensitive and prefer `info` in production.
- **Config reload** — a config change triggers a full process restart via the file-watch supervisor. In-flight requests are dropped and in-memory state (queues, rate-limit windows, metrics) resets. Use `--no-reload` if you'd rather restart explicitly.
- **State** — all rate limiting, queueing, and metrics state is in-memory and per-process. Run a single instance per credential pool; running replicas would give each its own independent limits.

## Security Notes

- **If `server.api_key` is not set, authentication is disabled entirely** — every endpoint (including the config UI) is open to anyone who can reach the port. NyaProxy warns at startup when this is combined with a non-loopback bind. Always set a key before exposing NyaProxy beyond localhost.
- The first key in `server.api_key` is the master key, required for the dashboard and configuration UI. Additional keys can be handed to applications for proxy traffic only.
- Do not share upstream provider credentials with clients — keep them in the NyaProxy config or your deployment's secret manager.
- Restrict `server.cors.allow_origins` to trusted origins when browsers call the proxy with credentials.
- Use `allowed_paths` and `allowed_methods` to limit what clients can call.

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

# NyaProxy

**一个轻量级、基于请求头的 API 代理，用于管理需要密钥或令牌认证的上游服务。**

[English](README.md) | [简体中文](README_zh.md) | [日本語](README_ja.md)

<div align="center">
  <img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/banner.png" alt="NyaProxy Banner" width="800" />

  <p>集中处理凭证注入、配额感知路由、频率限制、重试、故障转移和可观测性，适用于任何使用 API Key、Bearer Token 或自定义请求头的 HTTP API。</p>

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

## 概览

NyaProxy 是一个小型 API 网关，适用于使用 API Key、Bearer Token 或自定义请求头进行认证的服务。客户端使用内部代理密钥访问 NyaProxy，NyaProxy 再根据配置向上游服务注入正确的凭证并转发请求。

它适合团队集中管理外部或内部 API 访问，例如 AI 服务、图像生成服务、SaaS API、数据供应商 API 和公司内部服务。

请仅在上游服务条款允许的凭证和流量模式下使用 NyaProxy。

## 功能

| 功能 | 说明 | 配置 |
| --- | --- | --- |
| 凭证注入 | 通过请求头注入上游凭证，避免客户端直接持有密钥 | `headers`, `variables` |
| 凭证池 | 在多个上游 Key 或 Token 之间路由请求 | `variables.<name>` |
| 负载均衡 | 支持轮询、随机、最少请求、最快响应和权重策略 | `load_balancing_strategy` |
| 频率限制 | 支持端点、上游凭证、客户端 IP 和代理用户维度 | `rate_limit` |
| 请求队列 | 在配额可用前暂存请求 | `queue` |
| 重试与故障转移 | 对指定状态码重试，并临时冷却不可用凭证 | `retry` |
| 请求策略 | 转发前限制允许的路径和 HTTP 方法 | `allowed_paths`, `allowed_methods` |
| 请求体转换 | 使用带条件的 JMESPath 规则设置或删除 JSON 字段 | `request_body_substitution` |
| 可观测性 | 仪表板、请求历史、队列状态和凭证使用统计 | `dashboard` |
| 出站代理 | 可选通过 HTTP/SOCKS 代理访问上游服务 | `server.proxy` |

## 典型场景

- 为多个应用提供统一的第三方 API 访问入口。
- 为浏览器、移动端或内部客户端安全注入上游凭证。
- 按上游服务的每 Key、每分钟或每日配额进行路由。
- 在上游返回 `429` 或 `5xx` 时进行重试和故障转移。
- 在不同 API 提供商之间规范化请求体。
- 监控团队共享 API 凭证的使用情况。

## 快速开始

### 从 PyPI 安装

```bash
pip install nya-proxy
nyaproxy
```

默认服务地址为 `http://localhost:8080`。

常用入口：

- `http://localhost:8080/config`：配置界面
- `http://localhost:8080/dashboard`：指标和队列状态
- `http://localhost:8080/info`：服务和 API 信息

### 使用配置文件运行

```bash
nyaproxy --config config.yaml
```

### 从源码安装

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

## 配置

NyaProxy 使用 YAML 配置。更多示例见 [configs](configs/)。

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

### 请求格式

请求通过 `/api/<api_name>/<path>` 转发。

例如：

```yaml
apis:
  example_service:
    endpoint: https://api.example.com/v1
```

代理请求：

```text
POST http://localhost:8080/api/example_service/messages
```

会被转发到：

```text
POST https://api.example.com/v1/messages
```

## API 示例

### Bearer Token API

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

### 自定义请求头 API

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

### OpenAI 兼容 API

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

### 图像生成 API

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

## 安全建议

- 在对外暴露 NyaProxy 前设置 `server.api_key`。
- 如果未配置 `server.api_key`，NyaProxy 会**完全禁用鉴权**：任何人都可以访问代理、仪表板和配置界面。请务必设置 Key，或仅绑定到 `127.0.0.1`。
- `server.api_key` 中的第一个 Key 会作为管理员 Key，用于访问仪表板和配置界面。
- 其他代理 Key 可用于普通代理请求。
- 不要将上游服务凭证交给客户端。应将其保存在 NyaProxy 配置或部署环境的 Secret 管理系统中。
- 浏览器场景下使用凭证时，请将 `server.cors.allow_origins` 限制为可信来源。
- 使用 `allowed_paths` 和 `allowed_methods` 限制客户端可访问的接口范围。
- 日志应视为敏感数据，尤其是启用 debug 级别时。

## 频率限制

支持以下限制维度：

- `endpoint_rate_limit`：单个上游 API 的整体频率。
- `key_rate_limit`：每个上游凭证的频率。
- `ip_rate_limit`：每个客户端 IP 的频率。
- `user_rate_limit`：每个代理 API Key 的频率。

支持的格式：

```text
10/s     # 每秒 10 次
60/m     # 每分钟 60 次
1000/h   # 每小时 1000 次
5000/d   # 每天 5000 次
1/15s    # 每 15 秒 1 次
```

## 请求体替换

请求体替换可在转发前设置或删除 JSON 字段，适用于 provider 兼容、默认值注入和策略控制。

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

完整规则语法见 [Request Body Substitution](docs/request_body_substitution.md)。

## 管理端点

| 端点 | 用途 |
| --- | --- |
| `/api/<api_name>/<path>` | 转发请求到配置的上游 API |
| `/config` | 编辑和验证配置 |
| `/dashboard` | 查看指标、请求历史和队列状态 |
| `/info` | 查看配置的 API 和服务状态 |

## 部署指南

- [Docker 部署指南](docs/openai-docker.md)
- [PIP 安装指南](docs/openai-pip.md)

## 项目状态

NyaProxy 仍在积极开发中。配置和行为可能在不同版本之间发生变化。生产环境建议固定已验证版本，并在升级前查看 [changelog](CHANGELOG.md)。

## 社区

- Issues: [GitHub Issues](https://github.com/Nya-Foundation/nyaproxy/issues)
- Discord: [Nya Foundation](https://discord.gg/jXAxVPSs7K)
- Contact: [k3scat@gmail.com](mailto:k3scat@gmail.com)

## License

NyaProxy 基于 [MIT License](LICENSE) 发布。

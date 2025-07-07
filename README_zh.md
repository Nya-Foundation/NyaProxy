# 🐾 NyaProxy - 通用API代理

<div align="center">
  <img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/banner.png" alt="NyaProxy Banner" width="800" />
  
  <h3>智能平衡、安全保护、实时监控您的所有API交互</h3>
  
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

## 🌈 项目介绍

> [!WARNING]
> 本项目目前正在积极开发中。文档可能无法反映最新的更改。如果您遇到意外行为，请考虑使用之前的稳定版本或在我们的GitHub仓库中报告问题。

NyaProxy就像一个智能的中央管理器，专门用于访问各种在线服务（API）——无论是AI工具（如OpenAI、Gemini、Anthropic）、图像生成器，还是几乎任何使用访问密钥的Web服务。它帮助您更可靠、高效、安全地使用这些服务。

NyaProxy能为您带来的价值：

- **负载均衡：** 自动将请求分散到多个访问密钥，确保没有单个密钥过载。
- **保持在线：** 当一个密钥失效时，NyaProxy会自动尝试另一个，确保您的应用程序平稳运行（故障转移/弹性）。
- **节省成本：** 优化密钥使用方式，有效降低您的账单。
- **增强安全：** 在代理后隐藏您的实际访问密钥，增加一层保护。
- **使用跟踪：** 提供清晰的仪表板，实时查看您的密钥和服务使用情况。

## 🌟 核心功能
| 功能               | 描述                                                                 | 配置参考          |
|-----------------------|-----------------------------------------------------------------------------|---------------------------|
| 🔄 令牌轮换     | 跨多个提供商的自动密钥循环                             | `variables.keys`          |
| ⚖️ 负载均衡    | 5种策略：轮询、随机、最少请求、最快响应、加权 | `load_balancing_strategy` |
| 🚦 频率限制     | 每个端点/密钥的精细控制，智能排队                       | `rate_limit`              |
| 🕵️ 请求伪装   | 跨多个身份提供者的动态标头替换              | `headers` + `variables`   |
| 📊 实时指标 | 带有请求分析和系统健康状况的交互式仪表板              | `dashboard`               |
| 🔧 体内容替换 | 使用JSONPath进行动态JSON负载转换                          | `request_body_substitution` |

## 📥 快速开始

### 一键部署（零配置，立即使用！）

选择您最喜欢的平台，让我们开始吧！

<table>
  <tr>
    <td align="center">
      <a href="https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FNya-Foundation%2Fnyaproxy">
        <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render">
        <br>部署到 Render
      </a>
    </td>
    <td align="center">
      <a href="https://railway.com/template/TqUoxN?referralCode=9cfC7m">
        <img src="https://railway.com/button.svg" alt="Deploy on Railway">
        <br>部署到 Railway
      </a>
    </td>
  </tr>
</table>

> [!NOTE]
> NyaProxy在启动时会自动创建基本的工作配置。您只需要访问 `/config` 端点来添加您的API密钥！

> [!TIP]
> 您可以使用Gemini AI Studio获取免费API密钥进行测试。Gemini的API与OpenAI兼容，可以与NyaProxy无缝协作。[在这里获取Gemini API密钥](https://aistudio.google.com/app/apikey)。

### 本地部署（适合DIY爱好者！）

#### 先决条件
- Python 3.10或更高版本
- Docker（可选，用于容器化部署）

#### 安装

##### 1. 从PyPI安装（最简单的方法！）
```bash
pip install nya-proxy
```

##### 2. 运行NyaProxy

```bash
nyaproxy
```

...或者提供您自己的配置文件：

```bash
nyaproxy --config config.yaml
```

##### 3. 验证您的设置

访问 `http://localhost:8080/config` 来访问配置UI。

> [!IMPORTANT]
> 如果您将此代理暴露到互联网，请确保在配置中设置强API密钥以防止未经授权的访问。您API密钥数组中的第一个密钥将用作访问敏感界面（如仪表板和配置UI）的主密钥，而其他密钥只能用于常规API请求。
>
> 如果未指定主API密钥，将不会显示登录页面，任何人都可以访问仪表板和配置UI。这对本地测试很方便，但不建议在生产环境中使用。

访问 `http://localhost:8080/dashboard` 查看华丽的管理仪表板和所有API流量可视化。

### 详细部署指南

有关针对初学者的逐步说明，请查看我们的详细部署指南：

- [Docker部署指南](docs/openai-docker.md) - 使用Docker或Docker Compose运行
- [PIP安装指南](docs/openai-pip.md) - 直接Python安装

### 从源码安装

```bash
# 克隆仓库
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy

# 安装依赖
pip install -e .

# 运行NyaProxy
nyaproxy
```

#### Docker
```bash
docker run -d \
  -p 8080:8080 \
  # -v ${PWD}/config.yaml:/app/config.yaml \
  # -v ${PWD}/app.log:/app/app.log \
  k3scat/nya-proxy:latest
```

## 配置

配置参考可以在[Configs文件夹](configs/)中找到

```yaml
# NyaProxy 配置文件
# 此文件包含服务器设置和API端点配置

server:
  api_key: 
  logging:
    enabled: true
    level: debug
    log_file: app.log
  proxy:
    enabled: false
    address: socks5://username:password@proxy.example.com:1080
  dashboard:
    enabled: true
  cors:
    # 使用"*"允许所有来源，但当allow_credentials为true时，出于安全考虑请指定确切的来源
    allow_origins: ["*"]
    allow_credentials: true
    allow_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers: ["*"]

# 应用于所有API端点的默认配置，除非被覆盖
default_settings:
  key_variable: keys
  key_concurrency: true # 如果每个密钥可以处理多个并发请求，则标记为true，否则密钥将被锁定直到请求完成
  randomness: 0.0 # (0.0-x)秒的随机延迟，在请求时间中引入变化性，避免因一致的请求模式而被检测
  load_balancing_strategy: round_robin
  # 路径和方法过滤
  allowed_paths:
    enabled: false # 设置为true以启用请求路径过滤
    mode: whitelist # 如果是"whitelist"，只允许列出的路径；如果是"blacklist"，阻止列出的路径
    paths:
      - "*"
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"] # API的允许HTTP方法
  queue:
    max_size: 200
    max_workers: 10 # 设置可同时处理的最大请求数（队列并发处理数
    expiry_seconds: 300
  rate_limit:
    enabled: true
    endpoint_rate_limit: 10/s # 默认端点频率限制 - 可以按API覆盖
    key_rate_limit: 10/m # 默认密钥频率限制 - 可以按API覆盖
    ip_rate_limit: 5000/d # 基于IP的频率限制，防止滥用和密钥重新分发
    user_rate_limit: 5000/d # 基于服务器部分定义的代理API密钥的用户频率限制
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
    # OpenAI兼容API端点示例
    name: Google Gemini API
    # 支持的端点：
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
      enabled: true
      # 对于Gemini-2.5-pro-exp-03-25，每个密钥的频率限制是5 RPM和25 RPD
      # 端点频率限制应该是n × 每密钥RPD，其中n是密钥数量
      endpoint_rate_limit: 75/d
      key_rate_limit: 5/m
      # 应用频率限制的路径（支持正则表达式） - 默认所有路径"*"
      rate_limit_paths:
        - "/chat/*"
        - "/images/*"

    # 请求体替换设置
    request_body_substitution:
      enabled: false
      # 使用JMEPath的请求体替换规则
      rules:
        # 由于Gemini API不支持frequency_penalty和presence_penalty，我们用这些规则删除它们
        - name: "Remove frequency_penalty"
          operation: remove
          path: "frequency_penalty"
          conditions:
            - field: "frequency_penalty"
              operator: "exists"
        - name: "Remove presence_penalty"
          operation: remove
          path: "presence_penalty"
          conditions:
            - field: "presence_penalty"
              operator: "exists"

  test:
    name: Test API
    endpoint: http://127.0.0.1:8082
    key_variable: keys
    randomness: 5
    headers:
      Authorization: 'Bearer ${{keys}}'
      User-Agent: ${{agents}} # 支持模板变量的灵活标头自定义
    variables:
      keys:
      - your_test_key_1
      - your_test_key_2
      - your_test_key_3
      agents:
      - test_agent_1
      - test_agent_2
      - test_agent_3
    load_balancing_strategy: least_requests
    rate_limit:
      enabled: true
      endpoint_rate_limit: 20/m
      key_rate_limit: 5/m
      ip_rate_limit: 5000/d
      user_rate_limit: 5000/d
      rate_limit_paths:
        - "/v1/*"

  # 请随意在这里添加更多API，只需遵循上面相同的结构
```

## 📡 服务端点

| 服务    | 端点                          | 描述                        |
|------------|-----------------------------------|------------------------------------|
| API代理  | `http://localhost:8080/api/<endpoint_name>` | API请求的主代理端点 |
| 仪表板  | `http://localhost:8080/dashboard` | 实时指标和监控   |
| 配置UI  | `http://localhost:8080/config`    | 可视化配置界面     |

> [!NOTE]
> 如果您的配置端口和主机设置不同，请将 `8080` 和 `localhost` 替换为您配置的端口和主机

## 🔧 API配置

### OpenAI兼容API（Gemini、Anthropic等）
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
    endpoint_rate_limit: 75/d     # 总端点限制
    key_rate_limit: 5/m          # 每个密钥限制
    rate_limit_paths:
      - "/chat/*"            # 对特定路径应用限制
      - "/images/*"
```

### 通用REST API
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

## 🔒 安全功能

### 多API密钥支持

NyaProxy支持使用多个API密钥进行身份验证：

```yaml
server:
  api_key: 
    - your_master_key_for_admin_access
    - another_api_key_for_proxy_only
    - yet_another_api_key_for_proxy_only
```

> [!TIP]
> 列表中的第一个密钥作为主密钥，具有对仪表板和配置UI的完全访问权限。其他密钥只能用于API代理请求。这使您能够与不同的团队或服务共享有限的访问权限。

> [!CAUTION]
> 共享您的NyaProxy实例时，永远不要共享您的主密钥。而是为不同的用户或应用程序创建额外的密钥。

## 高级功能

### 🚦 频率限制功能

NyaProxy在多个级别提供全面的频率限制，以保护您的API并确保公平使用：

**多级频率限制：**
- **端点频率限制**: 控制API端点所有密钥的总请求数
- **密钥频率限制**: 限制每个API密钥的请求以遵守提供商限制  
- **IP频率限制**: 通过限制每个客户端IP地址的请求来防止滥用
- **用户频率限制**: 控制多租户场景中每个NyaProxy API密钥的使用

**灵活的频率限制格式：**
- 每秒: `1/15s` (每15秒1个请求)
- 每分钟: `5/m` (每分钟5个请求) 
- 每小时: `100/h` (每小时100个请求)
- 每天: `1000/d` (每天1000个请求)

**特定路径限制：**
使用正则表达式模式仅对特定端点应用频率限制：
```yaml
rate_limit_paths:
  - "/chat/*"      # 只限制聊天端点
  - "/images/*"    # 只限制图像生成
  - "/v1/models"   # 限制特定端点
```

### 🔄 动态标头替换

NyaProxy强大的模板系统允许您使用变量替换创建动态标头：

```yaml
apis:
  my_api:
    headers:
      Authorization: 'Bearer ${{keys}}'
      X-Custom-Header: '${{custom_variables}}'
    variables:
      keys:
        - key1
        - key2
      custom_variables:
        - value1
        - value2
```

> [!NOTE]
> 标头中的变量会根据您配置的负载均衡策略自动替换为变量列表中的值。

用例包括：
- 在不同的身份验证令牌之间轮换
- 循环使用用户代理以避免检测
- 在不同的账户标识符之间交替

### 🔧 请求体替换
使用JMESPath表达式动态转换JSON负载以添加、替换或删除字段：

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

有关详细的配置选项和示例，请参阅[请求体替换指南](docs/request_body_substitution.md)。

## 🖥️ 管理界面

### 实时指标仪表板
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/dashboard_ui.png" width="800" alt="Dashboard UI"/>

在 `http://localhost:8080/dashboard` 监控：
- 请求量和响应时间
- 频率限制状态和队列深度
- 密钥使用和性能指标
- 错误率和状态码

### 可视化配置界面
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/config_ui.png" width="800" alt="Configuration UI"/>

在 `http://localhost:8080/config` 管理：
- 实时配置编辑
- 语法验证
- 变量管理
- 频率限制调整
- 保存时自动重新加载

## ❤️ 社区

[![Discord](https://img.shields.io/discord/1365929019714834493)](https://discord.gg/jXAxVPSs7K)

> [!NOTE]
> 需要支持？请联系 [k3scat@gmail.com](mailto:k3scat@gmail.com) 或加入我们的Discord社区 [Nya Foundation](https://discord.gg/jXAxVPSs7K)

## 📈 项目增长

[![Star History Chart](https://api.star-history.com/svg?repos=Nya-Foundation/NyaProxy&type=Date)](https://star-history.com/#Nya-Foundation/NyaProxy&Date)
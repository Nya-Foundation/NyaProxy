# NyaProxy

**API キーやトークンで認証する上流サービスを管理する、軽量なヘッダーベース API プロキシです。**

[English](README.md) | [简体中文](README_zh.md) | [日本語](README_ja.md)

<div align="center">
  <img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/brand/banner-1280x640.png" alt="NyaProxy Banner" width="800" />

  <p>API Key、Bearer Token、カスタムヘッダーを使う HTTP API に対して、認証情報の注入、クォータを考慮したルーティング、レート制限、リトライ、可観測性を一元化します。</p>

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

## 概要

NyaProxy は、API Key、Bearer Token、カスタムヘッダーで認証するサービス向けの小さな API ゲートウェイです。クライアントは内部用のプロキシキーで NyaProxy にアクセスし、NyaProxy が設定に基づいて上流サービスの認証情報を注入してリクエストを転送します。

AI プロバイダー、画像生成 API、SaaS API、データベンダー API、社内サービスなど、外部または内部 API へのアクセスをチームで管理したい場合に利用できます。

NyaProxy は、上流サービスの利用規約で許可された認証情報とトラフィックパターンでのみ使用してください。

## 機能

| 機能 | 説明 | 設定 |
| --- | --- | --- |
| 認証情報の注入 | クライアントに上流キーを渡さず、ヘッダーで認証情報を注入 | `headers`, `variables` |
| 認証情報プール | 複数の上流 Key または Token にリクエストを分散 | `variables.<name>` |
| 負荷分散 | ラウンドロビン、ランダム、最少リクエスト、最速レスポンス、重み付け | `load_balancing_strategy` |
| レート制限 | エンドポイント、上流キー、クライアント IP、プロキシユーザー単位で制御 | `rate_limit` |
| キューイング | クォータが利用可能になるまでリクエストを保持 | `queue` |
| リトライとフェイルオーバー | 指定したステータスコードをリトライし、利用不可キーを一時的に冷却 | `retry` |
| 認証情報の隔離 | 上流が指定したエラーステータスを返した認証情報を一時的に選択対象から外す | `key_blocking` |
| リクエストポリシー | 転送前に許可パスと HTTP メソッドを制限 | `allowed_paths`, `allowed_methods` |
| ボディ変換 | 条件付き JMESPath ルールで JSON フィールドを設定または削除 | `request_body_substitution` |
| 可観測性 | ダッシュボード、リクエスト履歴、キュー状態、キー使用量 | `dashboard` |
| アウトバウンドプロキシ | 上流通信を任意の HTTP/SOCKS プロキシ経由に設定 | `server.proxy` |

## 主なユースケース

- 複数アプリケーション向けの第三者 API アクセスゲートウェイ。
- ブラウザ、モバイル、社内クライアントに上流シークレットを渡さない安全な認証情報注入。
- 上流サービスのキー単位、分単位、日単位のクォータを考慮したルーティング。
- `429` や `5xx` へのリトライとフェイルオーバー。
- プロバイダーごとの差異を吸収するリクエストボディの正規化。
- チームで共有する有料 API 認証情報の利用状況監視。

## クイックスタート

### PyPI からインストール

```bash
pip install nya-proxy
nyaproxy
```

デフォルトでは `http://localhost:8080` で起動します。

主なエンドポイント:

- `http://localhost:8080/config`: 設定 UI
- `http://localhost:8080/dashboard`: メトリクスとキュー状態
- `http://localhost:8080/info`: サービスと API 情報

### 設定ファイルを指定して実行

```bash
nyaproxy --config config.yaml
```

### ソースからインストール

```bash
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy
pip install -e .
nyaproxy
```

### Docker

```bash
mkdir -p data
cp configs/openai.yaml data/config.yaml  # プレースホルダーのキーをすべて置き換えてください

docker run -d \
  -p 8080:8080 \
  -v ${PWD}/data:/app \
  --user "$(id -u):$(id -g)" \
  k3scat/nya-proxy:latest --config /app/config.yaml --host 0.0.0.0
```

`config.yaml` そのものではなく、**ディレクトリ**をマウントしてください。`/config` UI は一時ファイルを書き出してから対象ファイルへリネームして保存しますが、ファイル単位でバインドマウントされたパスではこのリネームが `EBUSY` で失敗し、保存のたびに 500 が返ります。同じ理由で、読み取り専用マウントでも保存できません。

イメージは uid 100 で動作するため、そのままでは自分が所有するディレクトリに書き込めません。`--user` を指定してコンテナを現在のユーザーとして実行します。macOS と Windows の Docker Desktop は所有者を自動的にマッピングするため、このフラグは省略できます。

このディレクトリには `config.yaml` と `.nya_state.json` が置かれます。後者はレート制限のウィンドウとキーのクールダウンを再起動をまたいで保持するため、設定変更でクォータがリセットされることはありません。設定はホスト側でも `/config` UI からでも編集でき、いずれの場合も NyaProxy が自動的に再起動して反映します。`server.api_key` を設定するまでは、ポートを外部に公開しないでください。

## 設定

NyaProxy は YAML で設定します。追加例は [configs](configs/) を参照してください。

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
    attempts: 3
    retry_after_seconds: 1
    retry_request_methods: [POST, GET, PUT, DELETE, PATCH, OPTIONS]
    retry_status_codes: [429, 500, 502, 503, 504]
  key_blocking:
    enabled: true
    status_codes: [401, 403]
    duration_seconds: 300
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

### リクエスト形式

リクエストは `/api/<api_name>/<path>` から転送されます。

設定例:

```yaml
apis:
  example_service:
    endpoint: https://api.example.com/v1
```

プロキシへのリクエスト:

```text
POST http://localhost:8080/api/example_service/messages
```

転送先:

```text
POST https://api.example.com/v1/messages
```

## API 例

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

### カスタムヘッダー API

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

### OpenAI 互換 API

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

### 画像生成 API

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

## セキュリティ上の注意

- localhost 以外に公開する前に `server.api_key` を設定してください。
- `server.api_key` が設定されていない場合、NyaProxy は**認証を完全に無効化**します。プロキシ・ダッシュボード・設定 UI に誰でもアクセスできてしまうため、必ずキーを設定するか `127.0.0.1` のみにバインドしてください。
- `server.api_key` の最初のキーは、ダッシュボードと設定 UI にアクセスする管理者キーとして扱われます。
- 追加のプロキシキーは通常の API プロキシリクエストに使用できます。
- 上流サービスの認証情報をクライアントに共有しないでください。NyaProxy の設定またはデプロイ環境の Secret 管理に保存してください。
- ブラウザから認証情報を使う場合は、`server.cors.allow_origins` を信頼済み origin に限定してください。
- `allowed_paths` と `allowed_methods` でクライアントが呼び出せる範囲を制限してください。
- ログは機密データとして扱ってください。特に debug レベルでは注意が必要です。

## レート制限

次のスコープを制御できます。

- `endpoint_rate_limit`: 設定された上流 API 全体の頻度。
- `key_rate_limit`: 上流認証情報ごとの頻度。
- `ip_rate_limit`: クライアント IP ごとの頻度。
- `user_rate_limit`: プロキシ API Key ごとの頻度。

対応形式:

```text
10/s     # 1 秒あたり 10 リクエスト
60/m     # 1 分あたり 60 リクエスト
1000/h   # 1 時間あたり 1000 リクエスト
5000/d   # 1 日あたり 5000 リクエスト
1/15s    # 15 秒あたり 1 リクエスト
```

## リクエストボディ置換

リクエストボディ置換は、転送前に JSON フィールドを設定または削除できます。プロバイダー互換性、デフォルト値、ポリシー制御に利用できます。

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

詳細なルール構文は [Request Body Substitution](docs/request_body_substitution.md) を参照してください。

## 管理エンドポイント

| エンドポイント | 用途 |
| --- | --- |
| `/api/<api_name>/<path>` | 設定済みの上流 API へリクエストを転送 |
| `/config` | 設定の編集と検証 |
| `/dashboard` | メトリクス、リクエスト履歴、キュー状態の確認 |
| `/info` | 設定済み API とサービス状態の確認 |

## デプロイガイド

- [Docker Deployment Guide](docs/openai-docker.md)
- [PIP Installation Guide](docs/openai-pip.md)

## プロジェクト状態

NyaProxy は活発に開発中です。設定や挙動はリリース間で変更される場合があります。本番環境では検証済みバージョンを固定し、アップグレード前に [changelog](CHANGELOG.md) を確認してください。

## コミュニティ

- Issues: [GitHub Issues](https://github.com/Nya-Foundation/nyaproxy/issues)
- Discord: [Nya Foundation](https://discord.gg/jXAxVPSs7K)
- Contact: [k3scat@gmail.com](mailto:k3scat@gmail.com)

## License

NyaProxy は [MIT License](LICENSE) で公開されています。

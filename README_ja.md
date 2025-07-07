# 🐾 NyaProxy - ユニバーサルAPIプロキシ

<div align="center">
  <img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/banner.png" alt="NyaProxy Banner" width="800" />
  
  <h3>すべてのAPI通信をスマートに負荷分散、セキュア化、監視する方法</h3>
  
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

## 🌈 はじめに

> [!WARNING]
> このプロジェクトは現在活発に開発中です。ドキュメントが最新の変更を反映していない場合があります。予期しない動作に遭遇した場合は、以前の安定版の使用を検討するか、GitHubリポジトリで問題を報告してください。

NyaProxyは、様々なオンラインサービス（API）へのアクセスを管理するスマートな中央マネージャーのような役割を果たします。AIツール（OpenAI、Gemini、Anthropicなど）、画像生成器、またはアクセスキーを使用するほぼすべてのWebサービスに対応します。これらのサービスをより信頼性高く、効率的に、そして安全に利用できるよう支援します。

NyaProxyができること：

- **負荷分散：** 複数のアクセスキーにリクエストを自動的に分散し、単一のキーが過負荷になるのを防ぎます。
- **オンライン維持：** 一つのキーが失効した場合、NyaProxyが自動的に別のキーを試し、アプリケーションをスムーズに稼働させ続けます（フェイルオーバー/回復力）。
- **コスト削減：** キーの使用方法を最適化し、料金を抑える可能性があります。
- **セキュリティ強化：** プロキシの背後に実際のアクセスキーを隠し、保護レイヤーを追加します。
- **使用状況追跡：** キーとサービスの使用状況をリアルタイムで確認できる明確なダッシュボードを提供します。

## 🌟 主な機能
| 機能               | 説明                                                                 | 設定リファレンス          |
|-----------------------|-----------------------------------------------------------------------------|---------------------------|
| 🔄 トークンローテーション     | 複数のプロバイダー間での自動キー循環                             | `variables.keys`          |
| ⚖️ 負荷分散    | 5つの戦略：ラウンドロビン、ランダム、最少リクエスト、最速レスポンス、重み付け | `load_balancing_strategy` |
| 🚦 レート制限     | エンドポイント/キーごとの細かな制御とスマートキューイング                       | `rate_limit`              |
| 🕵️ リクエストマスキング   | 複数のアイデンティティプロバイダー間での動的ヘッダー置換              | `headers` + `variables`   |
| 📊 リアルタイムメトリクス | リクエスト分析とシステムヘルスを含むインタラクティブダッシュボード              | `dashboard`               |
| 🔧 ボディ置換 | JSONPathを使用した動的JSONペイロード変換                          | `request_body_substitution` |
| 🧑‍💻 最大ワーカー数 | 同時に処理できるリクエストの最大数を設定します（キューの並列処理数） | `queue.max_workers` |

## 📥 クイックスタート

### ワンクリックデプロイ（設定不要、すぐ使える！）

お好みのプラットフォームを選んで始めましょう！

<table>
  <tr>
    <td align="center">
      <a href="https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FNya-Foundation%2Fnyaproxy">
        <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render">
        <br>Renderにデプロイ
      </a>
    </td>
    <td align="center">
      <a href="https://railway.com/template/TqUoxN?referralCode=9cfC7m">
        <img src="https://railway.com/button.svg" alt="Deploy on Railway">
        <br>Railwayにデプロイ
      </a>
    </td>
  </tr>
</table>

> [!NOTE]
> NyaProxyは起動時に基本的な動作設定を自動的に作成します。APIキーを追加するには `/config` エンドポイントにアクセスするだけです！

> [!TIP]
> テスト用にGemini AI Studioで無料のAPIキーを取得できます。GeminiのAPIはOpenAI互換でNyaProxyとシームレスに動作します。[こちらでGemini APIキーを取得](https://aistudio.google.com/app/apikey)してください。

### ローカルデプロイ（DIY愛好者向け！）

#### 前提条件
- Python 3.10以上
- Docker（オプション、コンテナ化デプロイ用）

#### インストール

##### 1. PyPIからインストール（最も簡単な方法！）
```bash
pip install nya-proxy
```

##### 2. NyaProxyを実行

```bash
nyaproxy
```

...または独自の設定ファイルを提供：

```bash
nyaproxy --config config.yaml
```

##### 3. セットアップの確認

設定UIにアクセスするには `http://localhost:8080/config` を訪問してください。

> [!IMPORTANT]
> このプロキシをインターネットに公開する場合、不正アクセスを防ぐために設定で強力なAPIキーを設定してください。APIキー配列の最初のキーは、ダッシュボードや設定UIなどの機密インターフェースにアクセスするためのマスターキーとして使用され、追加のキーは通常のAPIリクエストのみに使用できます。
>
> マスターAPIキーが指定されていない場合、ログインページは表示されず、誰でもダッシュボードと設定UIにアクセスできます。これはローカルテストには便利ですが、本番環境では推奨されません。

すべてのAPIトラフィック可視化を含む素晴らしい管理ダッシュボードは `http://localhost:8080/dashboard` でチェックしてください。

### 詳細デプロイガイド

初心者向けのステップバイステップ手順については、詳細デプロイガイドをご覧ください：

- [Dockerデプロイガイド](docs/openai-docker.md) - DockerまたはDocker Composeで実行
- [PIPインストールガイド](docs/openai-pip.md) - 直接Pythonインストール

### ソースからインストール

```bash
# リポジトリをクローン
git clone https://github.com/Nya-Foundation/nyaproxy.git
cd nyaproxy

# 依存関係をインストール
pip install -e .

# NyaProxyを実行
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

## 設定

設定リファレンスは[Configsフォルダ](configs/)で確認できます

```yaml
# NyaProxy設定ファイル
# このファイルにはサーバー設定とAPIエンドポイント設定が含まれています

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
    # すべてのオリジンを許可するには"*"を使用しますが、セキュリティのためallow_credentialsがtrueの場合は正確なオリジンを指定してください
    allow_origins: ["*"]
    allow_credentials: true
    allow_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers: ["*"]

# オーバーライドされない限り、すべてのAPIエンドポイントに適用されるデフォルト設定
default_settings:
  key_variable: keys
  key_concurrency: true # 各キーが複数の同時リクエストを処理できる場合はtrueとしてマークし、そうでなければリクエストが完了するまでキーがロックされます
  randomness: 0.0 # リクエストタイミングに変動性を導入し、レート制限による一貫したリクエストパターンでの検出を回避するための(0.0-x)秒のランダム遅延
  load_balancing_strategy: round_robin
  # パスとメソッドフィルタリング
  allowed_paths:
    enabled: false # リクエストパスフィルタリングを有効にするにはtrueに設定
    mode: whitelist # "whitelist"の場合、リストされたパスのみを許可；"blacklist"の場合、リストされたパスをブロック
    paths:
      - "*"
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"] # APIの許可されたHTTPメソッド
  queue:
    max_size: 200
    max_workers: 10 # 同時に処理できるリクエストの最大数を設定します（キューの並列処理数）
    expiry_seconds: 300
  rate_limit:
    enabled: true
    endpoint_rate_limit: 10/s # デフォルトエンドポイントレート制限 - APIごとにオーバーライド可能
    key_rate_limit: 10/m # デフォルトキーレート制限 - APIごとにオーバーライド可能
    ip_rate_limit: 5000/d # 悪用とキー再配布を防ぐIPベースのレート制限
    user_rate_limit: 5000/d # サーバーセクションで定義されたプロキシAPIキーごとのユーザーベースレート制限
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
    # OpenAI互換APIエンドポイントの例
    name: Google Gemini API
    # サポートされているエンドポイント：
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
      # Gemini-2.5-pro-exp-03-25の場合、キーごとのレート制限は5 RPMと25 RPD
      # エンドポイントレート制限はn × キー毎RPDであるべき、nはキー数
      endpoint_rate_limit: 75/d
      key_rate_limit: 5/m
      # レート制限を適用するパス（正規表現サポート） - デフォルトはすべてのパス"*"
      rate_limit_paths:
        - "/chat/*"
        - "/images/*"

    # リクエストボディ置換設定
    request_body_substitution:
      enabled: false
      # JMESPathを使用したリクエストボディの置換ルール
      rules:
        # Gemini APIはfrequency_penaltyとpresence_penaltyをサポートしていないため、これらのルールで削除します
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
      User-Agent: ${{agents}} # テンプレート変数をサポートする柔軟なヘッダーカスタマイゼーション
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

  # ここに追加のAPIを自由に追加してください、上記と同じ構造に従ってください
```

## 📡 サービスエンドポイント

| サービス    | エンドポイント                          | 説明                        |
|------------|-----------------------------------|------------------------------------|
| APIプロキシ  | `http://localhost:8080/api/<endpoint_name>` | APIリクエストのメインプロキシエンドポイント |
| ダッシュボード  | `http://localhost:8080/dashboard` | リアルタイムメトリクスと監視   |
| 設定UI  | `http://localhost:8080/config`    | ビジュアル設定インターフェース     |

> [!NOTE]
> 設定したポートとホスト設定が異なる場合は、`8080`と`localhost`をそれぞれ置き換えてください

## 🔧 API設定

### OpenAI互換API（Gemini、Anthropicなど）
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
    endpoint_rate_limit: 75/d     # 総エンドポイント制限
    key_rate_limit: 5/m          # キーごとの制限
    rate_limit_paths:
      - "/chat/*"            # 特定のパスに制限を適用
      - "/images/*"
```

### 汎用REST API
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

## 🔒 セキュリティ機能

### 複数APIキーサポート

NyaProxyは認証用の複数APIキーの使用をサポートしています：

```yaml
server:
  api_key: 
    - your_master_key_for_admin_access
    - another_api_key_for_proxy_only
    - yet_another_api_key_for_proxy_only
```

> [!TIP]
> リストの最初のキーはマスターキーとして機能し、ダッシュボードと設定UIへの完全なアクセス権を持ちます。追加のキーはAPIプロキシリクエストのみに使用できます。これにより、異なるチームやサービスと限定的なアクセスを共有できます。

> [!CAUTION]
> NyaProxyインスタンスを共有する際は、マスターキーを絶対に共有しないでください。代わりに、異なるユーザーやアプリケーション用に追加のキーを作成してください。

## 高度な機能

### 🚦 レート制限機能

NyaProxyはAPIを保護し公平な使用を確保するため、複数レベルでの包括的なレート制限を提供します：

**マルチレベルレート制限：**
- **エンドポイントレート制限**: APIエンドポイントのすべてのキーでの総リクエスト数を制御
- **キーレート制限**: プロバイダー制限を遵守するために個別のAPIキーごとのリクエストを制限  
- **IPレート制限**: クライアントIPアドレスごとのリクエストを制限して悪用を防止
- **ユーザーレート制限**: マルチテナントシナリオでNyaProxy APIキーごとの使用を制御

**柔軟なレート制限形式：**
- 秒単位: `1/15s` (15秒間に1リクエスト)
- 分単位: `5/m` (1分間に5リクエスト) 
- 時間単位: `100/h` (1時間に100リクエスト)
- 日単位: `1000/d` (1日に1000リクエスト)

**パス固有の制限：**
正規表現パターンを使用して特定のエンドポイントのみにレート制限を適用：
```yaml
rate_limit_paths:
  - "/chat/*"      # チャットエンドポイントのみ制限
  - "/images/*"    # 画像生成のみ制限
  - "/v1/models"   # 特定のエンドポイントを制限
```

### 🔄 動的ヘッダー置換

NyaProxyの強力なテンプレートシステムにより、変数置換を使用して動的ヘッダーを作成できます：

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
> ヘッダー内の変数は、設定された負荷分散戦略に従って変数リストからの値で自動的に置換されます。

使用例には以下が含まれます：
- 異なる認証トークン間のローテーション
- 検出を避けるためのユーザーエージェントの循環
- 異なるアカウント識別子間の交互使用

### 🔧 リクエストボディ置換
JMESPath式を使用してJSONペイロードを動的に変換し、フィールドの追加、置換、削除を行います：

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

詳細な設定オプションと例については、[リクエストボディ置換ガイド](docs/request_body_substitution.md)を参照してください。

## 🖥️ 管理インターフェース

### リアルタイムメトリクスダッシュボード
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/dashboard_ui.png" width="800" alt="Dashboard UI"/>

`http://localhost:8080/dashboard`で監視：
- リクエスト量とレスポンス時間
- レート制限状況とキューの深さ
- キー使用量とパフォーマンスメトリクス
- エラー率とステータスコード

### ビジュアル設定インターフェース
<img src="https://raw.githubusercontent.com/Nya-Foundation/NyaProxy/main/assets/config_ui.png" width="800" alt="Configuration UI"/>

`http://localhost:8080/config`で管理：
- ライブ設定編集
- 構文検証
- 変数管理
- レート制限調整
- 保存時の自動リロード

## ❤️ コミュニティ

[![Discord](https://img.shields.io/discord/1365929019714834493)](https://discord.gg/jXAxVPSs7K)

> [!NOTE]
> サポートが必要ですか？[k3scat@gmail.com](mailto:k3scat@gmail.com)にお問い合わせいただくか、[Nya Foundation](https://discord.gg/jXAxVPSs7K)のDiscordコミュニティにご参加ください

## 📈 プロジェクトの成長

[![Star History Chart](https://api.star-history.com/svg?repos=Nya-Foundation/NyaProxy&type=Date)](https://star-history.com/#Nya-Foundation/NyaProxy&Date)
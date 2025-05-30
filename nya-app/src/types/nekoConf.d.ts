export interface ServerConfig {
  host: string;
  port: number;
  api_key: string;
  logging: {
    enabled: boolean;
    level: string;
    log_file: string;
  };
  proxy: {
    enabled: boolean;
    address: string;
  };
  dashboard: {
    enabled: boolean;
  };
  queue: {
    enabled: boolean;
    max_size: number;
    expiry_seconds: number;
  };
  cors: {
    allow_origins: string[];
    allow_credentials: boolean;
    allow_methods: string[];
    allow_headers: string[];
  };
}

export interface DefaultSettings {
  key_variable: string;
  load_balancing_strategy: string;
  rate_limit: {
    endpoint_rate_limit: string;
    ip_rate_limit: string;
    key_rate_limit: string;
    rate_limit_paths: string[];
  };
  retry: {
    enabled: boolean;
    mode: string;
    attempts: number;
    retry_after_seconds: number;
    retry_request_methods: string[];
    retry_status_codes: number[];
  };
  timeouts: {
    request_timeout_seconds: number;
  };
  simulated_streaming: {
    enabled: boolean;
    delay_seconds: number;
    init_delay_seconds: number;
    chunk_size_bytes: number;
    apply_to: string[];
  };
  request_body_substitution: {
    enabled: boolean;
    rules: Array<{
      name: string;
      operation: string;
      path: string;
      conditions: Array<{
        field: string;
        operator: string;
      }>;
    }>;
  };
}

export interface ApiConfig {
  name: string;
  endpoint: string;
  aliases?: string[];
  key_variable: string;
  headers: Record<string, string>;
  variables: Record<string, string[]>;
  load_balancing_strategy: string;
  rate_limit: {
    endpoint_rate_limit: string;
    key_rate_limit: string;
    rate_limit_paths: string[];
  };
}

export type ApiConfigs = Record<string, ApiConfig>;

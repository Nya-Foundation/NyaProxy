import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, StreamingResponse

import nya

PROXY_KEY = "test-proxy-key"
UPSTREAM_KEYS = ("key-a", "key-b", "key-c")


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_http(url: str, headers: dict[str, str] | None = None) -> None:
    deadline = time.time() + 10
    last_error = None
    while time.time() < deadline:
        try:
            response = httpx.get(url, headers=headers, timeout=1)
            if response.status_code < 500:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


@dataclass
class UpstreamState:
    records: list[dict[str, Any]] = field(default_factory=list)
    statuses_by_key: dict[str, list[int]] = field(default_factory=dict)
    default_status: int = 200
    lock: threading.Lock = field(default_factory=threading.Lock)

    def next_status(self, key: str) -> int:
        with self.lock:
            statuses = self.statuses_by_key.get(key)
            if statuses:
                return statuses.pop(0)
            return self.default_status

    def add_record(self, record: dict[str, Any]) -> None:
        with self.lock:
            self.records.append(record)


@pytest.fixture
def upstream_server():
    state = UpstreamState()
    app = FastAPI()
    port = get_free_port()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def catch_all(request: Request, path: str):
        if path == "health":
            return {"status": "ok"}

        auth = request.headers.get("authorization", "")
        key = auth.removeprefix("Bearer ").strip()
        raw_body = await request.body()
        body: Any
        try:
            body = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            body = raw_body.decode("utf-8", errors="replace")

        state.add_record(
            {
                "method": request.method,
                "path": f"/{path}",
                "authorization": auth,
                "key": key,
                "body": body,
            }
        )

        if path == "stream":

            async def events():
                yield b"data: one\n\n"
                yield b"data: two\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        status = state.next_status(key)
        return JSONResponse(
            status_code=status,
            content={"key": key, "path": f"/{path}", "status": status},
        )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for_http(f"http://127.0.0.1:{port}/health")

    yield f"http://127.0.0.1:{port}", state

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def proxy_server(tmp_path: Path, upstream_server):
    upstream_url, _ = upstream_server
    processes: list[subprocess.Popen] = []

    def start_proxy(
        *,
        load_balancing_strategy: str = "round_robin",
        key_rate_limit: str = "1000/m",
        endpoint_rate_limit: str = "1000/m",
        retry_enabled: bool = True,
        request_body_substitution: str = "      enabled: false",
        allowed_paths: str = """
    enabled: false
    mode: whitelist
    paths:
      - "*"
""",
        queue_expiry_seconds: int = 5,
        max_workers: int = 3,
    ) -> str:
        port = get_free_port()
        config_path = tmp_path / f"nyaproxy-{port}.yaml"
        log_path = tmp_path / f"nyaproxy-{port}.log"
        config_path.write_text(
            f"""
server:
  api_key:
    - {PROXY_KEY}
  logging:
    enabled: true
    level: info
    log_file: {log_path}
  dashboard:
    enabled: false
  cors:
    allow_origins: ["*"]
    allow_credentials: false
    allow_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    allow_headers: ["*"]

default_settings:
  key_variable: keys
  key_concurrency: true
  randomness: 0.0
  load_balancing_strategy: {load_balancing_strategy}
  allowed_paths:
{allowed_paths.rstrip()}
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
  queue:
    max_size: 20
    max_workers: {max_workers}
    expiry_seconds: {queue_expiry_seconds}
  rate_limit:
    enabled: true
    endpoint_rate_limit: {endpoint_rate_limit}
    key_rate_limit: {key_rate_limit}
    ip_rate_limit: 1000/m
    user_rate_limit: 1000/m
    rate_limit_paths:
      - "*"
  retry:
    enabled: {str(retry_enabled).lower()}
    mode: key_rotation
    attempts: 3
    retry_after_seconds: 0.01
    retry_request_methods: [GET, POST, PUT, DELETE, PATCH, OPTIONS]
    retry_status_codes: [429, 500, 502, 503, 504]
  timeouts:
    request_timeout_seconds: 10

apis:
  mock:
    name: Mock API
    endpoint: {upstream_url}
    key_variable: keys
    headers:
      Authorization: "Bearer ${{{{keys}}}}"
    variables:
      keys:
        - {UPSTREAM_KEYS[0]}
        - {UPSTREAM_KEYS[1]}
        - {UPSTREAM_KEYS[2]}
    load_balancing_strategy: {load_balancing_strategy}
    request_body_substitution:
{request_body_substitution.rstrip()}
""",
            encoding="utf-8",
        )

        schema_path = resources.files(nya) / "schema.json"
        code = """
import sys
import uvicorn
from nya.server.app import NyaProxyApp

app = NyaProxyApp(config_path=sys.argv[1], schema_path=sys.argv[2]).app
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(sys.argv[3]),
    log_level="warning",
    server_header=False,
)
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(config_path), str(schema_path), str(port)],
            cwd=os.getcwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        wait_for_http(f"http://127.0.0.1:{port}/info")
        return f"http://127.0.0.1:{port}"

    yield start_proxy

    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

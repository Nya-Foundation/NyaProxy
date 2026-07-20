import asyncio
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
from starlette.responses import JSONResponse, Response, StreamingResponse

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

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
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
                "query": request.url.query,
                "authorization": auth,
                "x_api_key": request.headers.get("x-api-key", ""),
                "key": key,
                "body": body,
            }
        )

        if path == "stream":

            async def events():
                yield b"data: one\n\n"
                yield b"data: two\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        if path == "stream-hang":

            async def hanging_events():
                yield b"data: first\n\n"
                await asyncio.sleep(120)
                yield b"data: never\n\n"

            return StreamingResponse(hanging_events(), media_type="text/event-stream")

        if path == "stream-error":

            async def broken_events():
                yield b"data: first\n\n"
                raise RuntimeError("upstream stream failure")

            return StreamingResponse(broken_events(), media_type="text/event-stream")

        if path.startswith("sleep-"):
            # Controllable hold time, e.g. /sleep-300 holds the key for
            # 300ms — the shape of an image-generation call.
            duration_ms = int(path.rsplit("-", 1)[1])
            await asyncio.sleep(duration_ms / 1000)
            return JSONResponse(content={"slept_ms": duration_ms, "key": key})

        if path == "slow":
            await asyncio.sleep(4)
            return JSONResponse(content={"status": "finally"})

        if path == "cookies":
            response = Response(content=b"cookies")
            response.raw_headers.extend(
                [
                    (b"set-cookie", b"first=1; Path=/"),
                    (b"set-cookie", b"second=2; Path=/"),
                ]
            )
            return response

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
        key_concurrency: bool = True,
        key_rate_limit: str = "1000/m",
        endpoint_rate_limit: str = "1000/m",
        ip_rate_limit: str = "1000/m",
        user_rate_limit: str = "1000/m",
        rate_limit_enabled: bool = True,
        retry_enabled: bool = True,
        retry_after_seconds: float = 0.01,
        key_blocking_enabled: bool = False,
        key_blocking_status_codes: tuple[int, ...] = (403,),
        key_blocking_duration_seconds: float = 300,
        request_body_substitution: str = "      enabled: false",
        allowed_paths: str = """
    enabled: false
    mode: whitelist
    paths:
      - "*"
""",
        request_timeout_seconds: float = 10,
        queue_expiry_seconds: int = 5,
        queue_max_size: int = 20,
        max_workers: int = 3,
        dashboard_enabled: bool = False,
        trusted_proxies: tuple[str, ...] = (),
        extra_api_config: str = "",
        keys: tuple = UPSTREAM_KEYS,
        endpoint_override: str | None = None,
        upstream_headers: str = '      Authorization: "Bearer ${{keys}}"',
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
    enabled: {str(dashboard_enabled).lower()}
  trusted_proxies: [{", ".join(f'"{p}"' for p in trusted_proxies)}]
  cors:
    allow_origins: ["*"]
    allow_credentials: false
    allow_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    allow_headers: ["*"]

default_settings:
  key_variable: keys
  key_concurrency: {str(key_concurrency).lower()}
  randomness: 0.0
  load_balancing_strategy: {load_balancing_strategy}
  allowed_paths:
{allowed_paths.rstrip()}
  allowed_methods: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
  queue:
    max_size: {queue_max_size}
    max_workers: {max_workers}
    expiry_seconds: {queue_expiry_seconds}
  rate_limit:
    enabled: {str(rate_limit_enabled).lower()}
    endpoint_rate_limit: "{endpoint_rate_limit}"
    key_rate_limit: "{key_rate_limit}"
    ip_rate_limit: "{ip_rate_limit}"
    user_rate_limit: "{user_rate_limit}"
    rate_limit_paths:
      - "*"
  retry:
    enabled: {str(retry_enabled).lower()}
    attempts: 3
    retry_after_seconds: {retry_after_seconds}
    retry_request_methods: [GET, POST, PUT, DELETE, PATCH, OPTIONS]
    retry_status_codes: [429, 500, 502, 503, 504]
  key_blocking:
    enabled: {str(key_blocking_enabled).lower()}
    status_codes: [{", ".join(str(code) for code in key_blocking_status_codes)}]
    duration_seconds: {key_blocking_duration_seconds}
  timeouts:
    request_timeout_seconds: {request_timeout_seconds}

apis:
  mock:
    name: Mock API
    endpoint: {endpoint_override or upstream_url}
    aliases:
      - /mock-alias
    key_variable: keys
    headers:
{upstream_headers.rstrip()}
    variables:
      keys:
{chr(10).join(f"        - {key}" for key in keys)}
    load_balancing_strategy: {load_balancing_strategy}
{extra_api_config.rstrip() + chr(10) if extra_api_config.strip() else ""}    request_body_substitution:
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
    proxy_headers=False,
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

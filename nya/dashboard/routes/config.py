"""
Mutating config routes: adding upstream providers and client API keys.

Writes go through the live config manager (schema-validated ``set`` +
``save`` with rollback on save failure), so these routes are only
registered when the dashboard is started with ``enable_control=True``.
"""

import logging
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from nacho import ValidationError
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nacho import Nacho

    from ..api import DashboardAPI


class AddApiRequest(BaseModel):
    """Payload for adding an upstream provider to ``apis``."""

    name: str = Field(..., min_length=1)
    endpoint: str = Field(..., pattern=r"^https?://.+")
    keys: List[str] = Field(..., min_length=1)
    key: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_-]+$")
    headers: Optional[Dict[str, str]] = Field(None, max_length=20)
    """Custom request headers for the provider.

    Optional: when omitted (or empty) the route writes the default
    ``Authorization: Bearer ${{...}}`` header.  Admin-authored config,
    so values are not checked for ``${{`` templates.
    """

    @field_validator("headers")
    @classmethod
    def _validate_headers(cls, value: Optional[Dict[str, str]]):
        if value is None:
            return value
        for name, val in value.items():
            stripped = name.strip()
            if not stripped:
                raise ValueError("header name must not be blank")
            if len(stripped) > 100:
                raise ValueError("header name must be at most 100 characters")
            if not val:
                raise ValueError(f"header '{stripped}' value must not be empty")
            if len(val) > 300:
                raise ValueError(
                    f"header '{stripped}' value must be at most 300 characters"
                )
        return value


class AddClientRequest(BaseModel):
    """Payload for adding a client key to ``server.api_key``."""

    key: str = Field(..., min_length=1)


class AddProviderKeyRequest(BaseModel):
    """Payload for topping up an upstream provider's key pool."""

    key: str = Field(..., min_length=1)


def _slugify(name: str) -> str:
    """Derive an ``apis`` section key from a display name."""
    slug = re.sub(r"[^a-z0-9]", "-", name.lower()).strip("-")
    return slug or f"api-{int(time.time() * 1000)}"


def _mask_key(key: str) -> str:
    """Mask a secret for display — the full value must never leave the API.

    Keys of up to 8 characters are fully starred; longer keys keep only
    the first and last 4 characters around an ellipsis.
    """
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]


_TEMPLATE_PROVIDER_NAME = "Example Service"
_TEMPLATE_PROVIDER_ENDPOINT = "https://api.example.com/v1"


def _is_template_provider(api: Any) -> bool:
    """True for the shipped demo section from the starter config.

    Identified by display name + endpoint (the project's template
    placeholder); hidden from the admin API and protected from deletion.
    """
    if not isinstance(api, dict):
        return False
    name = api.get("name")
    endpoint = api.get("endpoint")
    if not isinstance(name, str) or not isinstance(endpoint, str):
        return False
    return (
        name.strip() == _TEMPLATE_PROVIDER_NAME
        and endpoint.strip() == _TEMPLATE_PROVIDER_ENDPOINT
    )


def _normalize_client_keys(raw: Any) -> List[str]:
    """Coerce ``server.api_key`` (None | str | list) to a list of keys."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return list(raw)
    logger.warning(f"Unexpected server.api_key type: {type(raw).__name__}")
    return []


def _key_variable(config: "Nacho") -> str:
    """Name of the config variable that holds the upstream keys."""
    return config.get_str("default_settings.key_variable") or "keys"


def _set_and_save(
    config: "Nacho",
    path: str,
    value: Any,
    rollback: Callable[[], Any],
) -> Optional[JSONResponse]:
    """Write ``path`` in one ``set``, persist, roll back on save failure.

    Returns ``None`` on success or a JSONResponse describing the failure
    (422 for schema/write validation, 500 for a failed save).
    """
    try:
        config.set(path, value)
    except ValidationError as e:
        logger.error(f"Config validation failed for {path}: {e}")
        return JSONResponse(
            status_code=422,
            content={"error": f"Invalid config: {e}"},
        )
    except (ValueError, PermissionError) as e:
        logger.error(f"Cannot write config at {path}: {e}")
        return JSONResponse(status_code=422, content={"error": str(e)})
    try:
        config.save()
    except Exception as e:
        logger.error(f"Error saving config after writing {path}: {e}")
        try:
            rollback()
        except Exception as rollback_error:
            logger.error(f"Rollback of {path} failed: {rollback_error}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error saving config: {e}"},
        )
    return None


def register_config_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the provider/client-key config routes to ``app``."""

    @app.get("/api/config/apis")
    async def list_apis():
        """List configured providers with masked keys (never full values)."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            key_variable = _key_variable(config)
            apis = config.get_dict("apis", {})
            result = []
            for key, api in apis.items():
                if not isinstance(api, dict):
                    continue
                if _is_template_provider(api):
                    continue
                variables = api.get("variables") or {}
                keys = (
                    variables.get(key_variable) if isinstance(variables, dict) else None
                )
                key_list = keys if isinstance(keys, list) else []
                headers = api.get("headers")
                aliases = api.get("aliases")
                result.append(
                    {
                        "key": key,
                        "name": api.get("name"),
                        "endpoint": api.get("endpoint"),
                        "key_count": len(key_list),
                        "key_masks": [_mask_key(str(k)) for k in key_list],
                        "has_custom_headers": bool(headers),
                        "is_default_auth": headers
                        == {"Authorization": "Bearer ${{" + key_variable + "}}"},
                        "aliases": aliases
                        if isinstance(aliases, list)
                        and all(isinstance(a, str) for a in aliases)
                        else [],
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Error retrieving apis: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving apis: {str(e)}"},
            )

    @app.post("/api/config/apis")
    async def add_api(body: AddApiRequest):
        """Add a new upstream provider to the config."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            key = body.key if body.key is not None else _slugify(body.name)
            apis = config.get_dict("apis", {})
            if key in apis:
                return JSONResponse(
                    status_code=409,
                    content={"error": f"API '{key}' already exists"},
                )
            key_variable = _key_variable(config)
            if body.headers:
                # Custom headers replace the default Authorization header.
                # Keys are stripped; blank-after-strip keys are dropped
                # (pydantic rejects them upfront, this is a safety net).
                headers = {
                    name.strip(): val
                    for name, val in body.headers.items()
                    if name.strip()
                }
                if not headers:
                    return JSONResponse(
                        status_code=422,
                        content={"error": "headers must not be empty"},
                    )
            else:
                # No headers (None or {}): keep the default Bearer header.
                headers = {"Authorization": "Bearer ${{" + key_variable + "}}"}
            value = {
                "name": body.name,
                "endpoint": body.endpoint,
                "headers": headers,
                "variables": {key_variable: list(body.keys)},
            }
            error = _set_and_save(
                config,
                f"apis.{key}",
                value,
                rollback=lambda: config.delete(f"apis.{key}"),
            )
            if error is not None:
                return error
            return {"status": "ok", "key": key}
        except Exception as e:
            logger.error(f"Error adding api: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error adding api: {str(e)}"},
            )

    @app.post("/api/config/apis/{key}/keys")
    async def add_provider_key(key: str, body: AddProviderKeyRequest):
        """Append one upstream key to an existing provider's pool."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            apis = config.get_dict("apis", {})
            if key not in apis:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"API '{key}' not found"},
                )
            new_key = body.key.strip()
            if not new_key:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Key must not be empty"},
                )
            key_variable = _key_variable(config)
            api = apis[key]
            variables = api.get("variables") if isinstance(api, dict) else None
            if not isinstance(variables, dict):
                variables = {}
            stored = variables.get(key_variable)
            old_list = list(stored) if isinstance(stored, list) else []
            if new_key in old_list:
                return JSONResponse(
                    status_code=409,
                    content={"error": "Key already exists in the pool"},
                )
            path = f"apis.{key}.variables.{key_variable}"
            new_list = old_list + [new_key]
            error = _set_and_save(
                config,
                path,
                new_list,
                rollback=lambda: config.set(path, old_list),
            )
            if error is not None:
                return error
            return {"status": "ok", "key": key, "key_count": len(new_list)}
        except Exception as e:
            logger.error(f"Error adding provider key: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error adding provider key: {str(e)}"},
            )

    @app.delete("/api/config/apis/{key}")
    async def delete_api(key: str):
        """Remove a provider section from ``apis``."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            apis = config.get_dict("apis", {})
            if key not in apis:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"API '{key}' not found"},
                )
            if _is_template_provider(apis[key]):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "Example Service is the built-in template "
                        "provider and cannot be deleted"
                    },
                )
            old = apis[key]
            new_apis = {k: v for k, v in apis.items() if k != key}
            if not new_apis:
                # The schema requires `apis` to be non-empty (minProperties 1),
                # so an empty result would only produce an opaque 422 from
                # validation — refuse upfront with a clear conflict instead.
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "Cannot delete the last provider: "
                        "at least one API must stay configured"
                    },
                )
            error = _set_and_save(
                config,
                "apis",
                new_apis,
                rollback=lambda: config.set(f"apis.{key}", old),
            )
            if error is not None:
                return error
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Error deleting api: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error deleting api: {str(e)}"},
            )

    @app.post("/api/config/clients")
    async def add_client_key(body: AddClientRequest):
        """Append a client key to ``server.api_key``."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            key = body.key.strip()
            if not key:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Client key must not be empty"},
                )
            raw_old = config.get("server.api_key")
            current = _normalize_client_keys(raw_old)
            if key in current:
                return JSONResponse(
                    status_code=409,
                    content={"error": "Client key already exists"},
                )

            def _rollback() -> None:
                if raw_old is None:
                    config.delete("server.api_key")
                else:
                    config.set("server.api_key", raw_old)

            error = _set_and_save(
                config,
                "server.api_key",
                current + [key],
                rollback=_rollback,
            )
            if error is not None:
                return error
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Error adding client key: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error adding client key: {str(e)}"},
            )

    @app.get("/api/config/clients")
    async def list_client_keys():
        """List client keys as masks — full values never leave the API."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            current = _normalize_client_keys(config.get("server.api_key"))
            return {
                "clients": [
                    {"index": i, "mask": _mask_key(str(k))}
                    for i, k in enumerate(current)
                ]
            }
        except Exception as e:
            logger.error(f"Error listing client keys: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error listing client keys: {str(e)}"},
            )

    @app.delete("/api/config/clients/{index}")
    async def delete_client_key(index: int):
        """Revoke one client key by index; the last key is protected."""
        if not dashboard.config_manager:
            return JSONResponse(
                status_code=503,
                content={"error": "Config manager not available"},
            )
        try:
            config = dashboard.config_manager.config
            raw_old = config.get("server.api_key")
            current = _normalize_client_keys(raw_old)
            if index < 0 or index >= len(current):
                return JSONResponse(
                    status_code=404,
                    content={"error": f"Client key index {index} not found"},
                )
            if len(current) <= 1:
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": (
                            "Cannot revoke the last client key: "
                            "dashboard auth would be disabled"
                        )
                    },
                )

            def _rollback() -> None:
                if raw_old is None:
                    config.delete("server.api_key")
                else:
                    config.set("server.api_key", raw_old)

            error = _set_and_save(
                config,
                "server.api_key",
                [k for i, k in enumerate(current) if i != index],
                rollback=_rollback,
            )
            if error is not None:
                return error
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Error deleting client key: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error deleting client key: {str(e)}"},
            )

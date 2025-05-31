"""
Data models for request handling in NyaProxy.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.datastructures import URL


@dataclass
class AdvancedConfig:
    """
    Advanced configuration for NyaProxy Request Handling.

    This class holds the settings that control how streaming responses
    are handled, including chunk size and whether to use a streaming
    response.
    """

    # Request Body Substitution
    req_body_subst_enabled: bool = False
    subst_rules: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ProxyRequest:
    """
    Structured representation of an API request for processing.

    This class encapsulates all the data and metadata needed to handle
    a request throughout the proxy processing pipeline.
    """

    # Required request fields
    method: str

    # original url from the request, contains the full path of nya
    _url: Union["URL", str]

    # final url to be requested, differ from _url since the request is proxied
    url: Optional[Union["URL", str]] = None

    # Optional request fields
    _raw: Optional["Request"] = None
    headers: Dict[str, Any] = field(default_factory=dict)
    content: Optional[bytes] = None
    timeout: float = 30.0

    # API Related metadata
    api_name: str = "unknown"
    api_key: Optional[str] = None

    # Processing metadata
    _attempts: int = 0
    _added_at: float = field(default_factory=time.time)
    _expiry: float = 0.0
    _future: Optional[asyncio.Future] = None

    # Whether to apply rate limiting for this request
    _apply_rate_limit: bool = True

    _config: AdvancedConfig = field(default_factory=AdvancedConfig)

    @staticmethod
    async def from_request(request: "Request") -> "ProxyRequest":
        """
        Create a ProxyRequest instance from a FastAPI Request object.
        """

        return ProxyRequest(
            method=request.method,
            _url=request.url,
            headers=dict(request.headers),
            content=await request.body(),
            _raw=request,
            _added_at=time.time(),
        )

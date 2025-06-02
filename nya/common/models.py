"""
Data models for request handling in NyaProxy.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from httpx import Headers

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.datastructures import URL


@dataclass
class ProxyRequest:
    """
    Structured representation of an API request for processing.

    This class encapsulates all the data and metadata needed to handle
    a request throughout the proxy processing pipeline.
    """

    # Required request fields
    method: str

    priority: int  # Lower number = higher priority (1=retry, 2=priority, 3=normal)

    # original url from the proxy request
    _url: Union["URL", str]

    # final url to be requested
    url: Optional[Union["URL", str]] = None

    headers: Dict[str, Any] = field(default_factory=dict)
    content: Optional[bytes] = None

    # API Related metadata
    api_name: str = "unknown"
    api_key: Optional[str] = None

    future: Optional[asyncio.Future] = None

    added_at: float = field(default_factory=time.time)  # Timestamp when added to queue
    is_retry: bool = False
    attempts: int = 0  # Number of attempts made for this request

    # Whether to apply rate limiting for this request
    _rate_limited: bool = False

    @staticmethod
    async def from_request(request: "Request") -> "ProxyRequest":
        """
        Create a ProxyRequest instance from a FastAPI Request object.
        """

        return ProxyRequest(
            method=request.method,
            priority=3,
            _url=request.url,
            headers=Headers(request.headers),
            content=await request.body(),
        )

    def __lt__(self, other):
        """Compare for heap ordering (priority first, then timestamp)."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.added_at < other.added_at

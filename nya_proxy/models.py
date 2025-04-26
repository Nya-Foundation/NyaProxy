"""
Data models for request handling in NyaProxy.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.datastructures import URL


@dataclass
class NyaRequest:
    """
    Structured representation of an API request for processing.

    This class encapsulates all the data and metadata needed to handle
    a request throughout the proxy processing pipeline.
    """

    # Required request fields
    method: str

    # original url from the request, contains the full path of nya_proxy
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
    attempts: int = 0
    added_at: float = field(default_factory=time.time)
    expiry: float = 0.0
    future: Optional[asyncio.Future] = None

    apply_rate_limit: bool = True

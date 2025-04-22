"""
Data models for request handling in NyaProxy.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from fastapi import Request


@dataclass
class NyaRequest:
    """
    Structured representation of an API request for processing.

    This class encapsulates all the data and metadata needed to handle
    a request throughout the proxy processing pipeline.
    """

    # Required request fields
    method: str
    url: str

    # Optional request fields
    _raw_request: Optional["Request"] = None
    headers: Dict[str, str] = field(default_factory=dict)
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

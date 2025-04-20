"""
Data models for request handling in NyaProxy.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


@dataclass
class NyaRequest:
    """
    Structured representation of an API request for processing.
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
    api_key: str = ""

    api_config: Optional[Dict[str, Any]] = None
    trail_path: Optional[str] = None

    # Processing metadata
    attempts: int = 0
    added_at: float = 0.0
    request_id: str = ""
    expiry: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        result = {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "timeout": self.timeout,
        }

        if self.content is not None:
            result["content"] = self.content

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NyaRequest":
        """Create RequestData from dictionary."""
        return cls(
            method=data.get("method", "GET"),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            content=data.get("content"),
            timeout=data.get("timeout", 30.0),
            api_name=data.get("_api_name", "unknown"),
            key_used=data.get("_api_key", ""),
            attempts=data.get("attempts", 0),
            added_at=data.get("added_at", 0.0),
            request_id=data.get("request_id", ""),
            expiry=data.get("expiry", 0.0),
        )

"""
Improved custom exceptions for NyaProxy.
"""


class NyaProxyError(Exception):
    """Base exception class for all NyaProxy errors."""

    pass


class ConfigurationError(NyaProxyError):
    """Exception raised for configuration errors."""

    pass


class VariablesConfigurationError(ConfigurationError):
    """Exception raised for errors in variable configuration."""

    def __init__(self, message: str):
        """
        Initialize variables configuration error.

        Args:
            message: Error message
        """
        super().__init__(f"Variables configuration error: {message}")
        self.message = message


class EndpointRateLimitExceededError(NyaProxyError):
    """Exception raised when rate limits are exceeded."""

    def __init__(
        self, api_name: str, message: str = None, reset_in_seconds: float = None
    ):
        """
        Initialize endpoint rate limit exceeded error.

        Args:
            api_name: Name of the API
            message: Error message
            reset_in_seconds: Time until rate limit resets
        """
        self.api_name = api_name
        self.reset_in_seconds = reset_in_seconds
        super().__init__(message or f"Rate limit exceeded for {api_name}")


class QueueFullError(NyaProxyError):
    """Exception raised when a request queue is full."""

    def __init__(self, api_name: str, max_size: int):
        """
        Initialize queue full error.

        Args:
            api_name: Name of the API
            max_size: Maximum queue size
        """
        self.api_name = api_name
        self.max_size = max_size
        super().__init__(f"Queue for {api_name} is full (max size: {max_size})")


class RequestExpiredError(NyaProxyError):
    """Exception raised when a queued request expires."""

    def __init__(self, api_name: str, wait_time: float):
        """
        Initialize request expired error.

        Args:
            api_name: Name of the API
            wait_time: Time the request waited in queue
        """
        self.api_name = api_name
        self.wait_time = wait_time
        super().__init__(
            f"Request for {api_name} expired after waiting {wait_time:.1f}s"
        )


class APIKeyExhaustedError(NyaProxyError):
    """Exception raised when no API keys are available (all key are rate limited)."""

    def __init__(self, api_name: str):
        """
        Initialize API key rate limit exceeded error.

        Args:
            api_name: Name of the API
        """
        self.api_name = api_name
        super().__init__(f"No available API keys for {api_name} (all rate limited)")


class APIConfigError(NyaProxyError):
    """Exception raised for API configuration errors."""

    pass


class UnknownAPIError(NyaProxyError):
    """Exception raised when requesting an unknown API."""

    def __init__(self, path: str):
        """
        Initialize unknown API error.

        Args:
            path: Request path
        """
        self.path = path
        super().__init__(f"Unknown API endpoint for path: {path}")


class ConnectionError(NyaProxyError):
    """Exception raised for connection errors to target APIs."""

    def __init__(self, api_name: str, url: str, message: str = None):
        """
        Initialize connection error.

        Args:
            api_name: Name of the API
            url: Target URL
            message: Error message
        """
        self.api_name = api_name
        self.url = url
        super().__init__(message or f"Connection error to {api_name} at {url}")


class TimeoutError(NyaProxyError):
    """Exception raised for request timeouts."""

    def __init__(self, api_name: str, timeout: float):
        """
        Initialize timeout error.

        Args:
            api_name: Name of the API
            timeout: Timeout duration in seconds
        """
        self.api_name = api_name
        self.timeout = timeout
        super().__init__(f"Request to {api_name} timed out after {timeout:.1f}s")

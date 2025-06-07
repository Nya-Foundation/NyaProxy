"""
Improved custom exceptions for NyaProxy.
"""


class NyaProxyStatus(Exception):
    """
    Base exception class for all NyaProxy status.
    """

    def __init__(self, message: str = None):
        """
        Initialize NyaProxy status.

        Args:
            message: Status message
        """
        super().__init__()
        self.message = message or "An event occurred in NyaProxy"

    pass


class ConfigurationError(NyaProxyStatus):
    """
    Exception raised for configuration errors.
    """

    def __init__(self, message: str):
        """
        Initialize configuration error.

        Args:
            message: Error message
        """
        super().__init__(f"NyaProxy configuration error: {message}")
        self.message = message

    pass


class VariablesConfigurationError(ConfigurationError):
    """
    Exception raised for errors in variable configuration.
    """

    def __init__(self, message: str):
        """
        Initialize variables configuration error.

        Args:
            message: Error message
        """
        super().__init__(f"NyaProxy variables configuration error: {message}")
        self.message = message


class EndpointRateLimitExceededError(NyaProxyStatus):
    """
    Exception raised when rate limits are exceeded.
    """

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
        super().__init__(
            message or f"NyaProxy: Rate limit exceeded for {api_name} endpoint"
        )


class QueueFullError(NyaProxyStatus):
    """
    Exception raised when a request queue is full.
    """

    def __init__(self, api_name: str, max_size: int):
        """
        Initialize queue full error.

        Args:
            api_name: Name of the API
            max_size: Maximum queue size
        """
        self.api_name = api_name
        self.max_size = max_size
        super().__init__(
            f"NyaProxy: Request queue for {api_name} is full (capacity: {max_size})"
        )


class RequestExpiredError(NyaProxyStatus):
    """
    Exception raised when a queued request expires.
    """

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
            f"NyaProxy: Request for {api_name} expired after waiting {wait_time:.1f}s in queue"
        )


class NoAvailableAPIKeyError(NyaProxyStatus):
    """
    Exception raised when no API keys are available (all key are rate limited).
    """

    def __init__(self, api_name: str):
        """
        Initialize API key rate limit exceeded error.

        Args:
            api_name: Name of the API
        """

        self.api_name = api_name
        super().__init__(
            f"NyaProxy: No available API keys for {api_name} (all rate limited)"
        )


class APIKeyNotConfiguredError(NyaProxyStatus):
    """
    Exception raised when there is no API key found in the configuration.
    """

    def __init__(self, api_name: str):
        """
        Initialize API key not found error.

        Args:
            api_name: Name of the API
        """
        self.api_name = api_name
        super().__init__(f"NyaProxy: No API key found for {api_name}")


class MissingAPIKeyError(NyaProxyStatus):
    """
    Exception raised when an API key is missing in the configuration.
    """

    def __init__(self, api_name: str):
        """
        Initialize missing API key error.

        Args:
            api_name: Name of the API
        """
        self.api_name = api_name
        super().__init__(f"NyaProxy: Missing API key for {api_name}")


class APIConfigError(NyaProxyStatus):
    """
    Exception raised for API configuration errors.
    """

    pass


class UnknownAPIError(NyaProxyStatus):
    """
    Exception raised when requesting an unknown API.
    """

    def __init__(self, path: str):
        """
        Initialize unknown API error.

        Args:
            path: Request path
        """
        self.path = path
        super().__init__(f"NyaProxy: Unknown API endpoint for path: {path}")


class ConnectionError(NyaProxyStatus):
    """
    Exception raised for connection errors to target APIs.
    """

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
        super().__init__(
            message or f"NyaProxy: Connection error to {api_name} at {url}"
        )


class TimeoutError(NyaProxyStatus):
    """
    Exception raised for request timeouts.
    """

    def __init__(self, api_name: str, timeout: float):
        """
        Initialize timeout error.

        Args:
            api_name: Name of the API
            timeout: Timeout duration in seconds
        """
        self.api_name = api_name
        self.timeout = timeout
        super().__init__(
            f"NyaProxy: Request to {api_name} timed out after {timeout:.1f}s"
        )


class RequestRateLimited(NyaProxyStatus):
    """
    Exception raised when a request is rate limited.
    """

    def __init__(self, api_name: str, retry_after: float):
        """
        Initialize request rate limited error.

        Args:
            api_name: Name of the API
            retry_after: Time to wait before retrying in seconds
        """
        self.api_name = api_name
        self.retry_after = retry_after
        super().__init__(
            f"NyaProxy: Request to {api_name} is rate limited, retry after {retry_after:.1f}s"
        )


class EncounterUserDefinedRetry(NyaProxyStatus):
    """
    Exception raised when encountering a retry status code defined in the configuration.
    """

    def __init__(self, api_name: str, status_code: int):
        """
        Initialize retry status code error.

        Args:
            api_name: Name of the API
            status_code: HTTP status code that requires retry
        """
        self.api_name = api_name
        self.status_code = status_code
        super().__init__(
            f"NyaProxy: Encountered retry status code {status_code} for {api_name}"
        )


class ReachedMaxRetriesError(NyaProxyStatus):
    """
    Exception raised when the maximum number of retries is reached.
    """

    def __init__(self, api_name: str, max_retries: int):
        """
        Initialize reached max retries error.

        Args:
            api_name: Name of the API
            max_retries: Maximum number of retries allowed
        """
        self.api_name = api_name
        self.max_retries = max_retries
        super().__init__(
            f"NyaProxy: Reached maximum retries ({max_retries}) for {api_name}"
        )


class ReachedDailyQuotaError(NyaProxyStatus):
    """
    Exception raised when the daily quota for an API is reached.
    """

    def __init__(self, api_name: str, wait_time: float = None):
        """
        Initialize reached daily quota error.

        Args:
            api_name: Name of the API
            wait_time: Optional time to wait before retrying (in seconds)
        """
        self.api_name = api_name
        self.wait_time = wait_time
        super().__init__(
            f"NyaProxy: Max quota is reached for {api_name}, please try again in {wait_time:.1f}s"
            if wait_time
            else f"NyaProxy: Max quota is reached for {api_name}"
        )

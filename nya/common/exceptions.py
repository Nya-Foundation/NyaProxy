"""
Custom exceptions for NyaProxy.
"""

from typing import List, Union


class NyaProxyStatus(Exception):
    """
    Base exception class for all NyaProxy status.
    """

    def __init__(self, message: str = None):
        super().__init__()
        self.message = message or "An event occurred in NyaProxy"


class ConfigurationError(NyaProxyStatus):
    """
    Exception raised for configuration errors.
    """

    def __init__(self, errors: Union[str, List[str]]):
        if isinstance(errors, str):
            errors = [errors]
        super().__init__(f"NyaProxy configuration error: {'; '.join(errors)}")
        self.errors = errors


class VariablesConfigurationError(ConfigurationError):
    """
    Exception raised for errors in variable configuration.
    """

    def __init__(self, message: str):
        super().__init__(f"NyaProxy variables configuration error: {message}")
        self.message = message


class QueueFullError(NyaProxyStatus):
    """
    Exception raised when a request queue is full.
    """

    def __init__(self, api_name: str):
        self.api_name = api_name
        super().__init__(
            f"NyaProxy: Request queue for {api_name} is full, max size reached."
        )


class RequestExpiredError(NyaProxyStatus):
    """
    Exception raised when a queued request expires.
    """

    def __init__(self, api_name: str, wait_time: float):
        self.api_name = api_name
        self.wait_time = wait_time
        super().__init__(
            f"NyaProxy: Request for {api_name} expired after waiting {wait_time:.1f}s in queue"
        )


class APIKeyNotConfiguredError(NyaProxyStatus):
    """
    Exception raised when there is no API key found in the configuration.
    """

    def __init__(self, api_name: str):
        self.api_name = api_name
        super().__init__(f"NyaProxy: No API key found for {api_name}")


class MissingAPIKeyError(NyaProxyStatus):
    """
    Exception raised when an API key is missing for a request being processed.
    """

    def __init__(self, api_name: str):
        self.api_name = api_name
        super().__init__(f"NyaProxy: Missing API key for {api_name}")


class ReachedMaxRetriesError(NyaProxyStatus):
    """
    Exception raised when the maximum number of retries is reached.
    """

    def __init__(self, api_name: str, max_retries: int):
        self.api_name = api_name
        self.max_retries = max_retries
        super().__init__(
            f"NyaProxy: Reached maximum retries ({max_retries}) for {api_name}"
        )


class ReachedMaxQuotaError(NyaProxyStatus):
    """
    Exception raised when the available quota for an API is exhausted.
    """

    def __init__(self, api_name: str, wait_time: float = None):
        self.api_name = api_name
        self.wait_time = wait_time
        super().__init__(
            f"NyaProxy: Max quota is reached for {api_name}, please try again in {wait_time:.1f}s"
            if wait_time
            else f"NyaProxy: Max quota is reached for {api_name}"
        )

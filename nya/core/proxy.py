"""
The NyaProxyCore class handles the main proxy logic, including request processing,
"""

import asyncio
import traceback
from typing import TYPE_CHECKING, Optional, Union

from loguru import logger
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.exceptions import (
    APIKeyExhaustedError,
    EndpointRateLimitExceededError,
    QueueFullError,
    RequestExpiredError,
)
from ..common.models import ProxyRequest
from ..config.manager import ConfigManager
from .handler import RequestHandler

if TYPE_CHECKING:
    from .factory import ServiceFactory


class NyaProxyCore:
    """
    Handles main proxy logic, including requests, token rotation, and rate limiting.
    """

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        factory: Optional["ServiceFactory"] = None,
    ):
        """
        Initialize the proxy handler with dependency injection.

        Args:
            config: Configuration manager instance
            factory: Service factory instance for creating components
        """
        # Core dependencies
        self.config = config or ConfigManager.get_instance()

        # Create or use the service factory
        self.factory = factory or ServiceFactory(config_manager=self.config)

        # Initialize components through the factory
        self.metrics_collector = self.factory.create_metrics_collector()
        self.key_manager = self.factory.create_key_manager()
        self.request_queue = self.factory.create_request_queue()
        self.request_executor = self.factory.create_request_executor()
        self.response_processor = self.factory.create_response_processor()

        # Connect components
        self.factory.connect_components()

        # For backward compatibility and direct access
        self.load_balancers = self.factory.get_component("load_balancers")
        self.rate_limiters = self.factory.get_component("rate_limiters")

        # Initialize request handler
        self.request_handler = RequestHandler(
            config=self.config,
            key_manager=self.key_manager,
            metrics_collector=self.metrics_collector,
        )
        self.request_handler.load_balancers = self.load_balancers

        # Register request processor with queue if present
        if self.request_queue:
            self.request_queue.register_processor(self._process_queued_request)

    async def handle_request(
        self, request: ProxyRequest
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Handle an incoming proxy request.

        Args:
            request: FastAPI Request object

        Returns:
            Response to the client
        """
        try:
            # Prepare the request for forwarding
            api_name, path, _ = self.request_handler.prepare_request(request)

            if not api_name:
                return JSONResponse(
                    status_code=404, content={"error": "Unknown API endpoint"}
                )

            # Skip rate limit verification if path is not rate-limited
            if not self.request_handler.should_apply_rate_limit(api_name, path):
                request._apply_rate_limit = False
                return await self._process_request(request)

            if not await self.key_manager.has_available_keys(api_name):
                logger.debug(
                    f"No available API keys for {api_name}, rate limit exceeded or no keys configured."
                )
                return await self._handle_rate_limit_exceeded(request)

            # Check endpoint-level rate limiting
            self.request_handler.check_endpoint_rate_limit(api_name)

            # Process request and handle response
            return await self._process_request(request)

        except EndpointRateLimitExceededError:
            return await self._handle_rate_limit_exceeded(request)
        except APIKeyExhaustedError:
            return await self._handle_rate_limit_exceeded(request)
        except QueueFullError as e:
            return self._create_error_response(
                e, status_code=429, api_name=request.api_name
            )
        except Exception as e:
            logger.error(f"Error handling request: {str(e)}")
            logger.debug(traceback.format_exc())
            return self._create_error_response(
                e, status_code=500, api_name=request.api_name
            )

    async def _process_request(
        self,
        r: ProxyRequest,
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Process the prepared request and handle the response.

        Args:
            r: Prepared ProxyRequest object

        Returns:
            Response to the client
        """
        logger.debug(f"Processing request to {r.api_name}: {r.url}")

        # Get API configuration
        retry_enabled = self.config.get_api_retry_enabled(r.api_name)
        retry_attempts = self.config.get_api_retry_attempts(r.api_name)
        retry_delay = self.config.get_api_retry_after_seconds(r.api_name)

        if not retry_enabled:
            retry_attempts = 1
            retry_delay = 0

        # Configure custom headers for the proxied request
        await self.request_handler.set_request_headers(r)

        # Execute the request with retries if configured
        return await self.request_executor.execute_with_retry(
            r, retry_attempts, retry_delay
        )

    def _create_error_response(
        self, error: Exception, status_code: int = 500, api_name: str = "unknown"
    ) -> JSONResponse:
        """
        Create an error response for the client.

        Args:
            error: Exception that occurred
            status_code: HTTP status code to return
            api_name: Name of the API

        Returns:
            Error response
        """
        error_message = str(error)
        if status_code == 429:
            message = f"Rate limit exceeded: {error_message}"
        elif status_code == 504:
            message = f"Gateway timeout: {error_message}"
        else:
            message = f"Internal proxy error: {error_message}"

        return JSONResponse(
            status_code=status_code,
            content={"error": message},
        )

    async def _handle_rate_limit_exceeded(
        self,
        request: ProxyRequest,
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Handle a rate-limited request, queueing it if enabled.

        Args:
            request: ProxyRequest object containing the request data

        Returns:
            Response to the client
        """
        api_name = request.api_name

        # If queueing is enabled, try to queue and process the request
        if self.request_queue and self.config.get_queue_enabled():
            try:
                # Calculate appropriate reset time based on rate limit and queue wait time
                next_api_key_reset = await self._get_next_key_reset_time(api_name)
                queue_reset = await self._get_queue_wait_time(api_name)
                reset_in_seconds = int(max(next_api_key_reset, queue_reset))

                # Record metrics for queue hit
                self._record_queue_metrics(request, api_name)

                try:
                    # Enqueue the request and wait for response
                    return await self._enqueue_and_wait(request, reset_in_seconds)
                except (asyncio.TimeoutError, RequestExpiredError) as e:
                    logger.warning(
                        f"Request to {api_name} timed out in queue: {str(e)}"
                    )
                    return self._create_error_response(
                        e, status_code=504, api_name=api_name
                    )
                except QueueFullError as e:
                    return self._create_error_response(
                        e, status_code=429, api_name=api_name
                    )
                except Exception as e:
                    logger.error(f"Error processing queued request: {str(e)}")
                    return self._create_error_response(
                        e, status_code=500, api_name=api_name
                    )

            except Exception as queue_error:
                logger.error(
                    f"Error queueing request: {str(queue_error)}, "
                    f"{traceback.format_exc() if self.config.get_debug_level().upper() == 'DEBUG' else ''}"
                )

        # Default rate limit response if queueing is disabled or failed
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded for this endpoint or no available API keys."
            },
        )

    async def _get_next_key_reset_time(self, api_name: str) -> float:
        """
        Get the time until the next API key will be available.

        Args:
            api_name: Name of the API

        Returns:
            Time in seconds until next key reset
        """
        retry_delay = self.config.get_api_retry_after_seconds(api_name)
        return await self.key_manager.get_api_rate_limit_reset(api_name, retry_delay)

    async def _get_queue_wait_time(self, api_name: str) -> float:
        """
        Get the estimated wait time for a request in the queue.

        Args:
            api_name: Name of the API

        Returns:
            Estimated wait time in seconds
        """
        if not self.request_queue:
            return 0.0

        return await self.request_queue.get_estimated_wait_time(api_name)

    def _record_queue_metrics(self, request: ProxyRequest, api_name: str) -> None:
        """
        Record metrics for a queued request.

        Args:
            request: ProxyRequest object
            api_name: Name of the API
        """
        if self.metrics_collector:
            self.metrics_collector.record_queue_hit(api_name)
            self.metrics_collector.record_rate_limit_hit(
                api_name, request.api_key if request.api_key else "unknown"
            )

    async def _enqueue_and_wait(
        self, request: ProxyRequest, reset_in_seconds: int
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Enqueue a request and wait for it to be processed.

        Args:
            request: ProxyRequest object
            reset_in_seconds: Time until rate limit reset

        Returns:
            Response from processing the request

        Raises:
            Various exceptions if request processing fails
        """
        if not self.request_queue:
            raise RuntimeError("Request queue is not initialized")

        future = await self.request_queue.enqueue_request(
            r=request,
            reset_in_seconds=reset_in_seconds,
        )

        api_timeout = self.config.get_api_default_timeout(request.api_name)
        timeout = reset_in_seconds + api_timeout

        return await asyncio.wait_for(future, timeout=timeout)

    async def _process_queued_request(
        self, r: ProxyRequest
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Process a request from the queue.

        Args:
            r: ProxyRequest object containing the queued request data

        Returns:
            Response from the target API
        """
        return await self._process_request(r)

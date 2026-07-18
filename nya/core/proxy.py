"""
The NyaProxyCore class handles the main proxy logic with queue-first architecture.
"""

import asyncio
import math
import random
import traceback
from typing import TYPE_CHECKING, Dict, Optional, Union

import httpx
from loguru import logger
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.exceptions import (
    APIKeyNotConfiguredError,
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
)
from .control import TrafficManager
from .handler import RequestHandler
from .queue import RequestQueue
from .request import RequestExecutor

if TYPE_CHECKING:
    from ..common.models import ProxyRequest
    from ..config.manager import ConfigManager
    from ..services.metrics import MetricsCollector


class NyaProxyCore:
    """
    NyaProxyCore is the main proxy class that orchestrates all incoming requests
    using a queue-first architecture. It manages request validation, queuing,
    execution, addtional processing, and error handling.
    """

    def __init__(
        self,
        config: Optional["ConfigManager"] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        Initialize the NyaProxyCore with the given configuration and metrics collector.

        Args:
            config: Configuration manager instance
            metrics_collector: Optional metrics collector for tracking request metrics
        """
        self.config = config
        self.metrics_collector = metrics_collector

        # Core components
        self.control = TrafficManager(config=self.config)
        self.handler = RequestHandler(config=self.config)
        self.request_executor = RequestExecutor(
            config=self.config,
            metrics_collector=self.metrics_collector,
        )
        self.request_queue = RequestQueue(
            config=self.config,
            traffic_manager=self.control,
            metrics_collector=self.metrics_collector,
        )

        self.request_queue.register_processor(self._process_queued_request)
        # ``NyaProxyApp`` already closes the executor during shutdown. Attach
        # queue cleanup there so worker and delayed-retry tasks share the same
        # lifecycle without requiring a second application-level hook.
        self.request_executor.add_close_callback(self.request_queue.close)

    async def handle_request(
        self, request: "ProxyRequest"
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Handle request using queue-first architecture.

        Simple flow: validate → enqueue → process → respond
        """
        try:
            # Validate and prepare request
            self.handler.prepare_request(request)

            if not request.api_name:
                return self._error_response("NyaProxy: Unknown API endpoint", 404)

            denial = self.handler.validate_request_policy(request)
            if denial:
                status_code, message = denial
                return self._error_response(message, status_code)

            # Every request uses the same execution pipeline. The queue skips
            # quota windows for exempt paths, while preserving configured load
            # balancing, retries, key concurrency, and observability.
            future = await self.request_queue.enqueue_request(request)
            timeout = self.config.get_api_default_timeout(request.api_name)
            return await asyncio.wait_for(future, timeout=timeout)

        except ReachedMaxQuotaError as e:
            headers = (
                {"Retry-After": str(math.ceil(e.wait_time))} if e.wait_time else None
            )
            return self._error_response(e.message, 429, headers)
        except ReachedMaxRetriesError as e:
            return self._error_response(e.message, 429)
        except APIKeyNotConfiguredError as e:
            return self._error_response(e.message, 500)
        except QueueFullError as e:
            return self._error_response(e.message, 503)
        except (asyncio.TimeoutError, RequestExpiredError):
            return self._error_response("NyaProxy: Request timed out in queue", 504)
        except httpx.TimeoutException:
            return self._error_response("NyaProxy: Upstream request timed out", 504)
        except httpx.TransportError as e:
            logger.warning(f"Upstream transport error for {request.api_name}: {e}")
            return self._error_response(
                "NyaProxy: Unable to reach upstream endpoint", 502
            )
        except Exception as e:
            logger.error(
                f"Unexpected error handling request: {e}, traceback: {traceback.format_exc()}"
            )
            return self._error_response("NyaProxy: Internal proxy error", 500)

    async def _process_queued_request(self, request: "ProxyRequest") -> Response:
        """
        Process a request from the queue.
        """

        # Process request headers by setting API key and custom headers
        await self.handler.process_request_headers(request)
        # Process request body if needed based on API configuration
        self.handler.process_request_body(request)

        # introduce a random delay before executing the request
        random_delay = self.config.get_api_random_delay(request.api_name)

        if random_delay > 0:
            await asyncio.sleep(random.uniform(0, random_delay))

        return await self.request_executor.execute(request)

    def _error_response(
        self,
        message: str,
        status_code: int = 500,
        headers: Optional[Dict[str, str]] = None,
    ) -> JSONResponse:
        """
        Create a simple error response.
        """

        return JSONResponse(
            status_code=status_code, content={"error": message}, headers=headers
        )

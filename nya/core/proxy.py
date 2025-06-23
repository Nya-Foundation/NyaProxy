"""
The NyaProxyCore class handles the main proxy logic with queue-first architecture.
"""

import asyncio
import random
import traceback
from typing import TYPE_CHECKING, Optional, Union

from loguru import logger
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.exceptions import (
    APIKeyNotConfiguredError,
    QueueFullError,
    ReachedDailyQuotaError,
    ReachedMaxRetriesError,
)
from ..common.models import ProxyRequest
from ..config.manager import ConfigManager
from .control import TrafficManager
from .handler import RequestHandler
from .queue import RequestQueue
from .request import RequestExecutor

if TYPE_CHECKING:
    from ..services.metrics import MetricsCollector


class NyaProxyCore:
    """
    Simple, elegant proxy core with queue-first architecture.

    Design principle: Every request goes through the queue for consistent
    processing and natural backpressure.
    """

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        Initialize the proxy with minimal dependencies.
        """
        self.config = config or ConfigManager.get_instance()
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

    async def handle_request(
        self, request: ProxyRequest
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

            # If rate limit does not apply, get a random key and process immediately
            if not request._rate_limited:
                request.api_key = self.control.select_any_key(request.api_name)
                return await self._process_queued_request(request)

            # All requests go through the queue for consistent processing
            future = await self.request_queue.enqueue_request(request)
            timeout = self.config.get_api_default_timeout(request.api_name)
            return await asyncio.wait_for(future, timeout=timeout)

        except (ReachedMaxRetriesError, ReachedDailyQuotaError) as e:
            return self._error_response(e.message, 429)
        except APIKeyNotConfiguredError as e:
            return self._error_response(e.message, 500)
        except QueueFullError as e:
            return self._error_response(e.message, 503)
        except asyncio.TimeoutError:
            return self._error_response("NyaProxy: Request timed out in queue", 504)
        except Exception as e:
            logger.error(
                f"Unexpected error handling request: {e}, traceback: {traceback.format_exc()}"
            )
            return self._error_response(str(e), 500)

    async def _process_queued_request(self, request: ProxyRequest) -> Response:
        """
        Process a request from the queue.
        """

        # Process request headers by setting API key and custom headers
        await self.handler.process_request_headers(request)
        # Process request body if needed based on API configuration
        self.handler.process_request_body(request)

        # introduce a random delay before executing the request
        random_delay = self.config.get_api_random_delay(request.api_name)
        await asyncio.sleep(random.uniform(0, random_delay))

        return await self.request_executor.execute(request)

    def _error_response(
        self,
        message: str,
        status_code: int = 500,
    ) -> JSONResponse:
        """
        Create a simple error response.
        """

        return JSONResponse(status_code=status_code, content={"error": message})

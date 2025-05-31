"""
Load balancer for selecting API keys based on various strategies.
"""

import logging
import random
from typing import Callable, List, Optional, TypeVar

from loguru import logger

from ..common.constants import MAX_QUEUE_SIZE

T = TypeVar("T")


class LoadBalancer:
    """
    Load balancer for distributing requests across multiple API keys or values.

    Supports multiple load balancing strategies:
    - round_robin: Cycle through values in sequence
    - random: Choose a random value
    - least_requests: Select the value with the fewest reqeust counts
    - fastest_response: Select the value with the lowest average response time
    - weighted: Distribute based on assigned weights
    """

    # Define valid strategies
    VALID_STRATEGIES = {
        "round_robin",
        "random",
        "least_requests",
        "fastest_response",
        "weighted",
    }

    def __init__(
        self,
        values: List[str],
        strategy: str = "round_robin",
    ):
        """
        Initialize the load balancer.

        Args:
            values: List of values (keys, tokens, etc.) to balance between
            strategy: Load balancing strategy to use
            logger: Logger instance
        """
        self.values = values or [""]  # Ensure we always have at least an empty value
        self.strategy_name = strategy.lower()

        # Initialize metrics data
        self.requests_count = {value: 0 for value in self.values}
        self.response_times = {value: [] for value in self.values}
        self.weights = [1] * len(self.values)  # Default to equal weights
        self.current_index = 0  # Used for round_robin strategy

    def get_next(self) -> str:
        """
        Get the next value based on the selected load balancing strategy.

        Returns:
            The selected value
        """
        if not self.values:
            logger.warning("No values available for load balancing")
            return ""

        # Select strategy function
        strategy_func = self._get_strategy_function()

        obj = strategy_func()
        self.record_request_count(obj, active=True)

        return obj

    def _get_strategy_function(self) -> Callable[[], str]:
        """
        Get the appropriate strategy function based on strategy name.

        Returns:
            A function that returns the next value
        """
        strategies = {
            "round_robin": self._round_robin_select,
            "random": self._random_select,
            "least_requests": self._least_requests_select,
            "fastest_response": self._fastest_response_select,
            "weighted": self._weighted_select,
        }

        if self.strategy_name not in strategies:
            logger.warning(
                f"Unknown strategy '{self.strategy_name}', using round_robin instead"
            )
            return self._round_robin_select

        return strategies[self.strategy_name]

    def _round_robin_select(self) -> str:
        """Select the next value in a round-robin fashion."""
        value = self.values[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.values)
        return value

    def _random_select(self) -> str:
        """Select a random value."""
        return random.choice(self.values)

    def _least_requests_select(self) -> str:
        """Select the value with the least requests."""
        # Find values with minimum requests count
        min_requests = min(self.requests_count.values())
        candidates = [
            value
            for value, count in self.requests_count.items()
            if count == min_requests
        ]

        # If multiple values have the same count, pick one randomly
        return random.choice(candidates)

    def _fastest_response_select(self) -> str:
        """Select the value with the fastest average response time."""
        # Calculate average response times
        avg_times = {}
        for value, times in self.response_times.items():
            if times:
                avg_times[value] = sum(times) / len(times)
            else:
                # No data means we should try this value to gather data
                avg_times[value] = 0  # Prefer values with no data over slow ones

        # If no data available, fall back to random selection
        if not avg_times:
            return random.choice(self.values)

        # Find values with minimum average response time
        min_time = min(avg_times.values())
        candidates = [
            value for value, avg_time in avg_times.items() if avg_time == min_time
        ]

        # If multiple values have the same average time, pick one randomly
        return random.choice(candidates)

    def _weighted_select(self) -> str:
        """Select a value based on weights."""
        # Handle case where all weights are zero
        if sum(self.weights) == 0:
            return random.choice(self.values)

        # Weighted random selection
        total = sum(self.weights)
        r = random.uniform(0, total)
        cumulative = 0

        for i, weight in enumerate(self.weights):
            cumulative += weight
            if r <= cumulative:
                return self.values[i]

        # Fallback (should never reach here)
        return self.values[-1]

    def set_weights(self, weights: List[int]) -> None:
        """
        Set weights for weighted distribution strategy.

        Args:
            weights: List of integer weights, must match length of values

        Raises:
            ValueError: If weights length doesn't match values length
        """
        if len(weights) != len(self.values):
            raise ValueError(
                f"Weights length ({len(weights)}) must match values length ({len(self.values)})"
            )

        self.weights = weights
        logger.debug(f"Set weights: {weights}")

    def record_request_count(self, value: str, active: bool = True) -> None:
        """
        Record request count to a value for least_requests strategy.

        Args:
            value: The value that is being connected to
            active: True to increment, False to decrement
        """
        if value not in self.requests_count:
            return

        if active:
            self.requests_count[value] += 1
        else:
            self.requests_count[value] = max(0, self.requests_count[value] - 1)

    def record_response_time(self, value: str, response_time: float) -> None:
        """
        Record response time for a value for fastest_response strategy.

        Args:
            value: The value
            response_time: Response time in seconds
        """
        if value not in self.response_times:
            return

        # Add response time to history
        times = self.response_times[value]
        times.append(response_time)

        # Limit history length to last 10 responses
        if len(times) > MAX_QUEUE_SIZE:
            self.response_times[value] = times[-MAX_QUEUE_SIZE:]

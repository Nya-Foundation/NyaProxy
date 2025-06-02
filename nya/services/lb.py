"""
Load balancer for selecting API keys based on various strategies.
"""

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
    - least_requests: Select the value with the fewest request counts
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
        """
        self.values = values or [""]  # Ensure we always have at least an empty value
        self.strategy_name = strategy.lower()

        # Initialize metrics data
        self.requests_count = {value: 0 for value in self.values}
        self.response_times = {value: [] for value in self.values}
        self.weights = [1] * len(self.values)  # Default to equal weights
        self.current_index = 0  # Used for round_robin strategy

    def next(self, strategy: Optional[str] = None) -> str:
        """
        Get the next value based on the selected load balancing strategy.

        Returns:
            The selected value
        """
        if not self.values:
            logger.warning("No values available for load balancing")
            return ""

        # Select strategy function
        strategy_func = self._get_strategy_function(strategy)

        selected_value = strategy_func()
        return selected_value

    def _get_strategy_function(self, strategy: Optional[str]) -> Callable[[], str]:
        """Get the strategy function based on selected strategy."""
        strategy_map = {
            "round_robin": self._round_robin_select,
            "random": self._random_select,
            "least_requests": self._least_requests_select,
            "fastest_response": self._fastest_response_select,
            "weighted": self._weighted_select,
        }

        return strategy_map.get(
            strategy or self.strategy_name, self._round_robin_select
        )

    def _round_robin_select(self) -> str:
        """Select next value in round-robin fashion."""
        if not self.values:
            return ""

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

        # If multiple candidates, choose randomly among them
        return random.choice(candidates)

    def _fastest_response_select(self) -> str:
        """Select the value with the fastest average response time."""
        # Calculate average response times
        avg_times = {}
        for value in self.values:
            times = self.response_times.get(value, [])
            if times:
                avg_times[value] = sum(times) / len(times)
            else:
                avg_times[value] = 0  # Give priority to unused values

        # Find value with minimum average response time
        return min(avg_times, key=avg_times.get)

    def _weighted_select(self) -> str:
        """Select a value based on weights."""
        # Create weighted list
        weighted_choices = []
        for i, value in enumerate(self.values):
            weight = self.weights[i] if i < len(self.weights) else 1
            weighted_choices.extend([value] * weight)

        return random.choice(weighted_choices)

    def set_weights(self, weights: List[int]) -> None:
        """Set weights for weighted load balancing."""
        self.weights = weights[: len(self.values)]
        # Pad with 1s if not enough weights provided
        while len(self.weights) < len(self.values):
            self.weights.append(1)

    def record_request_count(self, value: str) -> None:
        """Record a request for the given value."""
        if value in self.requests_count:
            self.requests_count[value] += 1

    def record_response_time(self, value: str, response_time: float) -> None:
        """Record response time for the given value."""
        if value not in self.response_times:
            self.response_times[value] = []

        # Keep only last 100 response times for efficiency
        self.response_times[value].append(response_time)
        if len(self.response_times[value]) > MAX_QUEUE_SIZE:
            self.response_times[value] = self.response_times[value][-MAX_QUEUE_SIZE:]

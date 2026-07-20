"""
Load balancer for selecting API keys based on various strategies.
"""

import logging
import random
from typing import Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)


T = TypeVar("T")

#: Number of recent response times kept per key for fastest_response.
RESPONSE_TIME_WINDOW = 200


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
        keys: List[str],
        strategy: str = "round_robin",
    ):
        """
        Initialize the load balancer.

        Args:
            keys: List of keys (tokens, etc.) to balance between
            strategy: Load balancing strategy to use
        """
        self.keys = keys or [""]  # Ensure we always have at least an empty value
        self.strategy_name = strategy.lower()

        # Initialize metrics data
        self.requests_count = {key: 0 for key in self.keys}
        self.response_times: Dict[str, List[float]] = {key: [] for key in self.keys}
        self.weights = [1] * len(self.keys)  # Default to equal weights
        self.current_index = 0  # Used for round_robin strategy

    def next(self, strategy: Optional[str] = None) -> str:
        """
        Get the next key based on the selected load balancing strategy.

        Returns:
            The selected key
        """
        if not self.keys:
            logger.warning("No keys available for load balancing")
            return ""

        # Select strategy function
        strategy_func = self._get_strategy_function(strategy)

        selected = strategy_func()
        return selected

    def _get_strategy_function(self, strategy: Optional[str]) -> Callable[[], str]:
        """
        Get the strategy function based on selected strategy.
        """
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
        """
        Select next value in round-robin fashion.
        """
        if not self.keys:
            return ""

        value = self.keys[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.keys)
        return value

    def _random_select(self) -> str:
        """
        Select a random value.
        """
        return random.choice(self.keys)

    def _least_requests_select(self) -> str:
        """
        Select the value with the least requests.
        """
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
        """
        Select the value with the fastest average response time.
        """
        # Calculate average response times
        avg_times = {}
        for value in self.keys:
            times = self.response_times.get(value, [])
            if times:
                avg_times[value] = sum(times) / len(times)
            else:
                avg_times[value] = 0  # Give priority to unused values

        # Find value with minimum average response time
        return min(avg_times, key=lambda key: avg_times[key])

    def _weighted_select(self) -> str:
        """
        Select a value based on weights.
        """
        weights = [
            self.weights[i] if i < len(self.weights) else 1
            for i in range(len(self.keys))
        ]

        # Fall back to uniform selection if no key has a positive weight
        if not any(weight > 0 for weight in weights):
            return random.choice(self.keys)

        return random.choices(self.keys, weights=weights, k=1)[0]

    def set_weights(self, weights: List[int]) -> None:
        """
        Set weights for weighted load balancing.
        """
        self.weights = weights[: len(self.keys)]
        # Pad with 1s if not enough weights provided
        while len(self.weights) < len(self.keys):
            self.weights.append(1)

    def update_request_count(self, key: str, count: int) -> None:
        """
        Record a request for the given key.
        """
        if key in self.requests_count:
            self.requests_count[key] += count

    def record_response_time(self, key: str, response_time: float) -> None:
        """
        Record response time for the given key.
        """
        if key not in self.response_times:
            self.response_times[key] = []

        # Keep only a bounded window of recent response times
        self.response_times[key].append(response_time)
        if len(self.response_times[key]) > RESPONSE_TIME_WINDOW:
            self.response_times[key] = self.response_times[key][-RESPONSE_TIME_WINDOW:]

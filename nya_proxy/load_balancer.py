"""
Load balancer for key/token rotation.
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional


class LoadBalancerError(Exception):
    """Exception raised for load balancer errors."""

    pass


class LoadBalancer:
    """
    Load balancer that distributes requests among available keys/tokens.
    """

    def __init__(
        self,
        items: List[str],
        strategy: str = "round_robin",
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the load balancer.

        Args:
            items: List of keys/tokens to load balance
            strategy: Load balancing strategy (round_robin, random, least_connections, weighted)
            logger: Optional logger instance
        """
        if not items:
            raise LoadBalancerError(
                "Cannot initialize load balancer with empty items list"
            )

        self.items = items
        self.strategy = strategy.lower()
        self.logger = logger

        # For round-robin strategy
        self.current_index = 0

        # For least_connections strategy
        self.connections: Dict[str, int] = {item: 0 for item in items}

        # For weighted strategy (default all weights to 1)
        self.weights: Dict[str, float] = {item: 1.0 for item in items}

        # Performance tracking
        self.success_rates: Dict[str, float] = {item: 1.0 for item in items}
        self.last_update_time: Dict[str, float] = {item: time.time() for item in items}
        self.usage_count: Dict[str, int] = {item: 0 for item in items}

        # Validate strategy
        valid_strategies = ["round_robin", "random", "least_connections", "weighted"]
        if self.strategy not in valid_strategies:
            if self.logger:
                self.logger.warning(
                    f"Unknown strategy: {strategy}, falling back to round_robin"
                )
            self.strategy = "round_robin"

    def get_next(self) -> str:
        """
        Get the next item based on the selected strategy.

        Returns:
            The next key/token to use
        """
        if not self.items:
            raise ValueError("No items available for load balancing")

        if len(self.items) == 1:
            return self.items[0]

        # Choose based on strategy
        if self.strategy == "round_robin":
            return self._round_robin()
        elif self.strategy == "random":
            return self._random()
        elif self.strategy == "least_connections":
            return self._least_connections()
        elif self.strategy == "weighted":
            return self._weighted()

        # Fallback to round-robin if strategy not implemented
        return self._round_robin()

    def _round_robin(self) -> str:
        """Round-robin selection strategy."""
        item = self.items[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.items)
        self.usage_count[item] += 1
        return item

    def _random(self) -> str:
        """Random selection strategy."""
        item = random.choice(self.items)
        self.usage_count[item] += 1
        return item

    def _least_connections(self) -> str:
        """Least connections selection strategy."""
        # Find the item with the fewest active connections
        item = min(self.connections, key=self.connections.get)
        self.connections[item] += 1
        self.usage_count[item] += 1
        return item

    def _weighted(self) -> str:
        """Weighted selection strategy."""
        # Apply success rate to weights for smart selection
        adjusted_weights = {
            item: self.weights[item] * self.success_rates[item] for item in self.items
        }

        # Calculate total weight
        total_weight = sum(adjusted_weights.values())

        # If all weights are zero, fall back to round-robin
        if total_weight <= 0:
            return self._round_robin()

        # Select based on weighted probability
        selection = random.uniform(0, total_weight)
        current = 0

        for item, weight in adjusted_weights.items():
            current += weight
            if current >= selection:
                self.usage_count[item] += 1
                return item

        # Fallback in case of rounding errors
        return self._round_robin()

    def connection_finished(self, item: str, success: bool = True):
        """
        Mark a connection as finished and update performance metrics.

        Args:
            item: The item that was used
            success: Whether the request was successful
        """
        # Update connection count for least_connections strategy
        if item in self.connections:
            self.connections[item] = max(0, self.connections[item] - 1)

        # Update success rate for weighted strategy
        if item in self.success_rates:
            # Calculate time decay factor (more recent results have more weight)
            current_time = time.time()
            time_factor = min(
                1.0, (current_time - self.last_update_time[item]) / 3600
            )  # 1 hour decay

            # Apply time decay to success rate
            decay_factor = 0.9 * time_factor
            self.success_rates[item] *= 1 - decay_factor

            # Update with new result
            if success:
                self.success_rates[item] += decay_factor

            # Ensure rate stays in valid range
            self.success_rates[item] = max(0.1, min(1.0, self.success_rates[item]))
            self.last_update_time[item] = current_time

    def update_weight(self, item: str, weight: float):
        """
        Update the weight for an item (for weighted strategy).

        Args:
            item: The item to update
            weight: New weight value
        """
        if item in self.weights:
            self.weights[item] = max(0.1, weight)  # Ensure weight is at least 0.1

    def get_item_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics for all items.

        Returns:
            Dictionary with item statistics
        """
        return {
            item: {
                "usage_count": self.usage_count[item],
                "connections": self.connections.get(item, 0),
                "success_rate": self.success_rates.get(item, 1.0),
                "weight": self.weights.get(item, 1.0),
            }
            for item in self.items
        }

    def add_item(self, item: str, weight: float = 1.0):
        """
        Add a new item to the load balancer.

        Args:
            item: New item to add
            weight: Weight for weighted strategy
        """
        if item not in self.items:
            self.items.append(item)
            self.connections[item] = 0
            self.weights[item] = weight
            self.success_rates[item] = 1.0
            self.last_update_time[item] = time.time()
            self.usage_count[item] = 0

    def remove_item(self, item: str) -> bool:
        """
        Remove an item from the load balancer.

        Args:
            item: Item to remove

        Returns:
            True if removed, False if not found
        """
        if item not in self.items:
            return False

        self.items.remove(item)

        if item in self.connections:
            del self.connections[item]
        if item in self.weights:
            del self.weights[item]
        if item in self.success_rates:
            del self.success_rates[item]
        if item in self.last_update_time:
            del self.last_update_time[item]
        if item in self.usage_count:
            del self.usage_count[item]

        # Adjust current_index if needed
        if self.items and self.current_index >= len(self.items):
            self.current_index = 0

        return True

def _get_key_id_for_metrics(key: str) -> str:
    """
    Get a key identifier for metrics that doesn't expose the full key.

    Args:
        key: The API key or token

    Returns:
        A truncated version of the key for metrics
    """

    if not key:
        return "unknown"

    return key[:4] + "..." + key[-4:] if len(key) > 8 else key

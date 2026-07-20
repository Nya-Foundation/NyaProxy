"""
Durable runtime state across restarts.

Restarting is how NyaProxy applies a configuration change, so anything the
gateway relies on to enforce quotas has to outlive the process. Without this,
every edit (and every deploy, and every crash) would hand out a fresh burst
allowance and release every quarantined key.

Only rate-limit windows and key cool-downs are stored. In-flight and queued
requests deliberately are not: a queued request owns an ``asyncio.Future``
tied to a client socket that does not survive the restart, so replaying one
would spend upstream quota on a response nobody is waiting for.
"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


STATE_VERSION = 1


def state_key(name: str) -> str:
    """
    Stable, non-reversible identifier for a limiter name.

    Limiter names embed the upstream credential itself (``<api>_key_<key>``)
    and client IPs, none of which belong in a file on disk. Hashing keeps the
    mapping usable across a restart while keeping the file free of secrets.
    """
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def save_state(path: Union[str, Path], payload: Dict[str, Any]) -> bool:
    """
    Write ``payload`` atomically, returning whether it was persisted.

    Never raises: failing to save runtime state must not turn a clean
    shutdown into a crash.
    """
    target = Path(path)
    document = {"version": STATE_VERSION, **payload}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write-and-rename so a crash mid-write cannot leave a torn file that
        # the next start would have to reject.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=target.name, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, target)
        except BaseException:
            # mkstemp already created the file, so clean it up on any failure.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Could not persist runtime state to {target}: {exc}")
        return False


def load_state(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Read state written by ``save_state``.

    A missing, unreadable, corrupt, or version-mismatched file yields an empty
    result rather than an error: starting with cold counters is a degradation,
    but refusing to start is an outage.
    """
    target = Path(path)
    if not target.exists():
        return {}
    try:
        with target.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning(f"Ignoring unreadable runtime state at {target}: {exc}")
        return {}

    if not isinstance(document, dict):
        logger.warning(f"Ignoring malformed runtime state at {target}")
        return {}

    version = document.get("version")
    if version != STATE_VERSION:
        logger.info(
            f"Ignoring runtime state at {target}: version {version!r} "
            f"is not {STATE_VERSION}"
        )
        return {}

    return {k: v for k, v in document.items() if k != "version"}


def resolve_state_path(config_path: Optional[str]) -> Path:
    """
    Place the state file next to the configuration it belongs to.

    Keeping the two together means a bind-mounted config directory carries the
    state with it, which is what makes limits survive a container restart.
    """
    if config_path:
        return Path(config_path).resolve().parent / ".nya_state.json"
    return Path.cwd() / ".nya_state.json"

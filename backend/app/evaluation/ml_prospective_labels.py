"""Pure forward-label semantics for a future prospective ML evaluation.

This module deliberately performs no filesystem, network, database, model, or
production-service work. A later, separately authorized task may pass a
normalized in-memory SH/SZ panel into these functions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class ProspectiveLabelContract:
    """Frozen R1-compatible outcome, execution-cost, and alpha-label rules."""

    schema_version: int = 1
    universe_id: str = "shsz_a_share_v1"
    allowed_exchanges: tuple[str, ...] = ("SH", "SZ")
    horizons: tuple[int, ...] = (3, 5, 10, 20)
    take_profit: float = 0.08
    stop_loss: float = -0.06
    severe_drawdown: float = -0.08
    commission_per_side: float = 0.0003
    slippage_per_side: float = 0.001
    minimum_listing_sessions: int = 120
    minimum_industry_peers: int = 30

    def to_dict(self) -> dict[str, object]:
        """Return the stable serializable representation bound to a later run."""
        payload = asdict(self)
        payload["allowed_exchanges"] = list(self.allowed_exchanges)
        payload["horizons"] = list(self.horizons)
        return payload

    def sha256(self) -> str:
        """Return a deterministic identifier for this immutable semantic contract."""
        encoded = json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

"""Strategy fingerprint derivation for patches and solution candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .models import StrategyFingerprint


class StrategyFingerprinter:
    """Derives a deterministic strategy fingerprint from patch characteristics and hypothesis context."""

    @classmethod
    def create(
        cls,
        hypothesis_id: str,
        affected_files: List[str],
        change_pattern: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StrategyFingerprint:
        """Derives a StrategyFingerprint instance."""
        sorted_files = sorted(list(set(f.strip() for f in affected_files if f.strip())))
        normalized_pattern = change_pattern.strip().lower()

        # Deterministic SHA256 summary hash
        payload = {
            "hypothesis_id": hypothesis_id,
            "affected_files": sorted_files,
            "change_pattern": normalized_pattern,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        summary_hash = hashlib.sha256(encoded).hexdigest()

        return StrategyFingerprint(
            hypothesis_id=hypothesis_id,
            affected_files=sorted_files,
            change_pattern=normalized_pattern,
            summary_hash=summary_hash,
            metadata=metadata or {},
        )

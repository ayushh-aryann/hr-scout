"""Audit trail — append-only JSONL log for all pipeline actions."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from app.security.sanitizer import mask_pii

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


class AuditLog:
    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, session_id: str, details: Dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "event": event,
            "details": mask_pii(details),
        }
        with _LOCK:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as exc:
                logger.warning("Audit log write failed: %s", exc)

    def read_all(self, session_id: str = None) -> list:
        if not self._path.exists():
            return []
        entries = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if session_id is None or entry.get("session_id") == session_id:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.warning("Audit log read failed: %s", exc)
        return entries

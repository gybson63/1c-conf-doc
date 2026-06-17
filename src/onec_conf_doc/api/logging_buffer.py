"""In-memory ring buffer for application logs exposed via API."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class LogRecord:
    id: int
    ts: str
    level: str
    logger: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._capacity = capacity
        self._records: deque[LogRecord] = deque(maxlen=capacity)
        self._next_id = 1
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
            with self._lock:
                log_rec = LogRecord(
                    id=self._next_id,
                    ts=ts,
                    level=record.levelname,
                    logger=record.name,
                    message=msg,
                )
                self._next_id += 1
                self._records.append(log_rec)
        except Exception:
            self.handleError(record)

    def tail(self, limit: int = 200) -> list[LogRecord]:
        with self._lock:
            return list(self._records)[-limit:]

    def since(self, since_id: int) -> list[LogRecord]:
        with self._lock:
            return [r for r in self._records if r.id > since_id]

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._next_id - 1


_handler: RingBufferHandler | None = None


def get_log_handler() -> RingBufferHandler:
    if _handler is None:
        msg = "Logging not initialized"
        raise RuntimeError(msg)
    return _handler


def setup_logging(buffer_size: int = 2000) -> RingBufferHandler:
    global _handler
    if _handler is not None:
        return _handler

    handler = RingBufferHandler(capacity=buffer_size)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("onec_conf_doc")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    _handler = handler
    return handler

"""Stdlib logging with JSON output and request_id context.

Why JSON: when something breaks in a demo and the user pastes a request_id,
`docker logs ddstudio | grep <id>` returns the full chain of events for that
one request. That's the whole debugging story. No structlog dep needed.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

from .settings import settings

# Request id propagates through all log lines for one request.
# Set by main.py middleware on every incoming request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        # Anything passed via `extra={...}` lands on the record as attributes
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_") or key in {
                "args", "msg", "levelname", "levelno", "name", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    # Pretty in TTY, JSON when piped to a file or docker logs
    if sys.stdout.isatty():
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s [%(request_id)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        # Inject request_id into the record so the format string above works
        old_factory = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.request_id = request_id_var.get()
            return record

        logging.setLogRecordFactory(factory)
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


log = logging.getLogger("ddstudio")

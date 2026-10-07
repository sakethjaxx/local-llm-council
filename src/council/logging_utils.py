import json
import logging
import os
import sys
import time

from provider_caps import scrub_secret_values


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            }:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Covers message, extras and tracebacks: error text from providers can echo keys.
        return scrub_secret_values(json.dumps(payload, separators=(",", ":")))


class ScrubbingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub_secret_values(super().format(record))


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_council_logging_configured", False):
        return

    level = os.getenv("COUNCIL_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("COUNCIL_LOG_FORMAT", "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ScrubbingFormatter("%(levelname)s %(name)s %(message)s"))

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    root._council_logging_configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)

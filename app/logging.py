import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                **{
                    key: getattr(record, key)
                    for key in ("request_id", "code", "attempt")
                    if hasattr(record, key)
                },
            }
        )


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("workflow")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

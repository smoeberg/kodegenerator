# monitoring/logger.py
import structlog
from structlog.types import Processor
from datetime import datetime
import json

def configure_logger() -> structlog.BoundLogger:
    """Konfigurer struktureret logging."""
    # Fjern standard logging
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # Tilføj contextvars (f.eks. request_id)
            structlog.processors.add_log_level,        # Tilføj log-niveau
            structlog.processors.StackInfoRenderer(),  # Tilføj stack trace
            structlog.dev.set_exc_info,                # Tilføj exception info
            structlog.processors.TimeStamper(fmt="iso"),  # Tilføj timestamp
            structlog.processors.JSONRenderer()        # Output som JSON
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),  # Skriv til stdout (kan ændres til fil)
        cache_logger_on_first_use=True
    )

    # Opret en logger
    logger = structlog.get_logger()
    return logger

# Opret en global logger
logger = configure_logger()

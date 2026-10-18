"""Minimize GDPR request-reference metadata in *Uvicorn application access logs*.

An application-level filter cannot control Render edge/proxy access logs,
retention policies, or any third-party request telemetry. It is installed
only when the already-approved staging-only privacy preview is enabled.
"""
import logging
import re

_PRIVACY_PATH = re.compile(
    r"""(?<![A-Za-z0-9_-])/privacy/requests(?=$|[/?\s"' ])(?:[/?][^\s"']*)?"""
)
_REDACTED_PATH = "/privacy/requests/[redacted]"


def _redact_private_path(value: str) -> str:
    return _PRIVACY_PATH.sub(_REDACTED_PATH, value)


class PrivacyAccessLogFilter(logging.Filter):
    """Redact privacy path references and query strings, preserving status."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_private_path(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_private_path(v) if isinstance(v, str) else v
                for v in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_private_path(v) if isinstance(v, str) else v
                for key, v in record.args.items()
            }
        return True


def install_privacy_access_log_filter(logger: logging.Logger | None = None) -> None:
    """Idempotent and scoped only to Uvicorn's application request logger."""
    target = logger if logger is not None else logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PrivacyAccessLogFilter) for item in target.filters):
        target.addFilter(PrivacyAccessLogFilter())

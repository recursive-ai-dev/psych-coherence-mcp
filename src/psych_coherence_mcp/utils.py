"""Small date and time helpers shared across the package."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return utc_now().isoformat()


def parse_timestamp(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalize naive values to UTC."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

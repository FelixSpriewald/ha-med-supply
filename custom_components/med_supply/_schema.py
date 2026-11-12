"""Schema library shim: HA >= 2026.x uses probatio, older versions voluptuous."""

try:
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]

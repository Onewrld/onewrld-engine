"""Error classes: every failure is put in one of these buckets so the system knows what to do.

- RetryableError: temporary (network blip, rate limit). The job queue retries with backoff.
- PermanentError: will fail again if retried (bad file, rejected by platform). Goes to the
  dead-letter queue and alerts the owner.
- HaltedError: refused because the kill switch is on. Not a bug; never retried automatically.
"""


class OnewrldError(Exception):
    """Base class for all errors raised on purpose by this system."""


class RetryableError(OnewrldError):
    """Temporary failure. Safe to retry later."""


class PermanentError(OnewrldError):
    """Will not succeed on retry. Needs a human or a code fix."""


class HaltedError(OnewrldError):
    """Action refused because the kill switch is on."""

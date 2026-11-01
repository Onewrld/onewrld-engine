"""Demo handlers: prove the queue, retries, dead-letter and safety gate work end to end.
They never contact any real platform."""

from onewrld import safety
from onewrld.config import Settings
from onewrld.errors import PermanentError, RetryableError
from onewrld.jobs import handler


@handler("demo.post")
def demo_post(settings: Settings, payload: dict):
    """Pretends to publish a post. Goes through the real safety gate."""
    result = safety.outward_action(
        settings,
        "demo_post",
        lambda: {"posted": True, "note": "demo only; nothing real happened"},
        details={"platform": "demo", "text": payload.get("text", "")},
    )
    return result or {"posted": False, "dry_run": True}


@handler("demo.fail")
def demo_fail(settings: Settings, payload: dict):
    """Always fails. payload {"permanent": true} fails permanently; otherwise retryably."""
    if payload.get("permanent"):
        raise PermanentError("demo permanent failure")
    raise RetryableError("demo temporary failure")

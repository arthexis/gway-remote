"""Request-scoped bridge session registration for the trusted HTTP gateway."""
from contextlib import contextmanager


@contextmanager
def gateway_bridge_session(manager, *, bearer, audience):
    """Register an authenticated session and release it after the request."""
    if manager is None:
        raise RuntimeError("bridge sessions not configured")
    session_id = manager.register(token=bearer, audience=audience)
    try:
        yield session_id
    finally:
        manager.revoke(session_id)

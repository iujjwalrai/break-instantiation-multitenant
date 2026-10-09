"""Session lookup errors shared by client sessions.

Sessions are multi-use (`revoked_at`, not `used`), so they do not inherit
`TokenBase` and do not reuse `TokenError`.
"""


class SessionError(Exception):
    """Base for session resolve and revoke failures."""


class SessionInvalidError(SessionError):
    """No row matches the token, or the row is revoked or disabled."""


class SessionExpiredError(SessionError):
    """The row matches and is unrevoked, but `expires_at` has passed."""

class AdminSDKRequestError(RuntimeError):
    """Raised when an admin SDK request fails."""


class AdminSDKAuthenticationError(AdminSDKRequestError):
    """Raised when admin authentication is rejected by the server."""

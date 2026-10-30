"""One bounded domain error contract for every public command transport."""
from threaddesk.core.errors import ManagementError, NotFound, SecretRejected, GateBlocked, ThreadDeskError


def normalized(exc):
    if isinstance(exc, ManagementError):
        return exc
    if isinstance(exc, NotFound):
        return ManagementError("not_found", "The requested object was not found")
    if isinstance(exc, SecretRejected):
        return ManagementError("secret_rejected", "Protected content cannot be accepted")
    if isinstance(exc, GateBlocked):
        return ManagementError("gate_blocked", "The local operation gate denied this request")
    if isinstance(exc, ThreadDeskError):
        return ManagementError(getattr(exc, "code", "invalid_state"), str(exc)[:512])
    if isinstance(exc, (ValueError, TypeError)):
        return ManagementError("validation_error", "The domain rejected these command arguments", error_type=type(exc).__name__)
    return ManagementError("command_unconfirmed", "Execution could not be confirmed; inspect its operation status",
                           error_type=type(exc).__name__)

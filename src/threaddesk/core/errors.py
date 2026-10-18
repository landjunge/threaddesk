class ThreadDeskError(Exception):
    pass


class NotFound(ThreadDeskError):
    pass


class InvalidState(ThreadDeskError):
    pass


class SecretRejected(ThreadDeskError):
    pass


class GateBlocked(ThreadDeskError):
    pass


class ManagementError(InvalidState):
    """Stable machine code with a bounded, non-secret explanation."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details

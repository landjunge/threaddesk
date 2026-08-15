class ThreadDeskError(Exception):
    pass


class NotFound(ThreadDeskError):
    pass


class InvalidState(ThreadDeskError):
    pass


class SecretRejected(ThreadDeskError):
    pass


class StoreCorrupt(ThreadDeskError):
    """A store file is unreadable. Never raised for a merely missing file."""


class GateBlocked(ThreadDeskError):
    pass

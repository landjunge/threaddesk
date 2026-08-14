class ThreadDeskError(Exception):
    pass


class NotFound(ThreadDeskError):
    pass


class InvalidState(ThreadDeskError):
    pass


class SecretRejected(ThreadDeskError):
    pass

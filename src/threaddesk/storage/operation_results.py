"""Typed views of heterogeneous durable management-operation results."""


def result_object(record):
    """Reservations and successful scalar results are valid non-object receipts."""
    result = record.get("result")
    return result if isinstance(result, dict) else {}

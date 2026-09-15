import pytest

from threaddesk.core.errors import InvalidState
from threaddesk.services.return_contract import build, validate


def sample():
    return build(
        handoff_id="handoff-1", handoff_revision=2, thread_id="thread-1",
        task_id="task-1", worker="grok", run_id="run-7", result="Implemented",
        files=["src/app.py"], pull_request="https://github.com/a/b/pull/1",
        test_results=["42 passed"], open_issues=["Needs review"],
    )


def test_return_is_complete_and_always_unverified() -> None:
    payload = sample()
    assert payload["format"] == "threaddesk.return.v1"
    assert payload["handoff_revision"] == 2
    assert payload["delivery_status"] == "delivered"
    assert payload["review_status"] == "unverified"
    assert payload["files"] == ["src/app.py"]
    assert payload["test_results"] == ["42 passed"]


@pytest.mark.parametrize("field,value", [
    ("handoff_revision", 0), ("worker", ""), ("files", "not-a-list"),
    ("delivery_status", "accepted"), ("review_status", "verified"),
])
def test_untrusted_return_cannot_claim_acceptance(field, value) -> None:
    payload = sample()
    payload[field] = value
    with pytest.raises(InvalidState):
        validate(payload)

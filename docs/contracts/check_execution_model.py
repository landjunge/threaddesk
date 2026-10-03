"""Bounded B0 protocol model, not a product implementation or crypto proof.

Run: python docs/contracts/check_execution_model.py
Only the Python standard library is used. No files, network, secrets or real
money are changed. The actual product's 22 acceptance cases remain unproved.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import json


LIMIT = 10
MAX_COST = 8
FINAL_COST = 2


@dataclass(frozen=True)
class Attempt:
    phase: str = "NEW"
    ledger: str = "NONE"
    sends: int = 0
    permit: bool = False
    admitted_valid: bool = False
    cancelled_once: bool = False
    replayed: bool = False


@dataclass(frozen=True)
class State:
    attempts: tuple[Attempt, Attempt] = (Attempt(), Attempt())
    rights: bool = True
    frozen: bool = False
    sources: bool = True
    running: bool = True
    crashed: bool = False


class InvariantViolation(Exception):
    pass


def used(s: State) -> int:
    return sum(MAX_COST if a.ledger == "HELD" else
               FINAL_COST if a.ledger == "SETTLED" else 0
               for a in s.attempts)


def put(s: State, index: int, a: Attempt) -> State:
    values = list(s.attempts)
    values[index] = a
    return replace(s, attempts=tuple(values))


def check(s: State) -> None:
    if used(s) > LIMIT:
        raise InvariantViolation("shared_money_limit")
    for a in s.attempts:
        if a.phase in {"ADMITTED", "DISPATCHED", "UNKNOWN"}:
            if not a.admitted_valid:
                raise InvariantViolation("admission_after_control_barrier")
            if a.ledger != "HELD":
                raise InvariantViolation("unknown_or_live_attempt_lost_reservation")
        if a.phase == "SETTLED" and (a.ledger != "SETTLED" or a.sends != 1):
            raise InvariantViolation("settlement_without_one_observed_send")
        if a.sends > 1 or a.replayed:
            raise InvariantViolation("automatic_resend_after_unknown")
        if a.cancelled_once and a.ledger != "CANCELLED":
            raise InvariantViolation("late_reserve_reopened_tombstone")
        if a.phase == "CANCELLED" and (a.sends or a.permit):
            raise InvariantViolation("cancelled_attempt_can_send")


def transitions(s: State, mutation: str = ""):
    """Every action is a durable atomic step in its own component.

    Reserve and cancel deliveries can be reordered. Admission/control effects
    share one coordinator. Settlement is abstracted as a combined acknowledged
    transition: lost settlement replies, real DB durability, time, quotes,
    identity proofs and multiple budget accounts are outside this model.
    """
    if s.running and s.rights:
        yield "revoke_effective", replace(s, rights=False)
    if s.running and not s.frozen:
        yield "freeze_effective", replace(s, frozen=True)
    if s.sources:
        yield "required_source_down", replace(s, sources=False)
    if s.running and not s.crashed:
        recovered = []
        for a in s.attempts:
            phase = a.phase
            if phase in {"ADMITTED", "DISPATCHED"}:
                phase = "UNKNOWN"
            elif phase in {"INTENT", "RESERVED"}:
                phase = "CANCELLED"
            recovered.append(replace(a, phase=phase, permit=False))
        yield "crash_and_classify_durable_attempts", replace(
            s, attempts=tuple(recovered), running=False, crashed=True)
    if not s.running:
        # Recovery only restores this same intact journal; never an old backup.
        yield "recover_same_durable_journal", replace(s, running=True)

    for i, a in enumerate(s.attempts):
        label = f"call_{i + 1}:"
        if s.running and a.phase == "NEW" and s.rights and not s.frozen and s.sources:
            yield label + "durable_intent", put(s, i, replace(a, phase="INTENT"))
        if a.phase in {"INTENT", "RESERVED", "CANCELLED"}:
            # A previously sent Reserve can arrive after the coordinator crash
            # or after cancellation. Tombstones must defeat that delayed RPC.
            eligible = a.ledger == "NONE" or (
                mutation == "forget_tombstone" and a.ledger == "CANCELLED")
            if eligible:
                affordable = used(s) + MAX_COST <= LIMIT
                held = not s.frozen and (affordable or mutation == "skip_budget_check")
                ledger = "HELD" if held else "DENIED"
                yield label + "deliver_reserve", put(s, i, replace(a, ledger=ledger))
        if s.running and a.phase == "INTENT" and a.ledger == "HELD":
            yield label + "observe_reservation", put(s, i, replace(a, phase="RESERVED"))
        if s.running and a.phase in {"INTENT", "RESERVED"}:
            yield label + "fence_no_send", put(s, i, replace(a, phase="CANCELLED"))
        if a.phase == "CANCELLED" and a.ledger != "CANCELLED":
            yield label + "deliver_cancel_tombstone", put(s, i, replace(
                a, ledger="CANCELLED", cancelled_once=True))
        if s.running and a.phase == "RESERVED" and a.ledger == "HELD":
            valid = s.rights and not s.frozen and s.sources
            if valid or mutation == "skip_current_authority":
                yield label + "admit", put(s, i, replace(
                    a, phase="ADMITTED", permit=True, admitted_valid=valid))
        if s.running and a.phase == "ADMITTED" and a.permit:
            # Earlier admission can still send after a later effective revoke.
            yield label + "send_once", put(s, i, replace(
                a, phase="DISPATCHED", permit=False, sends=a.sends + 1))
        if a.phase in {"DISPATCHED", "UNKNOWN"} and a.sends == 1:
            yield label + "settle_final_provider_receipt", put(s, i, replace(
                a, phase="SETTLED", ledger="SETTLED"))
        if mutation == "refund_unknown" and a.phase == "UNKNOWN" and a.ledger == "HELD":
            yield label + "unsafe_timeout_refund", put(s, i, replace(a, ledger="NONE"))
        if mutation == "retry_unknown" and s.running and a.phase == "UNKNOWN":
            yield label + "unsafe_retry", put(s, i, replace(
                a, sends=a.sends + 1, replayed=True))


def explore(mutation: str = "") -> dict:
    initial = State()
    queue = deque([initial])
    parents = {initial: None}
    edges = 0
    while queue:
        s = queue.popleft()
        for action, nxt in transitions(s, mutation):
            edges += 1
            try:
                check(nxt)
            except InvariantViolation as exc:
                trace = [action]
                cursor = s
                while parents[cursor] is not None:
                    previous, step = parents[cursor]
                    trace.append(step)
                    cursor = previous
                return {"mutation": mutation, "violation": str(exc),
                        "counterexample": list(reversed(trace)),
                        "states_seen": len(parents), "edges_checked": edges}
            if nxt not in parents:
                parents[nxt] = (s, action)
                queue.append(nxt)
    return {"mutation": mutation or "correct_model", "violation": None,
            "states_seen": len(parents), "edges_checked": edges}


def replay(actions: list[str]) -> State:
    s = State()
    for action in actions:
        options = dict(transitions(s))
        if action not in options:
            raise RuntimeError(f"Required scenario is unreachable: {action}")
        s = options[action]
        check(s)
    return s


def main() -> None:
    correct = explore()
    if correct["violation"]:
        raise RuntimeError(correct)
    mutations = [explore(name) for name in (
        "skip_budget_check", "skip_current_authority", "refund_unknown",
        "retry_unknown", "forget_tombstone")]
    if any(not result["violation"] for result in mutations):
        raise RuntimeError("A deliberate protocol defect escaped detection")
    admitted = ["call_1:durable_intent", "call_1:deliver_reserve",
                "call_1:observe_reservation", "call_1:admit"]
    after = replay(admitted + ["revoke_effective", "call_1:send_once"])
    before = replay(admitted[:-1] + ["revoke_effective"])
    unknown = replay(admitted + ["crash_and_classify_durable_attempts",
                                "recover_same_durable_journal"])
    settled = replay(admitted + ["call_1:send_once", "call_1:settle_final_provider_receipt",
                                "call_2:durable_intent", "call_2:deliver_reserve"])
    if after.attempts[0].sends != 1 or any(x == "call_1:admit" for x, _ in transitions(before)):
        raise RuntimeError("Revocation boundary scenario failed")
    if unknown.attempts[0].phase != "UNKNOWN" or used(unknown) != MAX_COST:
        raise RuntimeError("Crash before actual send did not retain full reservation")
    if used(settled) != LIMIT:
        raise RuntimeError("Final settlement did not free only the unused remainder")
    print(json.dumps({"scope": "bounded_reference_model_only", "correct": correct,
                      "detected_mutations": mutations,
                      "explicit_scenarios_passed": 4}, indent=2))


if __name__ == "__main__":
    main()

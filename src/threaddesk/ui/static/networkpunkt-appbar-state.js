/* NetzwerkPunkt appbar 1.0.0 — metadata projection, not authentication. */
export const APPBAR_VERSION = "1.0.0";
export const APP_ORDER = Object.freeze(["kirabridge", "threaddesk", "4allpass", "tollgate"]);
const STATES = ["confirmed", "connecting", "disconnected", "unknown", "error"];
const ref = value => typeof value === "string" && /^[\w.:-]{1,128}$/.test(value);
const ttl = value => Number.isFinite(value) && value > 0 && value <= 15000;
const keys = (value, allowed) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).every(key => allowed.includes(key));

export function createPeerState(initial, { clock = () => performance.now(), wallClock = () => Date.now() } = {}) {
  let expected, generation = 0, serial = 0, pending = null, accepted = null, seq = -1, neutral = "unknown";
  function reset(next = expected) {
    if (!next || !APP_ORDER.includes(next.appId) || ![next.connectionRef, next.peerRef, next.peerEpoch].every(ref)
      || (next.unlockScope && ![next.unlockScope.userRef, next.unlockScope.vaultRef].every(ref))) {
      throw new TypeError("Invalid expected peer binding");
    }
    expected = Object.freeze({ appId: next.appId, connectionRef: next.connectionRef,
      peerRef: next.peerRef, peerEpoch: next.peerEpoch,
      unlockScope: next.unlockScope ? Object.freeze({ userRef: next.unlockScope.userRef, vaultRef: next.unlockScope.vaultRef }) : null });
    generation++; pending = null; accepted = null; seq = -1; neutral = "unknown";
  }
  reset(initial);
  const age = started => {
    const mono = clock() - started.mono, wall = wallClock() - started.wall;
    return mono < 0 || wall < 0 ? Infinity : Math.max(mono, wall);
  };
  function snapshot() {
    if (pending && age(pending) >= 2000) {
      pending = null; accepted = null; neutral = "unknown";
    }
    if (accepted && age(accepted.started) >= accepted.ttlMs) {
      accepted = null; neutral = "unknown";
    }
    if (!accepted) return { state: neutral, vault: "unknown", pulse: false };
    const state = accepted.state;
    const vault = state === "confirmed" && accepted.vault && age(accepted.started) < accepted.vault.ttlMs
      ? accepted.vault.state : "unknown";
    return { state, vault, pulse: expected.appId === "4allpass" && state === "confirmed" && vault === "unlocked" };
  }
  function begin() {
    snapshot();
    if (pending) return pending.ticket; // at most one outstanding check per peer
    if (accepted?.state !== "confirmed") accepted = null;
    const ticket = Object.freeze({ generation, check: ++serial });
    pending = { ticket, mono: clock(), wall: wallClock() };
    if (!accepted) neutral = "connecting";
    return ticket;
  }
  function current(ticket) {
    snapshot();
    return pending && pending.ticket === ticket && ticket.generation === generation;
  }
  function fail(ticket, state = "unknown") {
    if (!current(ticket)) return false;
    pending = null; accepted = null;
    neutral = state === "error" ? "error" : "unknown";
    return true;
  }
  function receive(ticket, value) {
    if (!current(ticket)) return false;
    const started = { mono: pending.mono, wall: pending.wall };
    const valid = keys(value, ["v", "appId", "connectionRef", "peerRef", "peerEpoch", "seq", "state", "ttlMs", "vault"])
      && value.v === 1 && value.appId === expected.appId && value.connectionRef === expected.connectionRef
      && value.peerRef === expected.peerRef && value.peerEpoch === expected.peerEpoch
      && Number.isSafeInteger(value.seq) && value.seq > seq && STATES.includes(value.state) && ttl(value.ttlMs);
    if (!valid) { fail(ticket); return false; }
    let vault = null;
    if (expected.appId === "4allpass" && value.state === "confirmed" && expected.unlockScope) {
      const scope = value.vault;
      if (keys(scope, ["userRef", "vaultRef", "allowed", "state", "ttlMs"]) && scope.allowed === true
        && scope.userRef === expected.unlockScope.userRef && scope.vaultRef === expected.unlockScope.vaultRef
        && ["locked", "unlocked", "unknown"].includes(scope.state) && ttl(scope.ttlMs) && scope.ttlMs <= value.ttlMs) {
        vault = { state: scope.state, ttlMs: scope.ttlMs };
      }
    }
    seq = value.seq; pending = null;
    accepted = { state: value.state, ttlMs: value.ttlMs, started, vault };
    return true;
  }
  function invalidate() { generation++; pending = null; accepted = null; neutral = "unknown"; }
  return Object.freeze({ begin, receive, fail, snapshot, reset, invalidate });
}

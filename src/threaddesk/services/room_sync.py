"""Pair local desks and sync explicitly shared room entries only."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from threaddesk.core.errors import InvalidState, NotFound, SecretRejected
from threaddesk.core.models import Thread, WhiteboardEntry, new_id, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.whiteboard_merge import merge_whiteboard, room_entries

SCHEMA = "threaddesk.room.v1"
ROOMS = "rooms.json"
PEERS = "peers.json"
INVITES = "invites.json"
ROLES = frozenset({"owner", "member", "read_only"})
PUBLISH = frozenset({"owner", "member"})
MAX_BUNDLE_BYTES = 1_000_000
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


class RoomDown(InvalidState):
    pass


def local_base_url(value: str) -> str:
    """Only direct loopback/RFC1918 IPv4 addresses; no redirects or proxies."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InvalidState("room_address")
    try:
        parsed = urlparse(value.strip().rstrip("/"))
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise InvalidState("room_address") from exc
    if (
        parsed.scheme != "http" or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        or host is None or port is None or not 1 <= port <= 65535
    ):
        raise InvalidState("room_address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise InvalidState("room_address") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise InvalidState("room_address")
    if not (address.is_loopback or any(address in network for network in _PRIVATE_NETWORKS)):
        raise InvalidState("room_address")
    return f"http://{address.compressed}:{port}"


class RoomBook:
    def __init__(self, store: Any, transport: Any = None) -> None:
        self.store = store
        self.transport = transport

    def instance_id(self) -> str:
        return ActorRegistry(self.store).instance_id()

    def view(self) -> dict[str, Any]:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        current = _find(state["rooms"], state.get("current_id"))
        peers = self._peers_for(current["id"]) if current else []
        invite = self._open_invite(current["id"]) if current else None
        return {
            "instance_id": self.instance_id(),
            "rooms": [_public_room(room) for room in state["rooms"]],
            "current": _public_room(current) if current else None,
            "peers": [
                {"instance_id": peer["instance_id"], "base_url": peer["base_url"]}
                for peer in peers
            ],
            "state": self._display_state(current),
            "last_sync": (current.get("sync") or {}).get("at", "") if current else "",
            "invite_code": invite["code"] if invite else "",
            "role": self._role(current) if current else "",
        }

    def create_room(self, name: str) -> dict[str, Any]:
        label = _label(name)
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        room = {
            "id": new_id(), "name": label, "created_at": now_iso(),
            "status": "open",
            "members": [{"instance_id": self.instance_id(), "role": "owner"}],
            "sync": {},
        }
        state["rooms"].append(room)
        state["current_id"] = room["id"]
        self._save(ROOMS, state)
        return _public_room(room)

    def select_room(self, room_id: str) -> None:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        if _find(state["rooms"], room_id) is None:
            raise InvalidState("room_missing")
        state["current_id"] = room_id
        self._save(ROOMS, state)

    def invite(self, role: str = "member") -> str:
        room = self._current()
        if self._role(room) != "owner" or role not in {"member", "read_only"}:
            raise InvalidState("room_forbidden")
        state = self._load(INVITES, {"version": 1, "invites": []})
        state["invites"] = [
            item for item in state["invites"] if item.get("room_id") != room["id"]
        ]
        code = secrets.token_urlsafe(18)
        state["invites"].append({
            "code": code, "room_id": room["id"], "role": role, "created_at": now_iso(),
        })
        self._save(INVITES, state)
        return code

    def accept(self, code: str, instance_id: str, base_url: str) -> dict[str, Any]:
        """Redeem one invitation. Never include the invitation in an error."""
        if not isinstance(code, str) or not isinstance(instance_id, str):
            raise InvalidState("room_forbidden")
        address = local_base_url(base_url)
        guest = _ref(instance_id)
        if guest == self.instance_id():
            raise InvalidState("room_forbidden")
        invites = self._load(INVITES, {"version": 1, "invites": []})
        match = next((item for item in invites["invites"] if _same(item.get("code", ""), code)), None)
        if match is None or match.get("role") not in {"member", "read_only"}:
            raise InvalidState("room_forbidden")
        rooms = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        room = _find(rooms["rooms"], match["room_id"])
        if room is None or self._role(room) != "owner":
            raise InvalidState("room_forbidden")
        _add_member(room, guest, match["role"])
        token = secrets.token_urlsafe(24)
        self._save(ROOMS, rooms)
        invites["invites"] = [item for item in invites["invites"] if item is not match]
        self._save(INVITES, invites)
        self._remember_peer(guest, address, room["id"], token)
        return {
            "ok": True, "token": token, "instance_id": self.instance_id(),
            "room": _public_room(room),
        }

    def join(self, code: str, peer_base: str, own_base: str) -> dict[str, Any]:
        peer_url, own_url = local_base_url(peer_base), local_base_url(own_base)
        if peer_url == own_url:
            raise InvalidState("room_address")
        try:
            result = self._post(peer_url, "/api/rooms/pair", {
                "code": code, "instance_id": self.instance_id(), "base_url": own_url,
            }, token="")
        except RoomDown as exc:
            raise InvalidState("room_offline") from exc
        if result.get("ok") is not True or not isinstance(result.get("room"), dict):
            raise InvalidState("room_forbidden")
        room, token, remote = result["room"], result.get("token"), result.get("instance_id")
        if not isinstance(token, str) or not token or not isinstance(remote, str):
            raise InvalidState("room_forbidden")
        remote = _ref(remote)
        if remote == self.instance_id() or not _safe_id(room.get("id")):
            raise InvalidState("room_forbidden")
        members = room.get("members")
        if not isinstance(members, list) or not all(isinstance(item, dict) for item in members):
            raise InvalidState("room_forbidden")
        if _member_role(room, remote) != "owner" or _member_role(room, self.instance_id()) not in {"member", "read_only"}:
            raise InvalidState("room_forbidden")
        self._remember_room(room)
        self._remember_peer(remote, peer_url, room["id"], token)
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        state["current_id"] = room["id"]
        self._save(ROOMS, state)
        return _public_room(room)

    def sync(self) -> dict[str, Any]:
        room = self._current()
        peers = self._peers_for(room["id"])
        if not peers:
            self._mark(room["id"], "not_connected", 0)
            return {"ok": False, "state": "not_connected", "conflicts": 0}
        conflicts = 0
        try:
            for peer in peers:
                remote = self._post(peer["base_url"], "/api/rooms/pull", {
                    "room_id": room["id"],
                }, token=peer["token"])
                # A valid connection is not authority for another room or sender.
                if remote.get("room_id") != room["id"] or remote.get("instance_id") != peer["instance_id"]:
                    raise InvalidState("room_forbidden")
                sender_role = _member_role(self._require(room["id"]), peer["instance_id"])
                if sender_role not in ROLES or (sender_role not in PUBLISH and remote.get("entries")):
                    raise InvalidState("room_forbidden")
                report = self.apply_bundle(remote)
                conflicts += int(report["conflicts"])
                if self._role(self._require(room["id"])) in PUBLISH:
                    acknowledgement = self._post(
                        peer["base_url"], "/api/rooms/push", self.export_bundle(room["id"]),
                        token=peer["token"],
                    )
                    if acknowledgement.get("ok") is not True:
                        raise InvalidState("room_bundle")
                    conflicts += int(acknowledgement.get("conflicts", 0))
        except (RoomDown, InvalidState, OSError, TypeError, ValueError):
            self._mark(room["id"], "peer_down", conflicts)
            return {"ok": False, "state": "peer_down", "conflicts": conflicts}
        state = "conflict_kept" if conflicts else "synced"
        self._mark(room["id"], state, conflicts)
        return {"ok": True, "state": state, "conflicts": conflicts}

    def export_bundle(self, room_id: str) -> dict[str, Any]:
        room = self._require(room_id)
        if self._role(room) not in PUBLISH:
            return _empty_bundle(room_id, self.instance_id())
        entries, threads = [], []
        seen: set[str] = set()
        for thread in self.store.list_threads(include_archived=True):
            shared = room_entries(self.store.list_whiteboard(thread.id), room_id)
            if not shared:
                continue
            entries.extend(item.to_dict() for item in shared)
            if thread.id not in seen:
                threads.append({"id": thread.id, "title": thread.title})
                seen.add(thread.id)
        return {
            "schema": SCHEMA, "room_id": room_id, "instance_id": self.instance_id(),
            "entries": entries, "threads": threads,
        }

    def apply_bundle(self, bundle: Any) -> dict[str, int]:
        """Validate every row before changing any thread or whiteboard."""
        if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
            raise InvalidState("room_bundle")
        room_id = bundle.get("room_id")
        if not _safe_id(room_id):
            raise InvalidState("room_bundle")
        if self._role(self._require(room_id)) not in ROLES:
            raise InvalidState("room_forbidden")
        rows, raw_titles = bundle.get("entries", []), bundle.get("threads", [])
        if not isinstance(rows, list) or not isinstance(raw_titles, list):
            raise InvalidState("room_bundle")
        try:
            encoded = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise InvalidState("room_bundle") from exc
        if len(encoded) > MAX_BUNDLE_BYTES:
            raise InvalidState("room_bundle")
        titles: dict[str, str] = {}
        for item in raw_titles:
            if not isinstance(item, dict) or not _safe_id(item.get("id")) or not isinstance(item.get("title", ""), str):
                raise InvalidState("room_bundle")
            titles[item["id"]] = item.get("title", "")
        incoming: list[WhiteboardEntry] = []
        for raw in rows:
            if not isinstance(raw, dict) or raw.get("room_id") != room_id:
                raise InvalidState("room_bundle")
            if not _safe_id(raw.get("thread_id")) or not _safe_id(raw.get("id")):
                raise InvalidState("room_bundle")
            if not isinstance(raw.get("content"), str) or not isinstance(raw.get("metadata", {}), dict):
                raise InvalidState("room_bundle")
            try:
                entry = WhiteboardEntry.from_dict(raw)
                reject_secrets(entry.content)
            except (KeyError, TypeError, ValueError, SecretRejected, InvalidState) as exc:
                raise InvalidState("room_bundle") from exc
            if entry.room_id != room_id:
                raise InvalidState("room_bundle")
            incoming.append(entry)
        for entry in incoming:
            self._shell(entry.thread_id, titles.get(entry.thread_id, ""))
        if not incoming:
            return {"added": 0, "kept": 0, "conflicts": 0}
        return merge_whiteboard(self.store, incoming)

    def serve_pull(self, instance_id: str, token: str, room_id: str) -> dict[str, Any]:
        self._trusted(instance_id, token, room_id)
        return self.export_bundle(room_id)

    def serve_push(self, instance_id: str, token: str, bundle: Any) -> dict[str, Any]:
        if not isinstance(bundle, dict):
            raise InvalidState("room_forbidden")
        room_id = bundle.get("room_id")
        if not isinstance(room_id, str) or bundle.get("instance_id") != instance_id:
            raise InvalidState("room_forbidden")
        self._trusted(instance_id, token, room_id)
        if _member_role(self._require(room_id), instance_id) not in PUBLISH:
            raise InvalidState("room_forbidden")
        report = self.apply_bundle(bundle)
        return {"ok": True, "added": report["added"], "conflicts": report["conflicts"]}

    def _trusted(self, instance_id: str, token: str, room_id: str) -> dict[str, Any]:
        if not isinstance(instance_id, str) or not isinstance(token, str):
            raise InvalidState("room_forbidden")
        if _member_role(self._require(room_id), instance_id) not in ROLES:
            raise InvalidState("room_forbidden")
        for peer in self._peers_for(room_id):
            if peer["instance_id"] == instance_id and _same(peer.get("token", ""), token):
                return peer
        raise InvalidState("room_forbidden")

    def _post(self, base_url: str, path: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
        url = local_base_url(base_url) + path
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-ThreadDesk-Instance": self.instance_id(), "X-ThreadDesk-Token": token,
        }
        result = self.transport(url, payload, headers) if self.transport is not None else _http_json(url, payload, headers)
        if not isinstance(result, dict):
            raise InvalidState("room_bundle")
        return result

    def _shell(self, thread_id: str, title: str) -> None:
        try:
            self.store.get_thread(thread_id)
        except NotFound:
            stamp = now_iso()
            try:
                label = _label(title or "Raum")
            except (InvalidState, SecretRejected):
                label = "Raum"
            self.store.save_thread(Thread(id=thread_id, title=label, created_at=stamp, updated_at=stamp))

    def _current(self) -> dict[str, Any]:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        room = _find(state["rooms"], state.get("current_id"))
        if room is None:
            raise InvalidState("room_missing")
        return room

    def _require(self, room_id: str) -> dict[str, Any]:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        room = _find(state["rooms"], room_id)
        if room is None:
            raise InvalidState("room_missing")
        return room

    def _role(self, room: dict[str, Any] | None) -> str:
        return _member_role(room, self.instance_id()) if room else ""

    def _open_invite(self, room_id: str) -> dict[str, Any] | None:
        state = self._load(INVITES, {"version": 1, "invites": []})
        return next((item for item in state["invites"] if item.get("room_id") == room_id), None)

    def _peers_for(self, room_id: str) -> list[dict[str, Any]]:
        state = self._load(PEERS, {"version": 1, "peers": []})
        return [dict(item) for item in state["peers"] if item.get("room_id") == room_id]

    def _remember_peer(self, instance_id: str, base_url: str, room_id: str, token: str) -> None:
        state = self._load(PEERS, {"version": 1, "peers": []})
        state["peers"] = [
            item for item in state["peers"]
            if not (item.get("instance_id") == instance_id and item.get("room_id") == room_id)
        ]
        state["peers"].append({
            "instance_id": instance_id, "base_url": base_url, "room_id": room_id, "token": token,
        })
        self._save(PEERS, state)

    def _remember_room(self, room: dict[str, Any]) -> None:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        current = _find(state["rooms"], room.get("id"))
        if current is None:
            state["rooms"].append({
                "id": room["id"], "name": _label(str(room.get("name") or "Raum")),
                "created_at": room.get("created_at") or now_iso(), "status": "open",
                "members": list(room.get("members") or []), "sync": {},
            })
        else:
            known = {item["instance_id"] for item in current["members"]}
            for member in room.get("members") or []:
                if member.get("instance_id") not in known and member.get("role") in ROLES:
                    current["members"].append({"instance_id": member["instance_id"], "role": member["role"]})
        self._save(ROOMS, state)

    def _mark(self, room_id: str, sync_state: str, conflicts: int) -> None:
        state = self._load(ROOMS, {"version": 1, "current_id": "", "rooms": []})
        room = _find(state["rooms"], room_id)
        if room is None:
            return
        previous = room.get("sync") or {}
        room["sync"] = {
            "at": now_iso() if sync_state in {"synced", "conflict_kept"} else previous.get("at", ""),
            "state": sync_state, "conflicts": conflicts, "digest": self._digest(room_id),
        }
        self._save(ROOMS, state)

    def _display_state(self, room: dict[str, Any] | None) -> str:
        if room is None or not self._peers_for(room["id"]):
            return "not_connected"
        sync = room.get("sync") or {}
        stored = sync.get("state") or "connected"
        if stored == "synced" and sync.get("digest") != self._digest(room["id"]):
            return "changes"
        return stored

    def _digest(self, room_id: str) -> str:
        rows = []
        for thread in self.store.list_threads(include_archived=True):
            for entry in room_entries(self.store.list_whiteboard(thread.id), room_id):
                row = entry.to_dict()
                row.pop("ordinal", None)
                rows.append(row)
        rows.sort(key=lambda row: (row["thread_id"], row["id"]))
        encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _load(self, name: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.store.artifact_path(name)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return json.loads(json.dumps(default))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            # Corruption must not turn an existing room into an empty new state.
            raise InvalidState("room_state") from exc
        collection = {ROOMS: "rooms", PEERS: "peers", INVITES: "invites"}[name]
        if (
            not isinstance(value, dict) or value.get("version") != 1
            or not isinstance(value.get(collection), list)
            or not all(isinstance(item, dict) for item in value[collection])
        ):
            raise InvalidState("room_state")
        return value

    def _save(self, name: str, value: dict[str, Any]) -> None:
        self.store.write_json_artifact(name, value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    if len(body) > MAX_BUNDLE_BYTES:
        raise InvalidState("room_bundle")
    request = Request(url, data=body, headers=headers, method="POST")
    # Environment proxies and redirects must never receive room credentials.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=2.0) as response:
            raw = response.read(MAX_BUNDLE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise InvalidState("room_forbidden") from exc
        raise RoomDown("room_offline") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RoomDown("room_offline") from exc
    if len(raw) > MAX_BUNDLE_BYTES:
        raise InvalidState("room_bundle")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidState("room_bundle") from exc
    if not isinstance(value, dict):
        raise InvalidState("room_bundle")
    if value.get("ok") is False:
        raise InvalidState("room_forbidden")
    return value


def _empty_bundle(room_id: str, instance_id: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "room_id": room_id, "instance_id": instance_id, "entries": [], "threads": []}


def _public_room(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": room["id"], "name": room["name"], "created_at": room["created_at"], "status": room["status"],
        "members": [
            {"instance_id": item["instance_id"], "role": item["role"]}
            for item in room.get("members") or [] if item.get("role") in ROLES
        ],
    }


def _find(rooms: list[dict[str, Any]], room_id: str | None) -> dict[str, Any] | None:
    if not room_id:
        return None
    return next((room for room in rooms if room.get("id") == room_id), None)


def _add_member(room: dict[str, Any], instance_id: str, role: str) -> None:
    if role not in ROLES:
        raise InvalidState("room_forbidden")
    for member in room["members"]:
        if member["instance_id"] == instance_id:
            if member["role"] != "owner":
                member["role"] = role
            return
    room["members"].append({"instance_id": instance_id, "role": role})


def _member_role(room: dict[str, Any], instance_id: str) -> str:
    for member in room.get("members") or []:
        if member.get("instance_id") == instance_id:
            return str(member.get("role") or "")
    return ""


def _label(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("room_name")
    value = reject_secrets(value).strip()
    if not value or len(value) > 80:
        raise InvalidState("room_name")
    return value


def _ref(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("room_forbidden")
    value = value.strip()
    if not _safe_id(value):
        raise InvalidState("room_forbidden")
    return value


def _safe_id(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 80 and value == value.strip()
        and "/" not in value and "\\" not in value and value not in {".", ".."}
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _same(left: str, right: str) -> bool:
    if not isinstance(left, str) or not isinstance(right, str) or not left or len(left) != len(right):
        return False
    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except UnicodeError:
        return False

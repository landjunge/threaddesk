"""Operator-provisioned random credentials; no caller-selected filesystem scope."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path

USER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SESSION_SECONDS = 8 * 3600


def private_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if path.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("Private directory required")
    path.chmod(0o700)
    return path


def _load(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Credential file must be a regular private file")
    if info.st_mode & 0o077:
        raise ValueError("Credential file permissions must be 0600")
    return json.loads(path.read_text(encoding="utf-8"))


def provision(data_dir: Path, user: str) -> str:
    if not USER.fullmatch(user):
        raise ValueError("User must match [a-z0-9][a-z0-9_-]{0,63}")
    root = private_directory(data_dir)
    # Serialize provisioning with the same cross-platform advisory lock as core.
    from threaddesk.storage.json_store import _lock_exclusive, _unlock
    lock_path = root / "credentials.lock"
    if lock_path.is_symlink():
        raise ValueError("Unsafe credential lock")
    with lock_path.open("a+b") as lock:
        os.chmod(lock_path, 0o600)
        _lock_exclusive(lock)
        try:
            path = root / "users.json"
            config = _load(path) if path.exists() else {"users": {}, "session_key": secrets.token_hex(32)}
            if user in config["users"]:
                raise ValueError("User exists; credentials were not replaced")
            token = secrets.token_urlsafe(32)
            config["users"][user] = hashlib.sha256(token.encode()).hexdigest()
            temp = root / (".users-" + secrets.token_hex(12))
            try:
                fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(config, out)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            private_directory(root / "users")
            private_directory(root / "users" / user)
            return token
        finally:
            _unlock(lock)


class Credentials:
    def __init__(self, data_dir: Path):
        self.root = private_directory(data_dir)
        config = _load(self.root / "users.json")
        self.users = config["users"]
        if not self.users or any(not USER.fullmatch(u) for u in self.users):
            raise ValueError("Provision a valid user first")
        self.key = bytes.fromhex(config["session_key"])

    def authenticate(self, token: str) -> str | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        result = None
        for user, expected in self.users.items():
            if hmac.compare_digest(digest, expected):
                result = user
        return result

    def _sign(self, text: str) -> str:
        return hmac.new(self.key, text.encode(), hashlib.sha256).hexdigest()

    def session(self, user: str) -> str:
        body = f"{user}.{int(time.time())}.{secrets.token_hex(16)}"
        return body + "." + self._sign(body)

    def session_user(self, value: str) -> str | None:
        try:
            user, stamp, nonce, signature = value.split(".")
            if user not in self.users or len(nonce) != 32:
                return None
            if not 0 <= time.time() - int(stamp) <= SESSION_SECONDS:
                return None
            return user if hmac.compare_digest(signature, self._sign(f"{user}.{stamp}.{nonce}")) else None
        except (ValueError, TypeError):
            return None

    def csrf(self, session: str) -> str:
        return self._sign("csrf:" + session)

    def user_root(self, user: str) -> Path:
        if user not in self.users:
            raise ValueError("Unknown user")
        return private_directory(private_directory(self.root / "users") / user)

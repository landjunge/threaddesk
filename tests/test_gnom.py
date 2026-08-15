import shlex
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import GateBlocked, InvalidState
from threaddesk.services.gnom_bridge import command_for, hub_url
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_gnom_brainstorm_does_not_send(svc: ThreadService) -> None:
    svc.create("Desk", "Kontext halten")
    svc.set_note("nächster Schritt: Handoff")
    packet = svc.gnom()
    assert packet["kind"] == "threaddesk.gnom"
    assert packet["hub"] == "gnom-hub-v1"
    assert packet["mode"] == "brainstorm"
    assert packet["ran"] is False
    assert Path(packet["path"]).is_file()
    assert Path(packet["chat_path"]).is_file()
    assert packet["prompt"].startswith("Modus: Send")
    assert "@bs" not in packet["prompt"]
    assert "/api/execute" not in packet["command"]
    assert "curl" in packet["command"]
    assert "/api/chat" in packet["command"]
    assert "127.0.0.1:8080" in packet["command"]
    chat = Path(packet["chat_path"]).read_text(encoding="utf-8")
    assert '"text"' in chat
    assert "sender" not in chat
    assert "Handoff" in chat


def test_gnom_execute_still_does_not_send(svc: ThreadService) -> None:
    svc.create("Go")
    svc.gate_set(cooldown_seconds=0)
    packet = svc.gnom(mode="execute")
    assert packet["mode"] == "execute"
    assert packet["ran"] is False
    assert "/api/chat" in packet["command"]
    assert "/api/execute" in packet["command"]
    assert packet["chat"]["text"].startswith("Modus: Execute")
    svc.gate_freeze(True)
    brain = svc.gnom(mode="brainstorm")
    assert brain["ran"] is False
    assert "/api/execute" not in brain["command"]
    with pytest.raises(GateBlocked):
        svc.gnom(mode="execute")


def test_mcp_export_gnom_and_localhost_only(svc: ThreadService, monkeypatch: pytest.MonkeyPatch) -> None:
    svc.create("Via MCP")
    got = McpBridge(svc).call("export_gnom", {"mode": "brainstorm"})
    assert got["ok"]
    assert got["result"]["ran"] is False
    names = [t["name"] for t in McpBridge(svc).list_tools()]
    assert "export_gnom" in names
    assert "delete" not in names
    monkeypatch.setenv("GNOM_HUB_URL", "https://example.com")
    with pytest.raises(InvalidState):
        hub_url()
    monkeypatch.setenv("GNOM_HUB_URL", "http://127.0.0.1:3012")
    assert hub_url() == "http://127.0.0.1:3012"
    import threaddesk.services.gnom_bridge as wrap

    source = Path(wrap.__file__).read_text(encoding="utf-8")
    assert "import gnom_hub" not in source
    assert "from gnom_hub" not in source
    assert "urlopen" not in source
    assert "requests" not in source


# --- GNOM_HUB_URL must really mean localhost -----------------------------------

LOOKALIKE_URLS = [
    "http://127.0.0.1.evil.com",
    "http://127.0.0.1.evil.com/api/chat",
    "http://localhost.attacker.io/x",
    "http://127.0.0.1@evil.com",
    "http://evil.com#127.0.0.1",
    "http://evil.com/?h=http://127.0.0.1",
    "https://127.0.0.1:8080",
    "http://127.1.2.3",
    "http://10.0.0.1",
    "http://[::2]:8080",
    "http://127.0.0.1:notaport",
    "file:///etc/passwd",
    "127.0.0.1:8080",
]


@pytest.mark.parametrize("url", LOOKALIKE_URLS)
def test_hub_url_rejects_lookalike_hosts(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GNOM_HUB_URL", url)
    with pytest.raises(InvalidState):
        hub_url()


@pytest.mark.parametrize(
    ("given", "want"),
    [
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://127.0.0.1:8080/", "http://127.0.0.1:8080"),
        ("  http://localhost:3012  ", "http://localhost:3012"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_hub_url_accepts_localhost_forms(
    given: str, want: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GNOM_HUB_URL", given)
    assert hub_url() == want


def test_hub_url_default_is_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GNOM_HUB_URL", raising=False)
    assert hub_url() == "http://127.0.0.1:8080"


def test_command_quotes_awkward_paths() -> None:
    """A home directory with spaces or metacharacters must not break the command."""
    cmd = command_for(Path("/tmp/my desk/gnom-chat.json"), "brainstorm", url="http://127.0.0.1:8080")
    assert "--data-binary '@/tmp/my desk/gnom-chat.json'" in cmd
    # The shell must hand curl exactly one argument, metacharacters included.
    evil = command_for(Path("/tmp/$(touch pwned)/c.json"), "brainstorm", url="http://127.0.0.1:8080")
    assert "--data-binary '@/tmp/$(touch pwned)/c.json'" in evil
    assert shlex.split(evil)[-1] == "@/tmp/$(touch pwned)/c.json"

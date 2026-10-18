"""Record real local UI evidence using existing Desk/browser helpers and synthetic data."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from playwright.sync_api import expect, sync_playwright
from test_desk_browser import Desk, _launch, _open_section

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.services.return_contract import build
from threaddesk.storage.json_store import JsonStore

OUT = (
    ROOT
    / ".runtime/design-20261018"
    / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
)
OUT.mkdir(parents=True)


def run():
    with TemporaryDirectory(prefix="threaddesk-design-synthetic-") as folder:
        svc = ThreadService(JsonStore(Path(folder)))
        thread = svc.create(
            "Synthetic knowledge and review context",
            "One saved thread; no agent execution.",
        )
        svc.set_note("Synthetic note remains local.\n" * 25)
        result = McpBridge(svc).call(
            "knowledge_manage",
            {
                "operation_id": "synthetic-question",
                "id": thread.id,
                "expected_revision": svc.get(thread.id).revision,
                "action": "record",
                "data": {
                    "kind": "question",
                    "title": "Which documented step comes next?",
                    "details": "A stored question is context, never an execution instruction.",
                    "source_ref": "Synthetic example conversation",
                    "source_revision": "message-1",
                },
            },
        )
        assert result["ok"]
        svc.receive_return(
            build(
                return_id="synthetic-return",
                handoff_id="synthetic-handoff",
                handoff_revision=1,
                thread_id=thread.id,
                task_id=thread.id + ":task",
                worker="codex",
                run_id="synthetic-run",
                result="Synthetic result delivered; review remains open.",
            )
        )
        svc.append_whiteboard(
            thread.id,
            actor="Synthetic operator",
            actor_type="system",
            entry_type="progress",
            content="Synthetic stored progress",
            metadata={"next_step": "Review existing result; no new job."},
        )
        desk = Desk(Path(folder))
        url = desk.start()
        try:
            with sync_playwright() as play:
                browser = _launch(play)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 900}, reduced_motion="reduce"
                )
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                for language in ("de", "en"):
                    page.goto(url + "/lang/" + language, wait_until="networkidle")
                    _open_section(page, "stand")
                    expect(
                        page.locator('[data-return-review="unverified"]')
                    ).to_have_count(1)
                    page.screenshot(path=str(OUT / ("desk-" + language + ".png")))
                    badge = page.locator('[data-return-review="unverified"]')
                    badge.scroll_into_view_if_needed()
                    expect(badge).to_be_visible()
                    page.screenshot(path=str(OUT / ("review-" + language + ".png")))
                    page.goto(url + "/knowledge", wait_until="networkidle")
                    expect(page.locator(".node-row")).to_have_count(1)
                    expect(page.locator(".node-row")).to_contain_text(
                        "Knotenrevision" if language == "de" else "node revision"
                    )
                    expect(page.locator(".node-row")).to_contain_text(
                        "nicht extern verifiziert"
                        if language == "de"
                        else "not externally verified"
                    )
                    assert page.locator(".node-main").evaluate("""el => {
                      const right=el.getBoundingClientRect().right;
                      return [...el.children].every(child => {
                        const range=document.createRange();range.selectNodeContents(child);
                        return [...range.getClientRects()].every(r => r.right <= right+1);
                      });
                    }""")
                    page.screenshot(path=str(OUT / ("knowledge-" + language + ".png")))
                page.goto(url, wait_until="networkidle")
                page.set_viewport_size({"width": 1024, "height": 700})
                page.evaluate("() => {document.documentElement.style.zoom = '1.25';}")
                _open_section(page, "packet")
                control = page.locator('details[data-disclosure="packet"] .btn').last
                control.focus()
                assert control.evaluate(
                    "el => { const r=el.getBoundingClientRect(); return r.left>=0 && r.top>=0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1; }"
                )
                assert page.locator(".shell").evaluate("el => el.clientWidth") >= 1180
                page.screenshot(path=str(OUT / "small-css-zoom125-en.png"))
                assert not errors, errors
                version = browser.version
                browser.close()
        finally:
            desk.stop()
        return {
            "status": "passed",
            "browser": version,
            "scope": "real isolated local browser; synthetic existing graph/return/whiteboard records; no agent/real users/model calls",
            "screens": "DE/EN desk and knowledge; 1024x700 viewport with explicit CSS zoom1.25 and focused reachable tool",
            "limits": "CSS zoom is a bounded emulation, not native desktop or every browser zoom mode; no live ChatGPT acceptance",
            "page_errors": errors,
            "assets": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / "src/threaddesk/ui/static").glob("*")
                if p.suffix in {".js", ".css"}
            },
        }


if __name__ == "__main__":
    try:
        value = run()
    except BaseException as error:
        value = {
            "status": "failed",
            "error": type(error).__name__,
            "detail": str(error)[:2000],
        }
        (OUT / "checks.json").write_text(json.dumps(value, indent=2))
        print(json.dumps({**value, "evidence": str(OUT)}))
        raise
    (OUT / "checks.json").write_text(json.dumps(value, indent=2))
    print(json.dumps({**value, "evidence": str(OUT)}))

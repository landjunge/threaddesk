"""Return decisions and uncertain storage stay visible in the existing desk."""

from pathlib import Path

from http_ui_client import choose_language

import pytest
from playwright.sync_api import expect, sync_playwright
from test_desk_browser import Desk, _launch, _open_section

from threaddesk.api.service import ThreadService
from threaddesk.services.return_contract import build
from threaddesk.storage.json_store import JsonStore


@pytest.mark.parametrize("language", ["de", "en"])
def test_return_decision_and_unknown_scope_are_visible_without_foreign_content(
    tmp_path: Path, language
):
    svc = ThreadService(JsonStore(tmp_path))
    current = svc.create("Synthetic review context")
    foreign = svc.create("Other synthetic thread")

    def delivery(identity, thread_id, result):
        return build(
            return_id=identity,
            handoff_id="handoff-synthetic",
            handoff_revision=1,
            thread_id=thread_id,
            task_id=thread_id + ":task",
            worker="codex",
            run_id="run-synthetic",
            result=result,
        )

    svc.receive_return(
        delivery("own-return", current.id, "Synthetic delivery <img src=x>")
    )
    svc.receive_return(
        delivery("foreign-return", foreign.id, "Foreign result must not appear")
    )
    svc.decide_return("foreign-return", "accepted", "Foreign decision must not appear")
    svc.append_whiteboard(
        current.id,
        actor="Synthetic",
        actor_type="system",
        entry_type="result",
        content="Untrusted cross-reference",
        metadata={"return_id": "foreign-return"},
    )
    svc.append_whiteboard(
        current.id,
        actor="Synthetic",
        actor_type="system",
        entry_type="problem",
        content="Uncertain synthetic execution",
        metadata={"status": "unknown"},
    )
    svc.switch(current.id)
    desk = Desk(tmp_path)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = _launch(play)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            choose_language(page, url, language)
            expect(page.locator('[data-return-review="unverified"]')).to_have_count(1)
            expect(page.locator('[data-return-review="unknown"]')).to_have_count(2)
            assert (
                "Foreign result must not appear"
                not in page.locator("body").inner_text()
            )
            assert (
                "Foreign decision must not appear"
                not in page.locator("body").inner_text()
            )
            assert page.locator(".whiteboard-log img").count() == 0
            boundary = (
                "Gesamtauftrag nicht automatisch"
                if language == "de"
                else "does not automatically accept the overall assignment"
            )
            expect(page.locator(".whiteboard-log .muted").first).to_contain_text(
                boundary
            )
            svc.decide_return("own-return", "rework", "Synthetic missing check")
            page.reload(wait_until="networkidle")
            expect(page.locator('[data-return-review="rework"]')).to_have_count(2)
            expect(page.locator('[data-return-review="unverified"]')).to_have_count(0)
            browser.close()
    finally:
        desk.stop()


@pytest.mark.parametrize("language", ["de", "en"])
def test_lost_accepted_note_response_stays_uncertain_without_post_retry(
    tmp_path: Path, language
):
    svc = ThreadService(JsonStore(tmp_path))
    thread = svc.create("Synthetic uncertain note")
    desk = Desk(tmp_path)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = _launch(play)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            choose_language(page, url, language)
            _open_section(page, "notes")
            notes = page.locator('#notes textarea[name="text"]')
            notes.fill("Synthetic text accepted exactly once")
            expect(page.locator("#request-state")).to_contain_text(
                "noch nicht gespeichert" if language == "de" else "not been saved"
            )
            posts = []

            def accept_then_disconnect(route):
                posts.append(route.request.post_data)
                route.fetch()
                route.abort()

            page.route(url + "/threads/" + thread.id + "/note", accept_then_disconnect)
            page.locator('#notes form[hx-post$="/note"] button[type="submit"]').click()
            expect(page.locator('#request-state[role="alert"]')).to_contain_text(
                "Keine verlässliche Speicherbestätigung"
                if language == "de"
                else "No reliable storage confirmation"
            )
            page.wait_for_timeout(
                1200
            )  # No automatic write retry or refresh is scheduled.
            assert len(posts) == 1
            assert (
                ThreadService(JsonStore(tmp_path)).get(thread.id).context.notes
                == "Synthetic text accepted exactly once"
            )
            expect(notes).to_have_value("Synthetic text accepted exactly once")
            expect(
                page.locator('#workspace [role="status"]:visible')
            ).to_have_count(0)
            browser.close()
    finally:
        desk.stop()

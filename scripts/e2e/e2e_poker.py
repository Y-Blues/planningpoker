"""End-to-end: the server (run.sh, memory storage) and four browsers in one room -- create, join by nickname, a stolen
nickname refused, hidden votes, reveal (average, nearest card, min, max), revote, next task, recap, remove, lock, an
unknown room, an absent host's handover; the first load's size measured; screenshots.
    PYTHON=... uv run --no-project --with playwright python scripts/e2e/e2e_poker.py <screenshot dir>
Starts and stops its own server (POKER_E2E_PORT, default 8197), or tests POKER_E2E_BASE (a deployment, its prefix
included: http://localhost:8096/planningpoker/)."""

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(os.environ.get("POKER_E2E_PORT", "8197"))
BASE = os.environ.get("POKER_E2E_BASE") or f"http://localhost:{PORT}/"
BOOT, T = 180000, 20000
ABSENT = 25  # the server's host_absent_seconds for the run (the page pings every 15 s)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def start_server():
    log = open(os.path.join(SHOTS, "server.log"), "w")
    server = subprocess.Popen(["./run.sh"], cwd=ROOT, env={**os.environ, "HTTP_PORT": str(PORT), "POKER_HOST_ABSENT_SECONDS": str(ABSENT)}, stdout=log,
                              stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(300):
        try:
            with urllib.request.urlopen(BASE + "api/services/__remote_capabilities__", timeout=2) as response:
                if response.status == 200:
                    return server
        except Exception:
            time.sleep(1)
    raise SystemExit("the server did not start: see server.log")


def open_page(browser, url, **options):
    context = browser.new_context(locale="fr-FR", **options)
    page = context.new_page()
    page.on("console", lambda message: message.type == "error" and print("  console:", message.text[:200]))
    page.goto(url)
    page.wait_for_selector(".pp-app", timeout=BOOT)
    return page


def enter(page, nickname):
    page.fill("#pp-nickname", nickname)
    page.click(".pp-welcome button[type=submit]")


def seat_faces(page):
    return page.eval_on_selector_all(".pp-seat .pp-card", "cards => cards.map(c => c.className.split(' ')[1])")


def main():
    server = None if os.environ.get("POKER_E2E_BASE") else start_server()
    try:
        with sync_playwright() as playwright:
            run(playwright)
    finally:
        if server is not None:
            os.killpg(server.pid, signal.SIGTERM)
            server.wait(timeout=30)
    print(f"{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


def run(playwright):
    browser = playwright.chromium.launch()
    # first load, measured: everything the page downloads until it is drawn
    sizes = {"own": 0, "cdn": 0}
    context = browser.new_context(locale="fr-FR", permissions=["clipboard-read", "clipboard-write"])
    alice = context.new_page()
    alice.on("console", lambda message: message.type == "error" and print("  console:", message.text[:300]))

    def counted(request):
        try:
            size = request.sizes()["responseBodySize"]
        except Exception:
            return
        sizes["own" if request.url.startswith(BASE) else "cdn"] += size

    alice.on("requestfinished", counted)
    started = time.time()
    alice.goto(BASE)
    alice.wait_for_selector(".pp-welcome:not([hidden])", timeout=BOOT)
    boot = time.time() - started
    alice.wait_for_timeout(1000)
    check("first load measured", sizes["own"] > 0, f"own server {sizes['own'] / 1e6:.2f} MB, Pyodide CDN "
          f"{sizes['cdn'] / 1e6:.2f} MB, drawn after {boot:.1f} s")
    with open(os.path.join(SHOTS, "first_load.json"), "w") as file:
        json.dump({**sizes, "seconds": round(boot, 1)}, file)
    check("noindex on the page", alice.locator('meta[name="robots"]').get_attribute("content") == "noindex, nofollow")
    with urllib.request.urlopen(BASE + "robots.txt") as response:
        check("robots.txt disallows everything", "Disallow: /" in response.read().decode())
    alice.screenshot(path=os.path.join(SHOTS, "1_welcome.png"), full_page=True)

    check("footer credits iPOPO and YCappuccino", alice.locator(".pp-footer a[target=_blank][rel=noopener]").count() == 2
          and "Propulsé par iPOPO et YCappuccino" in alice.inner_text(".pp-footer"))
    alice.click(".pp-welcome .pp-avatar-choice >> nth=2")
    alice.wait_for_selector(".pp-welcome .pp-avatar-choice[aria-pressed=true]", timeout=T)
    check("an avatar is selected on the join form", alice.locator(".pp-welcome .pp-avatar-choice[aria-pressed=true]").count() == 1)
    alice.screenshot(path=os.path.join(SHOTS, "1b_avatar_picker.png"), full_page=True)
    avatar = alice.inner_text(".pp-welcome .pp-avatar-choice >> nth=2")

    enter(alice, "Alice")
    alice.wait_for_selector(".pp-room:not([hidden])", timeout=T)
    room = alice.evaluate("location.hash").lstrip("#")
    check("a room is created, its id unguessable", len(room) >= 32, room[:6] + "…")
    check("the creator hosts it", "animateur" in alice.inner_text(".pp-me"))
    alice.click("text=Copier le lien")
    alice.wait_for_selector("text=Lien copié ✓", timeout=T)
    check("the room's link is copied", alice.evaluate("navigator.clipboard.readText()") == BASE + "#" + room)
    alice.fill("#pp-task-number", "101")
    alice.click(".pp-task-form button")
    alice.wait_for_selector("text=Tâche 101", timeout=T)

    link = BASE + "#" + room
    bob = open_page(browser, link)
    bob.wait_for_selector("text=Rejoindre la salle", timeout=T)
    enter(bob, "Bob")
    bob.wait_for_selector(".pp-room:not([hidden])", timeout=T)
    chloe = open_page(browser, link, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    enter(chloe, "Chloé")
    chloe.wait_for_selector(".pp-room:not([hidden])", timeout=T)
    alice.wait_for_function("document.querySelectorAll('.pp-seat').length === 3", timeout=T)
    check("three players at the table, live", alice.locator(".pp-seat").count() == 3)

    check("everyone sees Alice's chosen avatar", bob.locator(".pp-seat .pp-avatar", has_text=avatar).count() == 1)
    bob.click("button.pp-avatar")
    bob.click(".pp-picker-room .pp-avatar-choice >> nth=7")
    new = bob.inner_text(".pp-picker-room .pp-avatar-choice >> nth=7")
    alice.wait_for_function("a => [...document.querySelectorAll('.pp-seat .pp-avatar')].some(e => e.textContent === a)", arg=new, timeout=T)
    check("Bob's new avatar shows to the others live", True)
    bob.reload()
    bob.wait_for_selector(".pp-room:not([hidden])", timeout=T)
    check("a reloaded browser keeps its avatar", bob.locator("button.pp-avatar", has_text=new).count() == 1)

    mallory = open_page(browser, link)
    mallory.wait_for_selector("text=Rejoindre la salle", timeout=T)
    enter(mallory, "bob")
    mallory.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("someone else cannot take Bob's nickname", "déjà pris" in mallory.inner_text(".pp-error"),
          mallory.inner_text(".pp-error"))
    check("Bob's seat is untouched", alice.locator(".pp-seat").count() == 3)

    check("only the host can reveal", bob.locator(".pp-reveal").count() == 0 and alice.locator(".pp-reveal").count() == 1)
    for page, card in ((alice, "3"), (bob, "5"), (chloe, "8")):
        page.click(f".pp-deck-card:text-is('{card}')")
    for page in (alice, bob, chloe):
        page.wait_for_function("document.querySelectorAll('.pp-card.is-down').length === 3", timeout=T)
    check("votes are hidden until revealed", seat_faces(bob) == ["is-down"] * 3 and
          bob.locator(".pp-card.is-up").count() == 0, str(seat_faces(bob)))
    alice.screenshot(path=os.path.join(SHOTS, "2_votes_hidden.png"), full_page=True)

    alice.click(".pp-reveal")
    bob.wait_for_selector(".pp-results:not([hidden])", timeout=T)
    stats = dict(zip(bob.locator(".pp-stat dt").all_inner_texts(), bob.locator(".pp-stat dd").all_inner_texts()))
    check("revealed: average, nearest card, min, max", stats.get("Moyenne") == "5,3" and
          stats.get("Carte la plus proche") == "5" and stats.get("Min") == "3" and stats.get("Max") == "8", str(stats))
    check("everyone sees each vote", sorted(chloe.locator(".pp-card.is-up").all_inner_texts()) == ["3", "5", "8"])
    alice.screenshot(path=os.path.join(SHOTS, "3_revealed.png"), full_page=True)
    chloe.screenshot(path=os.path.join(SHOTS, "4_revealed_mobile.png"), full_page=True)

    alice.click("text=Revoter")
    bob.wait_for_function("document.querySelectorAll('.pp-card.is-up').length === 0", timeout=T)
    check("revote hides and clears the votes", bob.locator(".pp-card.is-down").count() == 0)
    for page, card in ((alice, "8"), (bob, "8"), (chloe, "8")):
        page.click(f".pp-deck-card:text-is('{card}')")
    alice.wait_for_function("document.querySelectorAll('.pp-card.is-down').length === 3", timeout=T)
    alice.click(".pp-reveal")
    alice.wait_for_selector(".pp-results:not([hidden])", timeout=T)
    alice.click(".pp-choice:text-is('13')")
    bob.wait_for_selector(".pp-final-value:text-is('13')", timeout=T)
    check("the host sets the final estimate", True)
    alice.fill("#pp-task-number", "102")
    alice.click(".pp-task-form button")
    bob.wait_for_selector("text=Tâche 102", timeout=T)
    check("recap of finished tasks", "n° 101" in bob.inner_text(".pp-recap") and "13" in bob.inner_text(".pp-recap"),
          bob.inner_text(".pp-recap").replace("\n", " | "))

    alice.hover(".pp-seat[data-participant] >> nth=2")
    alice.click(".pp-remove[aria-label='Retirer Chloé']")
    chloe.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("the host removes a participant", "retiré" in chloe.inner_text(".pp-error") and
          alice.locator(".pp-seat").count() == 2)
    alice.click("text=Verrouiller")
    alice.wait_for_selector("text=Déverrouiller", timeout=T)
    dan = open_page(browser, link)
    dan.wait_for_selector("text=Rejoindre la salle", timeout=T)
    enter(dan, "Dan")
    dan.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("a locked room refuses newcomers", "verrouillée" in dan.inner_text(".pp-error"), dan.inner_text(".pp-error"))
    bob.reload()
    bob.wait_for_selector(".pp-room:not([hidden])", timeout=BOOT)
    check("a known browser comes back as itself, even locked", "Bob" in bob.inner_text(".pp-me"))

    # host handover: Alice (the host) leaves; once unseen for ABSENT seconds, Bob (the next joined) hosts
    if not os.environ.get("POKER_E2E_BASE"):
        alice.close()
        bob.wait_for_function("document.querySelector('.pp-me').innerText.includes('animateur')", timeout=(ABSENT + 30) * 1000)
        check("an absent host hands the room to the next participant", True)
        check("the new host has the host's controls", bob.locator(".pp-task-form:not([hidden])").count() == 1 or
              bob.locator(".pp-reveal").count() == 1)
        back = context.new_page()
        back.goto(link)
        back.wait_for_selector(".pp-room:not([hidden])", timeout=BOOT)
        check("the old host comes back as a participant", "Alice" in back.inner_text(".pp-me") and
              "animateur" not in back.inner_text(".pp-me") and back.locator(".pp-reveal").count() == 0)

    stranger = open_page(browser, BASE + "#" + secrets.token_urlsafe(24))
    stranger.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("an unknown room is not found", stranger.inner_text(".pp-error") == "Salle introuvable.")
    bob.screenshot(path=os.path.join(SHOTS, "5_recap_locked.png"), full_page=True)
    browser.close()


if __name__ == "__main__":
    SHOTS = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "e2e-shots")
    os.makedirs(SHOTS, exist_ok=True)
    main()

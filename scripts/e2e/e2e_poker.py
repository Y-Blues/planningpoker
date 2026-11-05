"""End-to-end: the server (run.sh, memory storage) and four browsers in one room -- create, join by nickname, a stolen
nickname refused, hidden votes, reveal (average, nearest card, min, max), revote, next task, recap, remove, lock, an
unknown room, an absent host's handover; the first load's size measured; screenshots.
    PYTHON=... uv run --no-project --with playwright python scripts/e2e/e2e_poker.py <screenshot dir>
Runs with prefers-reduced-motion (POKER_E2E_MOTION=1: with the animations).
Starts and stops its own server (POKER_E2E_PORT, default 8197), or tests POKER_E2E_BASE (a deployment, its prefix
included: http://localhost:8096/planningpoker/)."""

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(os.environ.get("POKER_E2E_PORT", "8197"))
BASE = os.environ.get("POKER_E2E_BASE") or f"http://localhost:{PORT}/"
BOOT, T = 180000, 20000
ABSENT = 25  # the server's host_absent_seconds for the run (the page pings every 15 s)
# the page's animations off (prefers-reduced-motion), so the screenshots show settled pages; POKER_E2E_MOTION=1 keeps them
MOTION = "no-preference" if os.environ.get("POKER_E2E_MOTION") else "reduce"
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
    context = browser.new_context(locale="fr-FR", reduced_motion=MOTION, **options)
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


JIRA_SITE = "https://test.atlassian.net"
ISSUES = {   # what the mocked Jira answers, by JQL: an epic, its stories (two pages), their sub-tasks
    "key = KP-1 OR parent = KP-1": [
        {"key": "KP-1", "fields": {"summary": "Paiement en ligne", "issuetype": {"name": "Epic", "hierarchyLevel": 1}}},
        {"key": "KP-2", "fields": {"summary": "Carte bancaire", "issuetype": {"name": "Story", "hierarchyLevel": 0},
                                   "parent": {"key": "KP-1"}}},
        {"key": "KP-4", "fields": {"summary": "Facture PDF", "issuetype": {"name": "Story", "hierarchyLevel": 0},
                                   "parent": {"key": "KP-1"}}}],
    "parent in (KP-2,KP-4)": [
        {"key": "KP-3", "fields": {"summary": "Maquette du formulaire", "issuetype": {"name": "Sub-task", "hierarchyLevel": -1},
                                   "parent": {"key": "KP-2"}}}],
}


def fake_jira(context):
    """https://test.atlassian.net: a blank page and a mocked /rest/api/3/search/jql (read only: any other method fails);
    the epic's query comes in two pages (nextPageToken), the requests are recorded"""
    seen = []

    def search(route):
        request = route.request
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query)
        seen.append((request.method, query))
        issues = ISSUES.get(query["jql"][0], [])
        if request.method != "GET":
            return route.fulfill(status=405, body="{}")
        if query["jql"][0].startswith("key = ") and "nextPageToken" not in query:
            return route.fulfill(json={"issues": issues[:2], "nextPageToken": "page2", "isLast": False})
        if "nextPageToken" in query:
            issues = issues[2:]
        route.fulfill(json={"issues": issues, "isLast": True})

    context.route(JIRA_SITE + "/rest/api/3/search/jql*", search)
    context.route(JIRA_SITE + "/browse/*", lambda route: route.fulfill(content_type="text/html", body="<!doctype html><title>Jira</title><p>Jira</p>"))
    return seen


def jira_import(context, alice, bob):
    """the bookmarklet (its real source, from the link the page offers) run on a fake Jira page: pagination, children and
    grandchildren, the handshake with the room's page, the host's confirmation, the queue, the recap tree and its totals"""
    check("the import help and the bookmarklet link are offered to the host only", alice.locator(".pp-import-help summary").inner_text() ==
          "Importer depuis Jira" and alice.locator("a.pp-bookmarklet").count() == 1 and bob.locator(".pp-import:visible").count() == 0)
    href = alice.get_attribute("a.pp-bookmarklet", "href")
    script = urllib.parse.unquote(href[len("javascript:"):])
    secret = alice.evaluate("localStorage.getItem('planningpoker.secret')")
    check("the link holds the room's address, never the secret", secret and secret not in href and
          alice.evaluate("location.href") in script and "\n" not in script)
    alice.click(".pp-import-help summary")
    alice.screenshot(path=os.path.join(SHOTS, "6_import_help.png"), full_page=True)
    if shutil.which("node"):
        syntax = subprocess.run(["node", "--check", "-"], input=f"(async()=>{{{script}}})", text=True, capture_output=True)
        check("the minified bookmarklet parses", syntax.returncode == 0, syntax.stderr[:200])
    seen = fake_jira(context)
    jira = context.new_page()
    jira.goto(JIRA_SITE + "/browse/KP-1")
    with context.expect_page() as opened:
        jira.evaluate("source => (0, eval)(source)", script)
    room = opened.value
    room.on("console", lambda message: message.type == "error" and print("  console:", message.text[:200]))
    room.wait_for_selector(".pp-import-confirm:not([hidden])", timeout=BOOT)
    check("tickets received from the Jira site, waiting for the host", room.inner_text(".pp-import-text") ==
          "4 tickets reçus de test.atlassian.net", room.inner_text(".pp-import-text"))
    check("Jira was only read (GET), page by page, children then grandchildren", seen and all(m == "GET" for m, _ in seen)
          and [q["jql"][0] for _, q in seen] == ["key = KP-1 OR parent = KP-1"] * 2 + ["parent in (KP-2,KP-4)"], str(seen))
    check("nothing is queued before the confirmation", room.locator(".pp-queue-item").count() == 0)
    room.screenshot(path=os.path.join(SHOTS, "7_import_confirm.png"), full_page=True)
    room.click(".pp-import-confirm .pp-primary")
    room.wait_for_selector(".pp-queue-item", timeout=T)
    check("a vote in progress locks the queue", room.locator(".pp-queue-item:disabled").count() == 4)
    room.click(".pp-reveal")   # task 102's votes out: the queue opens
    room.wait_for_selector(".pp-queue-item:not([disabled])", timeout=T)
    tree = room.eval_on_selector_all(".pp-queue-item", "items => items.map(i => i.querySelector('.pp-key').textContent)")
    check("the queue is a tree: epic, stories, sub-task", tree == ["KP-1", "KP-2", "KP-3", "KP-4"], str(tree))
    check("the queue shows titles and kinds", "Carte bancaire" in room.inner_text(".pp-queue") and "epic" in room.inner_text(".pp-queue").lower())
    room.screenshot(path=os.path.join(SHOTS, "8_queue.png"), full_page=True)
    room.set_viewport_size({"width": 360, "height": 800})
    check("the queue fits a 360px screen", room.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    room.screenshot(path=os.path.join(SHOTS, "8b_queue_360.png"), full_page=True)
    room.set_viewport_size({"width": 1280, "height": 800})

    for key, card in (("KP-2", "5"), ("KP-3", "3")):
        room.click(f".pp-queue-item:has(.pp-key:text-is('{key}'))")
        room.wait_for_selector(f".pp-task-title:has-text('{key}')", timeout=T)
        room.click(f".pp-deck-card:text-is('{card}')")
        room.wait_for_selector(".pp-reveal", timeout=T)
        room.click(".pp-reveal")
        room.wait_for_selector(".pp-results:not([hidden])", timeout=T)
    check("a played ticket shows its title", "Maquette du formulaire" in room.inner_text(".pp-task-title"))
    room.fill("#pp-task-number", "9001")
    room.fill("#pp-task-parent", "EPIC-9")
    room.click(".pp-task-form button")
    room.wait_for_selector(".pp-task-title:has-text('9001')", timeout=T)
    room.click(".pp-deck-card:text-is('8')")
    room.click(".pp-reveal")
    room.wait_for_selector(".pp-results:not([hidden])", timeout=T)
    room.fill("#pp-task-number", "9002")
    room.click(".pp-task-form button")
    bob.wait_for_selector(".pp-recap-table tr.is-parent", timeout=T)
    rows = bob.eval_on_selector_all(".pp-recap-table tbody tr", """rows => rows.map(r => [r.className.match(/pp-depth-\\d/)[0],
        ...[...r.querySelectorAll('td')].map(td => td.querySelector('.pp-key') ? td.querySelector('.pp-key').textContent : td.textContent)])""")
    flat = {r[1]: r for r in rows}
    check("the recap is a tree: epic (never played) > story > sub-task", flat["KP-3"][0] == "pp-depth-2" and flat["KP-2"][0] == "pp-depth-1" and flat["KP-1"][0] == "pp-depth-0",
          str(rows))
    check("a story shows its own estimate and the total below it", flat["KP-2"][2] == "5" and flat["KP-2"][3] == "3", str(flat["KP-2"]))
    check("a hand-typed task joins its parent, never played: a group", flat["9001"][0] == "pp-depth-1" and flat["EPIC-9"][3] == "8" and
          flat["EPIC-9"][2] == "–", str([flat.get("9001"), flat.get("EPIC-9")]))
    check("the grand total (101 and the three above)", bob.inner_text(".pp-recap-table tfoot").split()[-1] == "29", bob.inner_text(".pp-recap-table tfoot"))
    bob.screenshot(path=os.path.join(SHOTS, "9_recap_tree.png"), full_page=True)
    bob.set_viewport_size({"width": 360, "height": 800})
    check("the recap tree fits a 360px screen", bob.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    bob.screenshot(path=os.path.join(SHOTS, "9b_recap_tree_360.png"), full_page=True)
    bob.set_viewport_size({"width": 1280, "height": 720})
    room.close()
    jira.close()


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
    context = browser.new_context(locale="fr-FR", reduced_motion=MOTION, permissions=["clipboard-read", "clipboard-write"])
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
    bob.click(".pp-edit")
    bob.wait_for_selector("#pp-profile:not([hidden])", timeout=T)
    check("the profile panel opens on the nickname", bob.evaluate("document.activeElement.id") == "pp-profile-name",
          bob.evaluate("document.activeElement.outerHTML.slice(0, 80)"))
    bob.keyboard.press("Escape")
    bob.wait_for_selector("#pp-profile", state="hidden", timeout=T)
    check("Escape closes it, focus back on the button", bob.locator("#pp-profile:visible").count() == 0 and
          bob.evaluate("document.activeElement.classList.contains('pp-edit')"))
    bob.click(".pp-edit")
    bob.wait_for_selector("#pp-profile:not([hidden])", timeout=T)
    bob.fill("#pp-profile-name", "Alice")
    bob.keyboard.press("Enter")
    bob.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("a taken nickname is refused, the panel stays open", "déjà pris" in bob.inner_text(".pp-error") and
          bob.locator("#pp-profile:visible").count() == 1)
    bob.fill("#pp-profile-name", "Bobby")
    bob.click("#pp-profile .pp-avatar-choice >> nth=7")
    new = bob.inner_text("#pp-profile .pp-avatar-choice >> nth=7")
    bob.screenshot(path=os.path.join(SHOTS, "1c_profile_panel.png"), full_page=True)
    bob.click("#pp-profile button[type=submit]")
    alice.wait_for_function("a => [...document.querySelectorAll('.pp-seat .pp-avatar')].some(e => e.textContent === a)", arg=new, timeout=T)
    alice.wait_for_selector(".pp-seat .pp-name >> text=Bobby", timeout=T)
    check("Bob's new nickname and avatar show to the others live", True)
    bob.wait_for_selector("#pp-profile", state="hidden", timeout=T)
    check("the panel closed, the error is gone", bob.locator("#pp-profile:visible").count() == 0 and
          bob.locator(".pp-error:visible").count() == 0)
    bob.reload()
    bob.wait_for_selector(".pp-room:not([hidden])", timeout=T)
    check("a reloaded browser keeps its avatar", bob.locator("button.pp-avatar", has_text=new).count() == 1)

    chloe.set_viewport_size({"width": 360, "height": 780})
    chloe.click(".pp-edit")
    chloe.wait_for_selector("#pp-profile:not([hidden])", timeout=T)
    check("the profile panel fits a 360px screen", chloe.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth && document.getElementById('pp-profile').getBoundingClientRect().right <= window.innerWidth"))
    chloe.screenshot(path=os.path.join(SHOTS, "1d_profile_panel_360.png"), full_page=True)
    chloe.click("#pp-profile .pp-profile-actions .pp-ghost")
    chloe.wait_for_selector("#pp-profile", state="hidden", timeout=T)

    mallory = open_page(browser, link)
    mallory.wait_for_selector("text=Rejoindre la salle", timeout=T)
    enter(mallory, "bobby")
    mallory.wait_for_selector(".pp-error:not([hidden])", timeout=T)
    check("someone else cannot take Bob's new nickname", "déjà pris" in mallory.inner_text(".pp-error"),
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
    check("recap of finished tasks", "101" in bob.inner_text(".pp-recap") and "13" in bob.inner_text(".pp-recap"),
          bob.inner_text(".pp-recap").replace("\n", " | "))

    jira_import(context, alice, bob)

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
    check("a known browser comes back as itself, even locked", "Bobby" in bob.inner_text(".pp-me"))

    # host handover: Alice (the host) leaves (her Jira tab, also hers, is closed: it would keep pinging); once unseen for ABSENT seconds, Bob (the next joined) hosts
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

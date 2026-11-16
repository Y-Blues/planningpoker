# Review planning poker v0.1.0.3 (English + Jira how-to)

## ARCHITECTE round 1

Date: 2026-11-16. Scope: planningpoker `english` f4da9c6 vs v0.1.0.2, ui_web `steps` 2693984 (tag v0.6.90.3) vs v0.6.90.2,
read against the locked framework sources (releases.lock). Unit tests: poker 93 OK, ui_web test_steps 2 OK.
Probes, run with the real locked Manager + TokenRights + Crud on MemoryStorage: scratchpad `arch_probe/probe.py`, `arch_probe/probe2.py`.

**Verdict: FAIL** (1 blocker, 2 major)

1. **blocker**: the seed is refused, so no text is ever stored. SeedLoader writes the `language`/`translation` records
   as `{sub: seed, tid: system}`. The Manager then checks its reach (storage manager.py:704 `_reaches`), which calls
   TokenRights.get_filter (permissions token_rights.py:172 `_signed(subject)`). That raises NotAuthenticated
   `token_without_rights`: the subject is unsigned, and it is no local service account because the poker composes no
   IModuleRoles. It fails under `api.storage.seeding()` too. Probe: "seed write FAILED: NotAuthenticated" with and
   without VISITOR_HOST, and an anonymous inherited read returns none of the seeded texts. In the real process every
   page opens on the error banner with bare keys (see 2), and English never appears. The unit tests miss it because
   FakeCrud serves the seed JSON directly, and the e2e has not been run yet. Fix, generic, in permissions (owner to
   confirm): TokenRights treats a framework write (`is_seeding()`, the contract SeedLoader states: "the guards meant
   for users' let them through") like a component's own call, with no filter, plus a permissions test. Then add an
   integration test in the poker with the real Manager + TokenRights + SeedLoader + Crud, not FakeCrud.
2. **major**: when the texts cannot be read, the fallback is a page of bare keys. poker_page.py:112 and :118 fall back
   to `built_in_locale`, which holds only the `ui.*` keys. Every `poker.*` label then shows as its key (checked:
   button "poker.create", lead "poker.welcome.lead"). test_language.py:120, `test_unreadable_texts_are_said_never_a_page_of_keys`,
   only checks the banner. Fix: on failure show only the named error (do not draw the app), or as a last resort read the
   packaged seed file (data, importlib.resources), keeping the ERROR log and the banner.
3. **major**: `shared=True` on poker_room, participant, task and vote (models/*.py:7) has no justification. The
   Manager asks IFilter only when there is a subject (manager.py:774-778 `_scope`; `_reaches` also only with a
   subject). The Rooms calls carry no subject, so no tenant filter applies, with or without VISITOR_HOST. Probe: with
   `shared=False`, write and read are OK under VISITOR_HOST. `shared` means one record set for every tenant: it changes
   TenantStamp and unique keys, and TokenRights.get_filter returns None for any subject, so any future signed caller
   holding a read right would see every room. models/__init__.py states a rationale that is false. Revert (KISS), or
   prove the need with a failing test.
4. **minor**, reuse: strings.py:17 `load` re-implements `ycappuccino.ui.i18n.load_locale(source, items=ITEMS)`, which
   makes the same two calls and is what the console's admin.py uses. Use load_locale.
5. **minor**, config: strings.py:8 hard-codes the item names. The site and the console take them as front component
   properties (client.json `language_item`/`translation_item`). Acceptable for a single app; PokerPage properties in
   poker.json would match rule 2.
6. **minor**, generic code in the app: poker.css:369-428 re-declares ui_web's Drawer and StepList structure (fixed
   panel, aria-hidden slide, bottom sheet at 640 px and below, reduced motion, step grid), because the poker does not
   load theme.css. A later Drawer fix will not reach the poker. Follow-up: ui_web ships these structural rules as a
   theme-independent sheet (colours as variables), and poker.css keeps only the colours.
7. **minor**, security surface, otherwise verified sound. probe2: anonymous get_many and get_one on poker_room,
   create translation, update poker_room, delete translation and delete_many poker_vote are all refused
   (NotAuthenticated). Only `language` and `translation` are readable, and only from the public organization
   (`{_tid: system}`, inherited read in the public org). No IAuthentication bundle is composed, so the subject is
   always None and there is no forged-token path. IPlanningPoker methods are `secure=False`, so the new IAuthorization
   does not affect them. Subscribe is still decided by RoomTopicAccess (its fallback refuses anonymous callers, as
   before). The ServiceAccounts config in the included profile, with no such component, is ignored and harmless
   (TokenRights.public_rights covers it). SeedLoader `after` waits for TokenRights and RoomEvents: fine. Residual: the
   anonymous ICrud reads (up to 10000 translations per call) are not throttled. That matches the site's surface, noted
   only.
8. **minor**, UX/wording:
   - The English texts use French guillemets « » (translations.json:399, :415, and the tip titles tip_popup,
     tip_login, tip_none). English uses “ ”.
   - The French tip_nothing (translations.json:534) says « avec le compte de l'animateur », but the poker has no
     accounts. Use « en tant qu'animateur », as the English "as the host" does.
   - index.html has no `lang` until the texts load (up to 15 × 2 s of retries). Set the browser's language at once.
9. **ok**, release mechanics. ui_web 2693984's parent is v0.6.90.2 (429c24d), and tag v0.6.90.3 is on it. The ui_web
   wheel in deploy/wheels is identical to the tag (steps.py, theme.css, drawer.py, builder.py and language.py
   compared). The lock and pyproject are consistent (`ui-web>=0.6.90.3`; ui_content v0.7.6.1 is prod website's).
   Reminder: push the tag and publish the GitHub release before any build without local wheels, or fetch_wheels.py fails.
10. **ok**, confirmations:
    - **i18n**: the poker uses the site's mechanism. Same items (ui_content language/translation, `inherited`), same
      seeding (SeedLoader `follow` source plus the ui_content platform_texts profile, as content.yml's platform-texts
      and yblues-translations), and same loaders (ui.i18n load_languages/load_strings into a Locale, which
      localize_site calls internally) over CrudDataSource(ICrud), with ui_web LanguageSwitch. Not going through
      localize_site/Site is acceptable: it is not a layout Site, and the console does the same.
    - **No inline translations**: no {fr:,en:} literal in app code; the texts are seed data, and a test enforces fr+en
      and matching placeholders for every key.
    - **Reuse**: coded refusals via api.messages, numbers via ui.series.format_number, Drawer and Builder relabel
      reused. StepList is generic, in ui_web, and tested. The bookmarklet only receives a JSON of texts.
    - **Retention**: language and translation are bound=configured, seed_records bound=configured, the poker items
      expire_after 30 d.
    - **Organization shown (4b)**: no language or translation record is displayed; only the texts and the language
      names in the switch appear.

### ARCHITECTE round 1, addendum on c2d1f14 (2026-11-16)

The builder found the same refusal on its first stage run and fixed it in c2d1f14: the bundle
`ycappuccino.permissions.service_accounts`, plus ServiceAccounts `{mode: module, module_roles: [], module_accounts:
[seed], accounts: {seed: read/write language, translation, seedRecord}}`.

- **Finding 1 (blocker) is RESOLVED.** The fix reuses the pattern of website-wm103's ops.yml (a module's local
  service account), which beats the framework change I suggested.
- **Probe** (`arch_probe/probe3.py`, real ServiceAccounts + TokenRights + Manager + Crud): the seed's writes of
  translation and seedRecord now pass, with and without VISITOR_HOST, and the anonymous inherited read returns the
  seeded texts.
- **Module mode** writes nothing and is ready at once. The merged `roles: {anonymous: ...}` from the ui_content profile
  yields no module role (built-in roles are excluded, and `module_roles: []`).
- **Accepted risk**: an unsigned in-process subject `{sub: seed}` may also write the texts through ICrud. Nothing can
  reach that from outside: no IAuthentication is composed, dispatch ignores a subject sent in the payload, and
  TokenRights refuses a signed, peer-asserted or caller-token `sub`.
- **Unit tests**: 93 OK on c2d1f14.

**Verdict stays FAIL**: findings 2 (major: fallback page of bare keys) and 3 (major: `shared=True` unjustified) remain
open; minors 4-8 to fix or accept.

## ERGONOME round 1

Date: 2026-11-16. Scope: 40b5efd vs v0.1.0.2: translations.json (FR + EN), page/poker_page.py, page/tutorial.py,
static/poker.css, static/jira_bookmarklet.js, and the staged e2e screenshots in /mnt/Lexar/linux_offload/poker-en/shots/{fr,en}
(EN 55/55 passed; the FR run was being replayed while I reviewed, and the previous FR run passed 56/56).

**Verdict: PASS** (0 blocker, 1 major to fix in the texts before release if possible, minors logged for later)

1. **major**, the how-to promises "once", but the bookmark belongs to one room. jira.py bakes the room's URL (and the
   page's language) into the bookmarklet, yet the hint ("A bookmark to install once" / « Un favori à installer une
   fois »), the intro ("installed only once" / « installé une seule fois ») and step 2 ("You only do this once" /
   « Vous ne le faites qu'une fois ») all say "once". This holds while a team keeps the same room (a 30-day sliding
   expiry). It breaks on a new room: the task limit says "create a new room", and teams often make one per session.
   The old bookmark then opens the OLD room (the issues land there) or shows "Room not found", and no tip covers that.
   Text-only fix: "once per room" (« une fois par salle »), plus a tip: « Une autre salle s'ouvre, ou "Salle
   introuvable" : glissez à nouveau le bouton depuis cette salle » / "Another room opens, or "Room not found": drag
   the button again from this room". Later, the generic fix is a bookmarklet that does not depend on the room.
2. **minor**, tip « Rien ne se passe dans la salle » / "Nothing happens in the room": the bookmarklet opens the room
   in a NEW tab (window.open), and the banner "N issues received…" appears there, not in the tab the host already has
   open. The likeliest cause of "nothing happens" is looking at the old tab. Say so: "the room opens in a new tab:
   look there". The fixed wording « dans le navigateur de l'animateur » is better than the ARCHITECTE's suggested
   « en tant qu'animateur » (agreed with the change made).
3. **minor**, figure vs text: tutorial.py:_browser hard-codes the keys "Ctrl / ⌘", "Shift" and "B". The French text
   says « Maj » while the figure shows "Shift". The figure is also a visible text that is not a key, which goes
   against ARCHITECTE 10's "no inline text". Use a key (« Maj » / "Shift").
4. **minor**, English wording, natural overall, with the right vocabulary (Average, Closest card, Final estimate, Vote
   again, Reveal, host, Summary, Sub-task, issues, Up next, Dismiss, "{voted} of {total} voted"). Possible polish:
   - intro: "Pull the issues from a Jira epic, issue or search into this room";
   - readonly: "Jira is read-only here: nothing is ever written or changed in it";
   - tip_none: "The page you have open shows no issues";
   - "No issue found" -> "No issues found" (the alert and the tip title together);
   - "recognised" -> "recognized" (the other texts read as US English);
   - the hint, "…: the step-by-step guide", reads like a caption in both languages. Try "Install a bookmark once,
     then import from Jira in one click." (and see 1);
   - "Σ below" is understandable only through its tooltip; acceptable.
5. **minor**, Edge: in the drag tip, "right-click the bookmarks bar › Add page" is Chrome's menu. Edge calls it the
   "favorites bar", and its menu entry differs. Say "Chrome: …; Edge: favorites bar › Add this page to favorites",
   or keep Chrome only.
6. **minor**, language switch: it is findable (top right, on the welcome and in the room, a native select). The
   options are endonyms (Français / English), the Auto label is translated (« Auto (navigateur) » / "Auto
   (browser)"), it has the aria-label Language, the choice is kept, and it switches at once (e2e checked it both ways,
   on the welcome). Two gaps:
   - nothing visible says "language" before the user opens it. A 🌐 before the label would help a visitor whose
     browser has the wrong language;
   - at 360 px it wraps onto its own header line (shots 4_revealed_mobile, 9b), about 45 px taken from the room.
     Fit it on the tools row (a shorter "🌐 Auto"), or accept it.
   The switch in the room is not checked by the e2e. The code relabels the page, redraws it and rebuilds the
   bookmarklet's texts, which reads fine.
7. **minor**, e2e evidence: 6c_tutorial_panel and 6b are captures of a scrolled panel, so steps 3 to 5, the read-only
   note and the five tips never appear in any screenshot (the DOM checks do count them: 5 steps, 5 figures, read-only,
   5 tips). Add a capture after scrolling the panel to its end.
8. **ok**, Jira how-to otherwise meets the brief:
   - it is opened from the import area (host only), closes (×, focus back on the button), is a side panel on desktop
     and a bottom sheet at 360 px without horizontal scroll, and reads well at 360;
   - five numbered steps, one action each, short sentences: Ctrl/⌘+Shift+B, drag (the button is right under step 2),
     open Jira, click the bookmark, what is seen (Import, Up next, Epic › Story › Sub-task);
   - the figures are helpful (the dashed target bar, the dropped bookmark, the address);
   - "you need a computer" is said up front, and "read only" in a visible box;
   - the tips cover the drag fallback (right-click, or Copy the bookmark), pop-ups, 401/403 and no issue found, and
     their titles quote the bookmarklet's real alerts;
   - the 2 known text fixes are applied in 40b5efd: EN “ ” quotes, and « dans le navigateur de l'animateur ».
9. **ok**, French unchanged from v0.1.0.2: every French literal removed by the diff (page, view, rooms, bookmarklet)
   is identical in seed fr. The only additions are the new how-to's entry (« 📥 Importer depuis Jira » plus its hint)
   and its panel. The French decimal comma is kept (« 5,3 », shot fr/4_revealed_mobile).
10. **architecture, challenge/agree with ARCHITECTE round 1**:
    - 2 and 3 are resolved in 40b5efd: strings.packaged reads the shipped seed beside the error, and `shared` is
      removed from the models;
    - I agree with 6 (poker.css duplicates the Drawer and StepList structure; ui_web should ship a structural sheet);
    - 1 above is also a design point: the bookmarklet binds a room and a language into a link meant to live in the
      bookmarks bar for good. A room-independent bookmarklet (it opens the poker, and the room page that answers
      "ready" picks the issues up) would make "once" true, and is worth a later phase;
    - 8's index.html `lang` before the texts load: not seen in the screenshots, still open as noted.

## ARCHITECTE confirmation

Date: 2026-11-16. Diff c2d1f14..b47ad0b (40b5efd, b47ad0b). Unit tests rerun: 94 OK. Stage e2e as reported by the
builder: FR 56/56, EN 55/55.

**Verdict: PASS**

- **Major 2 is fixed.** `strings.packaged` falls back to the built-in texts plus the shipped seed (package data, the
  same wheel the browser loads), shown beside the named error and the ERROR log. The test now asserts a real label
  rather than a key.
- **Major 3 is fixed.** `shared=True` is reverted on the 4 poker items, along with the false docstring.
- **Wording**: the English quotes are now “ ”, and the French « Rien ne se passe » tip no longer mentions accounts.
- **ERGONOME changes**: the new tip_room text and the once-per-room wording are fine.
- **_apply**: a page that was joined and gets a catching-up state with `me: None` is now told it was removed. This is
  sound: open_room and the not-found path reset `_me` first, and pings and topic messages keep the current `_me`.
- **Minors 4-7 stay logged for later**: strings.load could reuse ui.i18n.load_locale; ITEMS as component properties;
  generic Drawer/StepList CSS in poker.css; anonymous ICrud reads not throttled. Also: `<html>` has no lang before the
  texts load.

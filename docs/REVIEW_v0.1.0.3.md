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

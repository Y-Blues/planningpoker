# Review planning poker v0.1.0.4

## ERGONOME round 1

Date: 2026-11-16. Scope: planningpoker 00f67da vs v0.1.0.3 (seed/translations.json FR + EN, page/poker_page.py,
page/tutorial.py, static/poker.css, scripts/e2e/e2e_poker.py) and ui_web 8054e3f vs v0.6.90.3 (LanguageSwitch icon,
assets/controls.css, theme.install_controls). Evidence: staged e2e FR 59/59 and EN 58/58, 0 ERROR (the FR log only has
podman's SIGKILL warning from the planned restart); shots in v0104/shots/{fr,en} compared with shots/{fr,en} (v0.1.0.3).

**Verdict: PASS** (0 blocker, 0 major; minors below, none a blocker for this release)

1. **ok**, "🌐 Auto" is clear enough. The globe says "language" in any language, the select's accessible name is
   « Langue » / "Language", and the open list shows the endonyms (Français / English). "Auto" no longer says *what* it
   follows, but that is a common convention and the choice reverts in one click. Optional: a `title` tooltip
   ("Auto: your browser's language").
2. **ok**, the header holds at 360 px, both languages. The switch sits on the brand's line in 1d_profile_panel_360,
   4_revealed_mobile, 8b_queue_360 and 9b_recap_tree_360, and an e2e check asserts it. This saves the ~45 px row that
   v0.1.0.3 spent on it (compare shots/fr/8b_queue_360). For the host, FR keeps its two tool rows as before
   (« Alice · animateur », Modifier / Verrouiller, Copier le lien), and EN fits Lock on the first row. The welcome shows
   only the brand and the switch, so it fits by construction, though no 360 px capture of it exists.
3. **minor**, on a phone the tools are now right-aligned (`.pp-tools { justify-content: flex-end }`). A wrapped row
   leaves one button stranded at the right (« Copier le lien » in fr/9b, "Copy link" in en/8b), and the identity chip
   no longer starts the row. This is cosmetic. `justify-content: flex-start` inside the ≤560 px query restores the
   v0.1.0.3 reading order.
4. **minor**, probable regression at tablet widths, not captured. The FR host header measures 874 px in fr/8_queue
   (brand 181 + tools 545 + switch 124 + gaps), so between 561 px and ~900 px it wraps. The switch (`order: 2`) then
   drops alone to the *start* of a second line, whereas v0.1.0.3's `.pp-header-end` kept it right-aligned. Fix (KISS):
   raise the brand-line rule (`.pp-tools { order: 3; flex-basis: 100% }`) to ~920 px, and add a 768 px host capture
   to the e2e.
5. **ok**, the Edge steps are plausible and accurate for current (Chromium) Edge. Right-clicking the favorites bar
   offers "Add this page to favorites", and right-clicking a favorite offers "Edit", which opens a Name + URL dialog.
   The FR names (« barre des favoris », « Ajouter cette page aux favoris », « Modifier ») match French Edge, and the EN
   uses the US spelling "favorites". Chrome's "Add page" / « Ajouter une page » stays right.
6. **minor**, coverage: the changed tip (tip_drag, Edge) still appears in no screenshot. 6c stops at step 3, and
   6d/6e start at the second tip. Steps 4-5, the read-only note and the first tip are only checked by the DOM. Add one
   middle capture: `scrollIntoView` on `.pp-tutorial-readonly`.
7. **minor**, French typography, pre-existing but now visible. The FR seed has no non-breaking space at all (0 of 139
   entries) before « : ; ? ! » or inside « ». In fr/6d_tutorial_end the new tip breaks as "« tickets reçus" /
   "» s'y affiche". Fix this seed-wide with U+202F (or U+00A0). The new FR sentence is also clunky: « regardez-y,
   « tickets reçus » s'y affiche » has *y* twice and a comma splice. Suggested: « La salle s'ouvre dans un nouvel
   onglet : « tickets reçus » s'y affiche. Sinon, … ». The EN text ("look there for “issues received”") matches the
   real banner (poker.import.received_many).
8. **ok**, the EN polish is applied: the intro "Pull the issues from…", "Jira is read-only here", "No issues found"
   (the tip title matches the bookmarklet's alert poker.jira.none), "recognized", and the hint "Install a bookmark once
   per room, then import from Jira in one click.". The FR hint is parallel. The text reads as natural US English and
   is consistent with step 2 and the room tip ("once per room").
9. **ok**, step 1's figure shows « Ctrl / ⌘ + Maj + B » / "Ctrl / ⌘ + Shift + B" (fr/6c, en/6b), it is relabelled
   with the texts, and an e2e check covers it. `<html lang>` is set at start from the shipped seed and the browser's
   languages, before the storage read. Nit: `_show_language` builds a LanguageSwitch twice. The first is never
   rendered, so this is harmless.
10. **ok**, architecture (cross-check):
    - The Drawer/StepList structure moved to ui_web `assets/controls.css`, which `theme_css()` appends and
      `install_controls` installs once, never beside the theme. It is coloured by `--yc-*` tokens with fallbacks
      equal to the old values. This resolves ARCHITECTE v0.1.0.3 minor 6.
    - poker.css now only maps `--pp-*` onto `--yc-*` and keeps its own look.
    - `load_locale` with `I18nItems` from PokerPage properties resolves minors 4/5. The LanguageSwitch `icon` is
      generic, optional and tested.
    - A separate `poker.language_auto` key, rather than overriding `ui.language_auto`, is right: the translation item
      is shared with other apps.
    - KISS holds.

## ARCHITECTE round 1

Date: 2026-11-16. Scope: planningpoker 00f67da vs v0.1.0.3 (all files) and ui_web 8054e3f vs v0.6.90.3 (theme.css,
theme.py, assets/controls.css, language.py, README, tests), against ui v0.5.78 i18n.py and core component_factory.py.
Reran: poker unit 96 OK; ui_web test_theme + test_language 16 OK. Read: e2e logs FR 59/59, EN 58/58, stage_app.log
0 ERROR, and shots v0104/{fr,en} (4, 6c, 6d, 6e, 9b, 1_welcome).

**Verdict: PASS** on the code. Release precondition: finding 1, before tagging.

1. **major** (process, not code; a release precondition), the ui_web version line has forked. Local tag v0.6.90.3.1
   (1416fcc, branch wm16: PaneLayout collapsible + m13 grip) is NOT an ancestor of 8054e3f. webmail-wm16/pyproject.toml:17
   pins `ycappuccino-ui-web>=0.6.90.3.1`, so a 0.6.90.4 built from 8054e3f would satisfy that pin without the
   feature. The next website lock bump to 0.6.90.4 would also silently drop the webmail's fold. current_tasks
   19:07 already says "rebase/merge ui_web 0.6.90.4 onto v0.6.90.3.1 before tagging", but this is not done yet:
   v0.6.90.4 is not tagged, and the wheel in deploy/wheels and image a7b85bc520bc come from the un-rebased commit.
   `git merge-tree` shows only pyproject.toml conflicting, and theme.css merges clean (3.1 touches pane rules only).
   Before tagging:
   - rebase onto v0.6.90.3.1;
   - rerun the ui_web suite;
   - rebuild the wheel and the image;
   - rerun the poker e2e (FR + EN), the impacted gate;
   - then tag. Also fix the releases.lock comment ("built from the tag": no tag exists yet).
2. **ok**, rule-order move in theme.css: the only change is order inside the theme's one <style>.
   - The rules after the old position that touch the drawer are theme.css:643-644 (margins, no overlapping property)
     and theme.css:661-662, the reduced-motion `transition: none`. The latter now precedes controls.css's
     `.yc-drawer { transition }` at equal specificity, but controls.css:64-66 re-applies reduced motion at its own
     end, so the result is unchanged.
   - The fallbacks equal the old values. `--yc-accent-text` and `--yc-drawer-*` are defined nowhere in the
     workspace, so the step number stays #fff, with 80vh and min(380px, 92vw).
   - webmail front/style.py, the website themes and tenfoot are separate <style>/<link> elements, so nothing changes
     for them. `theme_css()` still contains everything (theme.py:32), so apps that concatenate it are unaffected.
3. **ok**, install_controls vs install_theme (theme.py:40): controls are skipped when the theme is there. Nit: the
   reverse (controls, then a later install_theme) leaves two identical copies, which is harmless. It is tested both
   ways in test_theme.
4. **ok**, specificity of poker.css vs the controls <style>. The poker.css <link> comes first (index.html and
   PyodidePage's link_stylesheets, adopted once), and install_controls (poker_page.py:85) appends the <style> after
   it, so controls win ties.
   - Every poker override is scoped and higher: `.pp-tutorial .yc-*` (0,2,0)+, `.pp-app .yc-drawer-backdrop`. The
     drawer and its backdrop are rendered inside `.pp-app`, with the class `yc-drawer pp-tutorial`.
   - `.yc-drawer-close` (poker.css:380) has no counterpart in controls, and the tokens sit on `:root`
     (poker.css:374).
   - Correct, but fragile: an unscoped override added later would silently lose. Keep the scoping rule, maybe as a
     comment at poker.css:372.
5. **ok**, property wiring: core component_factory.py:147-148 turns defaulted __init__ parameters into component
   properties, and fronts/poker.json sets them as the site's client.json does for WebSite (site.py:56). Unit test
   test_the_items_are_the_page_s_properties proves that the named items are read. Nits:
   - the defaults ("language"/"translation") duplicate poker.json, where WebSite defaults to "";
   - `I18nItems.named` raises in __init__ (poker_page.py:49) without the "PokerPage: property" prefix that WebSite
     adds in start(). Both are acceptable.
6. **ok**, i18n stays exactly the site's mechanism: ui_content `language`/`translation` items, `ui.i18n.load_locale`
   with `I18nItems.named` (ui v0.5.78 i18n.py:36, :296), and ui_web LanguageSwitch. `strings.load` and `ITEMS` are
   gone (reused, not parallel). `poker.language_auto` as its own key is right (agree with ERGONOME 10): overriding
   `ui.language_auto` in the shared translation item would change the other apps.
7. **ok**, lang at once: start() takes `strings.packaged(dom.languages())`, then `_show_language()`, then
   `set_document`, all before `await load_locale` (poker_page.py:86-88). A test holds the CRUD and asserts lang "en".
   - LanguageSwitch is built twice (:106-112), which is harmless: its constructor only reads the preference
     (language.py:30-41), and only the second instance is rendered (:425).
   - Nit: __init__ also reads the seed JSON (:71); built_in_locale() would do, since start() replaces it.
   - Residual: index.html:4 has no `lang` during the Pyodide boot (~5.6 s on the first load, per first_load.json).
     Fixing that would need JS (rule 7b), so leave it.
8. **ok**, generic placement and reuse:
   - controls.css, install_controls and the LanguageSwitch `icon` are in ui_web (extended), documented in the README
     and tested;
   - Drawer and StepList are reused unchanged, and load_locale is reused;
   - no new @Item, so there is no retention issue;
   - no JS app logic;
   - KISS: no new component.
9. **minor**, stale docstrings: drawer.py:4 ("theme.css animates them") and steps.py:6 ("(theme.css)") now mean
   assets/controls.css.
10. **minor**, a11y on phones: in the DOM the switch comes after the tools (poker_page.py:425), but at ≤560 px it is
    shown before them (poker.css:101 `order: 2`, :446 `order: 3`). Tab order no longer follows the visual order
    (WCAG 2.4.3, mild). Accept, or render the switch before the tools and reorder for wide screens instead.
11. **ok**, figure keys: tutorial.py:61 uses `poker.tutorial.key_ctrl`/`key_shift` via the Builder (relabelled), and
    « Maj » now matches the FR text « Ctrl + Maj + B ». The unit test and e2e check both languages.
12. **ok**, wording: the EN polish is applied as logged, the Edge steps are plausible (agree with ERGONOME 5), and
    "recognized" and "No issues found" match the bookmarklet's alerts.
13. **note**, anonymous ICrud reads of the texts are not throttled. This is the same as the site and deliberately left.
14. **cross-check ERGONOME round 1**:
    - agree 3, 6 and 7 (the FR NBSP, and the double « y » in tip_nothing);
    - agree 4, confirmed in code: `.pp-header` is `justify-content: space-between; flex-wrap: wrap` (poker.css:92)
      and the switch has `order: 2` with no `margin-left: auto`, so between 561 px and the header's width a wrapped
      switch lands alone at the line's start. Fix it with 3 together, and with 10 if the order changes;
    - on 9 ("html lang set at start"): at PokerPage start, which is after the Pyodide boot (see 7);
    - on 10: no challenge.

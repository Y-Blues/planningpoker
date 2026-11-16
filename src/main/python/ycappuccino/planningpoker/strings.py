"""The planning poker's languages and texts, as the Y.Blues site reads its own: the `language` and `translation` items of
ui_content (seeded by ui_content's platform profile and by seed/translations.json), read by the page over ICrud with
ycappuccino.ui.i18n.load_locale (the items named by PokerPage's properties). No text is written here: only which keys
the bookmarklet gets, and the shipped seed as the last resort."""

import json
from importlib import resources
from typing import Sequence

from ycappuccino.ui.i18n import Locale, built_in_locale

LANGUAGE_PREFERENCE = "planningpoker.language"   # the switch's choice, kept by the browser like the nickname

# the bookmarklet's texts (static/jira_bookmarklet.js reads TEXT.<name>), by key
BOOKMARKLET_TEXTS = {"not_jira": "poker.jira.not_jira", "blocked": "poker.jira.blocked", "status": "poker.jira.status",
                     "ask_key": "poker.jira.ask_key", "no_key": "poker.jira.no_key", "none": "poker.jira.none",
                     "failed": "poker.jira.failed"}


def packaged(wanted: Sequence[str] = ()) -> Locale:
    """the last resort when the storage cannot be read (the error is said beside it): the built-in texts and the poker's
    seed file as shipped, in the first of `wanted` (the browser's languages) they are written in -- never bare keys"""
    records = json.loads(resources.files("ycappuccino.planningpoker").joinpath("seed/translations.json").read_text(encoding="utf-8"))
    return built_in_locale(wanted).with_texts({record["key"]: record["text"] for record in records})

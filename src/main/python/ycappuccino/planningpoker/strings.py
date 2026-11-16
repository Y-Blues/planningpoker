"""The planning poker's languages and texts, as the Y.Blues site reads its own: the `language` and `translation` items of
ui_content (seeded by ui_content's platform profile and by seed/translations.json), read over ICrud through
ycappuccino.ui.i18n into a Locale. No text is written here: only the item names and which keys the bookmarklet gets."""

import json
from importlib import resources
from typing import Sequence

from ycappuccino.ui.datasource import DataSource
from ycappuccino.ui.i18n import I18nItems, Locale, built_in_locale, load_languages, load_strings

ITEMS = I18nItems(languages="language", translations="translation")
LANGUAGE_PREFERENCE = "planningpoker.language"   # the switch's choice, kept by the browser like the nickname

# the bookmarklet's texts (static/jira_bookmarklet.js reads TEXT.<name>), by key
BOOKMARKLET_TEXTS = {"not_jira": "poker.jira.not_jira", "blocked": "poker.jira.blocked", "status": "poker.jira.status",
                     "ask_key": "poker.jira.ask_key", "no_key": "poker.jira.no_key", "none": "poker.jira.none",
                     "failed": "poker.jira.failed"}


async def load(source: DataSource) -> Locale:
    """the storage's languages (its default first) and every text of each (the built-in ui.* ones where it has none);
    a transport failure is raised, never taken for an empty storage"""
    return Locale(languages=await load_languages(source, ITEMS), strings=await load_strings(source, ITEMS))


def packaged(wanted: Sequence[str] = ()) -> Locale:
    """the last resort when the storage cannot be read (the error is said beside it): the built-in texts and the poker's
    seed file as shipped, in the first of `wanted` (the browser's languages) they are written in -- never bare keys"""
    records = json.loads(resources.files("ycappuccino.planningpoker").joinpath("seed/translations.json").read_text(encoding="utf-8"))
    return built_in_locale(wanted).with_texts({record["key"]: record["text"] for record in records})

"""The reader an organization update uses: the Light Pull rules, read wider (25 Nov 2026).

GHUS found updates did too little: three to five pages of 7,000 characters each
left most boxes "not found" (Carnegie Mellon: three pages, eight facts). An
update is asked for one organization already on the map, so it reads more of
that organization's OWN site - up to ten pages, three topic pages, longer page
text, four follow-up pages for the boxes still missing - with the same quote
check and evidence rules as the Light Pull (``light_pull_reader``). Discovery's
Light Pull for new candidates keeps its bound.

``improve_description`` (``description_upgrade``) runs on what this reader read.
"""

from __future__ import annotations

from agents.collection.light_pull_reader import LightPullReader

UPDATE_MAX_PAGES = 10
UPDATE_TOPIC_PAGES = 3
UPDATE_PAGE_CHARS = 12000
UPDATE_FOLLOWUP_PAGES = 4
UPDATE_MAX_TOKENS = 6000


class UpdateReader(LightPullReader):
    """A Light Pull reader that reads more of the organization's own pages."""

    max_pages = UPDATE_MAX_PAGES
    topic_pages = UPDATE_TOPIC_PAGES
    page_chars = UPDATE_PAGE_CHARS
    followup_pages = UPDATE_FOLLOWUP_PAGES

    def __init__(self, client, fetch, *, max_tokens: int = UPDATE_MAX_TOKENS, **kwargs):
        super().__init__(client, fetch, max_tokens=max_tokens, **kwargs)

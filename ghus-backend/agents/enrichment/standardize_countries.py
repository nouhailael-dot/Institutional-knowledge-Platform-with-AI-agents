"""One form for the country (GHUS, 24 Nov 2026): every stored US spelling becomes "USA".

    python -m agents.enrichment.standardize_countries          # dry run: what would change
    python -m agents.enrichment.standardize_countries --live   # writes

The write itself is the approved writer's (agents.enrichment.decisions
standardize_countries); this module is only its command line.
"""

from agents.enrichment.decisions import _countries_main

if __name__ == "__main__":
    raise SystemExit(_countries_main())

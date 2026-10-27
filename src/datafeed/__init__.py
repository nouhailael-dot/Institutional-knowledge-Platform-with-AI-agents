"""Data Feed: GHUS adds Actors, People and Events by spreadsheet or by hand.

Nothing here writes a canonical record. Records are validated and previewed
here, then staged for Review by the backend's own command
(``agents.datafeed.stage_import``); only a GHUS reviewer's decision admits one,
through the approved admission workflow.
"""

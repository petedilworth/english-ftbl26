"""
The editions: one email a day, five days a week, all built the same way.

Each edition is a subclass of `base.Edition` that turns the database into
an `EditionOutput`. The runner (`runner.py`, invoked as
`python src/edition.py <name>`) does everything else - the size check,
sending, archiving, the claims ledger and the sent marker - identically
for all of them. See docs/editions.md for the design and docs/voice.md
for how they should sound.

The registry lives in `registry.py`, not here: `digest.py` imports
`editions.phrasing`, and an eager import of the editions from this
package would loop back through it.
"""

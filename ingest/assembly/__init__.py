"""Step 2: assemble the processed datasets into one training view (data/training/).

Stages, in order: load (verify) -> confidence -> derive -> backfill -> dedup -> split -> weights ->
Jev traces -> export. Processed data is never modified; every stage works on in-memory copies.
"""

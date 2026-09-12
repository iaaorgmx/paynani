"""
paynani CLI — the onboarding flow, in Python.

Ports webapp/'s PHP setup form so an agent host with no PHP CLI can still run
it: every operational script elsewhere in this repository is already Python 3,
standard library only (see harness/adapters/*.py), so this package adds no new
runtime dependency to what paynani already requires to function at all. See
issue #114 for the PRD and the language-choice rationale.
"""

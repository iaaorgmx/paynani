---
name: Harness candidate evaluation
about: Measure a candidate runtime before adding adapter support
title: "Evaluate harness candidate: <name>"
labels: enhancement
---

Before writing adapter code, answer these five questions on a real host:

1. Is there a session-start hook or equivalent startup signal?
2. Can Paynani deliver to an open session after it becomes idle?
3. What happens when the target session is busy?
4. What happens in non-interactive or headless mode?
5. Where do the mailbox credentials and runtime secrets live?

Record exact commands, versions, observed output, and whether the candidate is
`replay-only`, `live`, `autonomous`, or unsupported.

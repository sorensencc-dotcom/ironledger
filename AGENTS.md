---
ijfw_version: 1.6.5
ijfw_schema: 1
type: code
---

# AGENTS.md

This file follows the open AGENTS.md spec (https://agents.md/) and is the
canonical agent-instructions surface for this project.

## Project intent (seeded from brainstorm)

Phase 15: attach later evidence to an existing economic event. PDF statement
rows (text layer) are more evidence on an existing charge, confirmed in the
existing inbox. New formats are adapters into that linker. Never a second
posting for a confirmed match. Never auto-attach. Packaging waits.

<!-- IJFW-MEMORY-START -->
Memory: `.ijfw/memory/` — brief.md, research.md, handoff.md
Last: Phase 15 shipped 2026-09-15 on main (HEAD e68ef25). Next: real PDF try-on vs SimpleFIN. Handoff: docs/meta/plans/ironledger-phase-15-handoff.md.
<!-- IJFW-MEMORY-END -->

<!-- IJFW-ROUTING-START -->
Project-level plan/build → ijfw-workflow. After brief lock → ijfw-plan. Do not start execute until the user approves the plan.
<!-- IJFW-ROUTING-END -->

<!-- IJFW-AGENTS-START -->
<!-- IJFW-AGENTS-END -->

<!-- IJFW-BLACKBOARD-START -->
{}
<!-- IJFW-BLACKBOARD-END -->

<!-- IJFW-DISCIPLINE-START -->
# Code Discipline

Working code only. Finish the job. Plausibility is not correctness.

## Section 0 — Non-negotiables

No flattery, no filler. Start directly with answers. Disagree when you
disagree — call out false premises before proceeding. Never fabricate file
paths, APIs, or test results. Stop when confused: if ambiguity exists, ask
rather than guess. Touch only what you must — every line must trace to the
user's request.

## Section 1 — Before writing code

State your plan in one or two sentences before editing. Read the files you
will modify and their callers. Match existing patterns in the codebase rather
than imposing new styles. Surface assumptions explicitly. Present tradeoffs
when multiple approaches exist.

## Section 2 — Writing code: simplicity first

No features beyond what was asked. Avoid premature abstraction or
configurability.

## Section 3 — Surgical changes

Do not "improve" adjacent code, comments, formatting, or imports that are not
part of the task. Every changed line must trace directly to the request.

## Section 4 — Goal-driven execution

Rewrite vague asks into verifiable goals before starting. Run the verification.
Read the output. Do not claim success without checking.

## Section 5 — Tool use and verification

Prefer running the code to guessing about the code. Never report "done" based
on a plausible-looking diff alone.

## IronLedger invariants

Plaintext Beancount is the accounting authority. SQLite is a disposable
projection. Zero runtime `import beancount` in `src/ironledger`. Money path
is integer minor units only — no float division.
<!-- IJFW-DISCIPLINE-END -->

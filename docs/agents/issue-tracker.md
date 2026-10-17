# Issue tracker

**Tracker:** local markdown. Issues live as one file per ticket under
`.scratch/<feature>/issues/NN-slug.md`, numbered in dependency order, and are committed to the
repo so the ticket history travels with the code.

**Why not GitHub Issues:** the `gh` CLI on the development machine is signed into a different
(employer) account. This repo is pushed over the `github.com-second` SSH alias as `eamax-code`.
Switch to GitHub Issues only after `gh auth login` as `eamax-code`.

PRs as a request surface: off.

## Conventions
- Ticket status lives in the file's `**Status:**` line (`ready-for-agent`, `in-progress`, `done`).
- Acceptance criteria are checkboxes; tick them in the ticket when verified by a test or a run.
- Never edit a parent/spec file from a ticket.

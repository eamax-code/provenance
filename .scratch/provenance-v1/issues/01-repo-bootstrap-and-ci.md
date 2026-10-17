# 01: Repo bootstrap, rename to Provenance, CI on GitHub

**What to build:** The existing MVP lands in `eamax-code/provenance` as the first commit under the Provenance name, with continuous integration that runs lint and the full test suite on every push, so every later ticket has a green baseline to build on.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Project, settings defaults and docs use the name Provenance; the API title and OpenAPI reflect it
- [x] GitHub Actions workflow runs ruff and pytest (SQLite and PostgreSQL service) on push and pull request
- [x] `.scratch/` tickets, agent docs, glossary and ADRs are committed
- [x] First push to `origin/main` succeeds over the `github.com-second` alias with the eamax-code identity

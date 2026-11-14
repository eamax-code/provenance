# ADR 0010: The API reference at /docs is the site's own page, not Swagger UI

**Status:** accepted (2026-11-15)

AGENTS.md §4 and §8.9 call for FastAPI's Swagger UI at `/docs`. By release every other page
shares one header, footer and dark palette (GH #11), and `/docs` was the one page in a different
look, light and generic, behind the main "Data API" link.

**Decision.**
- `/docs` serves `site/docs/`, which renders the live `/openapi.json` in the shared layout:
  groups by tag, parameters, request and response fields, auth, a curl example and a link to
  the Playground. It builds every node with `textContent`, so nothing from the description is
  parsed as markup.
- `/openapi.json` is unchanged and remains the contract. Trying a call is the Playground's job.
- The quickstart and guides are at `/developers/`, and the changelog and versioning policy are
  at `/changelog/`.

**Consequences.** There is no Swagger "Try it out". A developer who wants it can load
`/openapi.json` into any OpenAPI tool. The reference test checks that every tag in the spec has
a heading, so a new group cannot go missing.

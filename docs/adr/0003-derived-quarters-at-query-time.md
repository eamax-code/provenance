# ADR 0003: Derived quarters are computed at query time and never stored

**Status:** accepted (2026-10-17)

`financial_facts` holds only observations reported by the issuer. Quarter values obtained by
subtracting two year-to-date observations are computed when `include_derived=true` is requested
and returned with `derived=true`, `quality_status=derived` and both source observations.

**Why:** keeps the stored dataset a faithful record of the source and makes the derivation
auditable per response.

# Q-07 Activist stakes (Schedule 13D): filers, stakes, stated purpose, amendment chains

Status: **built** (2026-11-25; ui's 9 comments folded in, see "Build notes" at the end). MCP and
chat follow.

A Schedule 13D is filed by whoever acquires more than 5% of a class with a purpose beyond passive
investment (influence over the company); a 13G is the passive form. Information about what the
filers reported, not signals. **Not investment advice.**

## Source and coverage

- Structured Schedules 13D and 13D/A, filed as XML since December 2024 (EDGAR form types
  `SCHEDULE 13D`, `SCHEDULE 13D/A`): reporting persons, shares, percent of the class (already
  stored for the holders view), and **Item 4, Purpose of Transaction, as filed** (new: read from
  the same XML; a new table, its load gated as below).
- Older free-text schedules (`SC 13D`, before December 2024) are not read: a chain starts at the
  first structured filing, and `coverage` says so on every response. For example, the Schedule
  13D on Match Group filed on 15 July 2024 (free text, accession 0000902664-24-004719) is not
  shown; its later structured amendments, if any, start that chain. 5,943 free-text 13Ds filed
  since January 2024 are in the index and unread.
- Today: about 1,900 original 13Ds and 7,500 amendments about 2,100 companies are stored.

## 1. `GET /v1/companies/{cik}/activists?status=&as_of=`

The company's 13D filers, one entry per filer chain (a filer and its amendments).

| Parameter | Values | Default |
|---|---|---|
| `status` | `current` (latest filing at or above 5%) or `all` (also exited) | `current` |
| `as_of` | ISO date: only filings made by then | none |

```json
{
  "cik": "0000012345",
  "data": [
    {
      "filer": {"name": "Starboard Value LP", "cik": "0001517137"},
      "group": [{"name": "Starboard Value LP", "cik": "0001517137", "type": "PN",
                 "type_label": "partnership"},
                {"name": "Jeffrey C. Smith", "cik": null, "type": "IN",
                 "type_label": "individual"}],
      "current": {"percent": 9.1, "shares": 5400000, "class_label": "Class A common stock",
                  "form": "SCHEDULE 13D/A", "amendment_number": 2,
                  "filed_date": "2026-10-02", "event_date": "2026-09-30",
                  "accession_number": "...", "source_url": "https://www.sec.gov/Archives/..."},
      "first_filed": {"form": "SCHEDULE 13D", "filed_date": "2026-03-04", "percent": 6.2,
                      "accession_number": "...", "source_url": "https://www.sec.gov/Archives/..."},
      "switched_from_13g": {"filed_date": "2025-11-12", "form": "SCHEDULE 13G/A",
                            "percent": 5.4, "source_url": "..."},
      "purpose": {"excerpt": "The Reporting Persons acquired the Shares ... believe the Issuer is
                  undervalued and intend to engage with management and the Board ...",
                  "truncated": true, "form": "SCHEDULE 13D/A", "filed_date": "2026-06-02",
                  "accession_number": "...", "carried_forward": true,
                  "source_url": "https://www.sec.gov/Archives/..."},
      "chain": [
        {"form": "SCHEDULE 13D", "filed_date": "2026-03-04", "event_date": "...",
         "amendment_number": null, "percent": 6.2, "shares": 3700000,
         "class_label": "Class A common stock", "change_pct_points": null,
         "change_shares": null, "accession_number": "...", "source_url": "..."},
        {"form": "SCHEDULE 13D/A", "filed_date": "2026-10-02", "amendment_number": 2,
         "percent": 9.1, "shares": 5400000, "class_label": "Class A common stock",
         "change_pct_points": 2.9, "change_shares": 1700000, "accession_number": "...",
         "source_url": "..."}
      ],
      "status": "current"
    }
  ],
  "coverage": {"from": "2024-12-18", "note": "Structured Schedules 13D since December 2024; older free-text schedules are not read."},
  "labels": {"disclaimer": "Information, not signals. Not investment advice."},
  "notes": ["..."]
}
```

### Field rules

- **A chain** is one filer's original 13D and its 13D/As about the company, in filing order. The
  filer is the filing agent's subject filer (the `filer` the SEC records); when a 13D/A is filed
  by a different member of the same group (a reporting person in common), it joins that chain.
- **`group`**: every reporting person on the latest filing, as filed (name, CIK when given, type
  code: IA, IN, PN, CO, ...). A group filing (several reporting persons) has one chain, never one
  per person. `current.percent` is the group's figure as the filing gives it: the largest
  aggregate percent a reporting person reports (each person's line reports the group's shares it
  is deemed to own), never a sum across persons (that would count the same shares again).
- **`change_pct_points`**: this filing's percent minus the previous filing's in the chain, in
  percentage points (derived); `null` on the first. Shares change likewise in `change_shares`.
- **`status`**: `current` when the latest filing's percent is 5 or more; `exited` when it reports
  less than 5% (the filer's exit amendment). `status=all` includes exited chains.
- **`switched_from_13g`** (derived): the same filer (or a reporting person in common) filed a
  13G or 13G/A about the company before its first 13D in this chain: passive to active. `null`
  otherwise. Only structured 13Gs (December 2024 on) are compared.
- **`purpose`**: Item 4 of the **latest filing that states one**, as filed: the first 600
  characters, cut at a sentence end where possible, with `truncated` and the filing's link for
  the full text. It is **quoted, never summarised, never generated by a model**. An amendment
  that says Item 4 is unchanged keeps the earlier statement (its own filing is in the chain).
- Links are sec.gov/Archives filing pages only; no API URLs, CUSIPs or fetch times.

## 2. `GET /v1/activists?since=&until=&kind=&min_percent=&limit=&offset=`

Across companies: "new activist stakes this month".

| Parameter | Values | Default |
|---|---|---|
| `since`, `until` | filing dates, at most 366 days apart | the last 30 days |
| `kind` | `new` (original 13Ds), `increased`, `decreased`, `exited`, `switched` (13G to 13D), `all` | `new` |
| `min_percent` | 5-100 | none |
| `limit`, `offset` | 1-100, 0-5,000 | 50, 0 |

```json
{
  "data": [
    {"company": {"cik": "...", "name": "...", "ticker": "..."},
     "filer": {"name": "...", "cik": "..."}, "group_size": 2,
     "kind": "new", "form": "SCHEDULE 13D", "filed_date": "2026-11-18",
     "event_date": "2026-11-14", "amendment_number": null,
     "percent": 6.2, "shares": 3700000, "class_label": "Common stock",
     "change_pct_points": null, "switched_from_13g": null,
     "purpose": {"excerpt": "...", "truncated": true, "form": "SCHEDULE 13D",
                 "filed_date": "2026-11-18", "accession_number": "...",
                 "carried_forward": false, "source_url": "..."},
     "accession_number": "...", "source_url": "https://www.sec.gov/Archives/..."}
  ],
  "meta": {"limit": 50, "offset": 0, "has_more": false, "next_offset": null},
  "coverage": {"from": "2024-12-18", "note": "..."},
  "labels": {"disclaimer": "Information, not signals. Not investment advice."}
}
```

- One row per filing (sorted by filing date, newest first); `kind` from the chain: `new` is an
  original 13D, `increased`/`decreased` an amendment whose percent moved by 0.1 points or more,
  `exited` one that reports under 5%, `switched` an original 13D whose filer filed a 13G first,
  `amended` any other amendment (and a chain's first structured filing when it is a 13D/A).
  `kind=new` returns every original 13D, switched ones included (their `kind` reads `switched`);
  `kind=all` every filing. `switched_from_13g` is given on switched rows. The demo key: at most
  10 rows, from showcase companies only (as the insider screener).

## Errors and access

- `404 company_not_found`; `422 invalid_parameter` for a window over 366 days or bad values.
- The demo key: showcase companies only on the per-company view; at most 10 rows across
  companies, trimmed with a note.
- Usual rate and plan limits.

## MCP and chat (after the API)

- MCP tools `company_activists` and `activist_stakes`.
- Chat answers "who are the activists at X", "new activist stakes this month" with the rows,
  each linked to its filing, the purpose quoted as filed, and the disclaimer.

## Gate before release

- Load (Item 4 text): dry run with counts (filings read, with Item 4, unchanged-statement
  amendments, failed), then the write.
- Hand-check 30 filings against the XML on Archives (at most 1 wrong): the chain each joins,
  percent and shares, the change from the previous filing, the purpose excerpt (verbatim), and
  the 13G-to-13D flag; including a 13D/A chain of three or more, a group filing with several
  reporting persons, an exit amendment under 5%, and a switch from 13G.
- R-2: p95 under 500 ms for both endpoints.

## Build notes (2026-11-25)

- **ui's 9 points, all in:** (1) `purpose` cites the filing that states it (`form`,
  `filed_date`, `accession_number`, `source_url`), which may be older than `current`;
  `carried_forward` is true then. (2) `class_label` on `current`, each chain entry and the
  cross-company rows: the plain label of the schedule's class title as filed (the XML's
  `securitiesClassTitle`, through the 13F class labels; an unclear title stays as filed).
  (3) `event_date` beside `filed_date` on the cross-company rows. (4) `group[].type_label` in
  plain words, from the API. (5) `amendment_number` on amendments, as filed (`amendmentNo`).
  (6) `excerpt` is plain text, whitespace collapsed, the first 600 characters of Item 4's own
  text (`transactionPurpose`, no heading), cut at a sentence end (or `; `) where one falls after
  the first 200 characters, else at a word. (7) Order: current chains by `current.percent`,
  largest first, then exited chains by exit `filed_date`, latest first. (8) An exited chain's
  `current` is the exit filing (under 5%). (9) Demo rows across companies come from showcase
  companies only.
- **Chains:** a filing joins an earlier chain about the same company when they share the
  filer CIK or a reporting person's CIK; an original 13D after the chain exited starts a new
  chain. `filer` is whoever filed the chain's first structured 13D (a group member may file
  later amendments; `group` is the latest filing's reporting persons).
- **Exited** means a fall under 5% from an earlier filing at 5% or more in the chain (`status`
  and `kind` alike). A group whose members each report only their own shares can file under 5%
  throughout (FONAR's 57-person buyout group: 1.95% at most): its chain stays `current`, and
  its `percent` is the largest a single reporting person reports, as filed.
- **Moves** are compared to 4 decimals (18.1 to 18.2 is an increase of 0.1 points).
- **Gate (2026-11-25):** 30 filings against their XML (chains of 3 or more, group filings,
  exits, switches, carried statements, truncated Item 4): figures, shares, amendment numbers,
  classes and quotes all right; two rule faults found (FONAR read as exited, Bitdeer's 0.1 move
  as amended), fixed and proven; a fresh 30 after the fix had none. In-process: per company
  about 25 ms; across companies 0.2 s for 30 days, about 1 s for a full year when first built,
  then about 10 ms from a per-process cache that is rebuilt when a 13D or 13G row is added.
- **Unchanged:** an amendment whose Item 4 is short (400 characters or fewer) and says it is
  unchanged or not amended does not state a purpose; the earlier statement is quoted, citing
  its own filing.
- **Storage:** `schedule_13d_purposes` gains `class_title` and `amendment_number` (migration
  b2c4d6e8f0a3), filled from the cached XML by `scripts/load_13d_purposes.py` (10,463 filings;
  10,463 with a class, 8,325 with an amendment number); new 13Ds read for the holders view store
  them too.


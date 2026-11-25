# Q-01 Full-text search inside filings

`GET /v1/search/filings?q=&cik=&form=&section=&filed_from=&filed_to=&sort=&limit=&offset=`

Finds stored filing sections whose text matches the query and returns one hit per section, with its
filing, a snippet and the Archives link to the document the section was read from. Only text this
service has stored is searched; `coverage` says what that is (it is computed from the data, not
written by hand). `/v1/search` (companies plus passages) stays as it is; this endpoint is the one for
the search page, the MCP tool and the chat question "which filings mention …".

| Parameter | Values | Default |
|---|---|---|
| `q` | 2-200 characters; syntax below | required |
| `cik` | one CIK (with or without leading zeros) | none |
| `form` | comma-separated forms, e.g. `10-K,S-1`. A form includes its amendments (`S-1` finds `S-1/A`) | none |
| `section` | `annual_report`, `prospectus`, `earnings_release`, `8k_officers`, or one item code from `coverage` (e.g. `10k:1A`) | none |
| `filed_from`, `filed_to` | ISO dates, inclusive, on the filing date. `filed_to` is the as-of date: nothing filed after it | none |
| `sort` | `date` (newest filing first) or `relevance` | `date` |
| `limit` | 1-50 | 20 |
| `offset` | 0-500 | 0 |

## Query syntax

- `supply chain`: every word must appear in the section, in any order. Words are matched on their
  English stem (`tariffs` finds `tariff`). Common words (`the`, `of`, …) are ignored.
- Stems are PostgreSQL's English stemmer, so `activations` (stem `activ`) also finds
  `activities`. A quoted single word is matched by its stem too; only phrases of two or more
  words are matched exactly.
- `"going concern"`: a quoted phrase. **Every hit contains the phrase itself**: the words, in that
  order and next to each other, ignoring case and the punctuation or line breaks between them, with
  no stemming (`"material weakness"` does not find `material weaknesses`). Phrases and words mix:
  `"going concern" substantial doubt`.
- `tariff or duties`: either side may match.
- `-china`: a word or quoted phrase after `-` must not appear.

A query with no searchable word (only common words or symbols) is `422 invalid_query`.

## Response

```json
{
  "query": {
    "q": "\"going concern\" substantial doubt",
    "phrases": ["going concern"],
    "words": ["substantial", "doubt"],
    "excluded": [],
    "filters": {"cik": null, "form": ["10-K"], "section": null,
                "filed_from": "2025-01-01", "filed_to": null},
    "sort": "date"
  },
  "hits": [
    {
      "cik": "0001234567",
      "company": "Example Therapeutics, Inc.",
      "ticker": "EXTX",
      "filing": {
        "accession_number": "0001234567-26-000012",
        "form": "10-K",
        "filed_date": "2026-03-14",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000012/extx-20251231.htm"
      },
      "section": {"item": "10k:7",
                  "title": "Item 7. Management's Discussion and Analysis"},
      "snippet": "… these conditions raise substantial doubt about the Company's ability to continue as a going concern within one year …",
      "highlights": [[22, 39], [91, 104]],
      "relevance": null
    }
  ],
  "meta": {"limit": 20, "offset": 0, "has_more": true, "next_offset": 20},
  "coverage": [
    {"section": "earnings_release", "items": ["ex:99.1"], "forms": ["8-K", "8-K/A"],
     "sections": 12889, "companies": 1668, "first_filed": "2023-11-30", "last_filed": "2026-11-20"},
    {"section": "prospectus", "items": ["pr:risk", "pr:use", "..."], "forms": ["S-1", "F-1", "424B4", "..."],
     "sections": 6222, "companies": 365, "first_filed": "2010-04-09", "last_filed": "2026-11-23"},
    {"section": "annual_report", "items": ["10k:1A", "10k:7"], "forms": ["10-K", "10-KT"],
     "sections": 1152, "companies": 297, "first_filed": "2024-02-28", "last_filed": "2026-11-18"},
    {"section": "8k_officers", "items": ["5.02"], "forms": ["8-K", "8-K/A"],
     "sections": 35, "companies": 8, "first_filed": "2024-04-16", "last_filed": "2026-10-30"}
  ],
  "notes": ["Searches the filing sections this service has stored (see coverage), not every filing on EDGAR."]
}
```

(The coverage figures above are today's local data, for illustration.)

## Field rules

- **One hit per section.** A filing can appear more than once when several of its sections match
  (a 10-K's Item 1A and Item 7); each is its own hit with its own section.
- `filing.source_url` is the sec.gov/Archives document the section was read from. No other link is
  given: no API URLs, no fetch or detection times.
- `snippet` is plain text, about 35 words, cut around the place where most query terms meet. It has
  no HTML. `highlights` are `[start, end)` character offsets into `snippet` for each phrase or word
  occurrence shown, so the page can mark them without parsing. A stemmed word is highlighted as the
  word that appears in the text (`tariffs`). Only words PostgreSQL stems to the query word's own
  stem are highlighted, never words that merely start the same way: `going` (stem `go`) marks
  `going` and `go`, never `goods`, `governance` or `government` (fixed 2026-11-25; before,
  snippets and `section_offset` could sit on such words). Unquoted words match anywhere in the
  section, so `going concern` without quotes may show `concerns` alone; quote it for the phrase.
- **`section_offset`** (Q-09, Items 1A and 7 only; `null` for other sections): where the hit starts in
  the item's text as filed, the `text` that `/v1/filings/{accession}/sections/{item}` returns, so
  `text[section_offset:]` begins with the matched phrase or word and a reader can open at it.
- `relevance` is between 0 and 1 with `sort=relevance`, and `null` with `sort=date`. Under
  relevance, a section whose title names the query (`risk factors`) ranks higher; ties go to the
  newer filing. Relevance ranks the newest 2,000 matching sections (ranking reads each section's
  stored index; a note says so); narrow with filters to rank older ones.
- With a quoted phrase, sections are checked for the phrase as written; if 5,000 have been checked
  (or 800 read in full) without filling the page, the page ends there with a note.
- `company` is the company's current name; `ticker` is its primary ticker or `null`.
- No total count: `has_more` says whether another page exists. Pages stop at `offset` 500; narrow
  the query or the filters to see past that.
- `coverage` is the same for every query (it is not filtered) and is recomputed at most hourly.

## Errors and access

- `422 invalid_query`: no searchable word, or more than 8 phrases. `422 invalid_parameter`: a bad
  CIK, form, section, date or range (`filed_from` after `filed_to`).
- The demo key sees hits from the public showcase companies only, at most 10 per page, with
  `has_more` false and a note saying the list was trimmed. `cik` outside them is `403 demo_scope`.
- Usual rate limits and plan limits apply; a search is one request.

## MCP and chat

- The MCP tool `search_filings` moves to this endpoint, with the same parameters (`query` for `q`,
  `as_of` for `filed_to`).
- Chat answers "which filings mention X", "who talks about X in their risk factors" and similar
  questions with the top hits as cited passages, each linked to its document, and says what the
  search covers when no hit is found.

## Gate before release

- A dry run of 30 random queries (taken from words and phrases in stored sections, plus 10 written
  by hand), then a hand-check of 30 random hits: each contains every phrase as written and every
  word (by stem), excludes `-` terms, and its link opens the document holding the snippet. At most 1
  wrong.
- R-2: p95 under 500 ms over the query set, for both sorts, on a warm local server.

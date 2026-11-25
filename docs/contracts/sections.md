# Q-09 Sections: a 10-K item's text as filed

Status: **contract** (2026-11-25, PM go), for ui; building.

A 10-K item's text as filed, cut out of the annual report's own document, with its heading, a
link to that document on EDGAR Archives, and where in the document the text sits. The text is
never summarised or rewritten.

## Source and coverage

- **Items held:** 10-K Item 1A (Risk Factors) and Item 7 (Management's Discussion and Analysis).
  These are the items read for "What changed" (X-14, `app/services/tenk_sections.py`): the two
  latest 10-Ks (10-K, 10-K405, 10-KT) of the read set, about 290 companies (the showcase, then
  the largest filers by revenue). Today: 656 Item 1A and 654 Item 7 sections. Other items, and
  10-Ks outside the read set, are not held (404, below).
- **Document:** the filing's primary document on EDGAR Archives, read once through the SEC
  client and cached.

## 1. `GET /v1/filings/{accession}/sections`

The items held for one filing.

```json
{"accession_number": "0000320193-26-000026", "cik": "0000320193", "form": "10-K",
 "filed_date": "2026-10-31", "report_date": "2026-09-26",
 "items": [{"item": "1A", "title": "Risk Factors", "characters": 86211},
           {"item": "7", "title": "Management's Discussion and Analysis", "characters": 17402}],
 "coverage": "Items 1A and 7 of the latest two 10-Ks for about 290 companies are held; other items are not read yet."}
```

## 2. `GET /v1/filings/{accession}/sections/{item}`

`item`: `1A` or `7`. (The example's dates, counts and offsets are illustrative.)

```json
{
  "accession_number": "0000320193-26-000026",
  "cik": "0000320193",
  "company": "Apple Inc.",
  "form": "10-K",
  "filed_date": "2026-10-31",
  "report_date": "2026-09-26",
  "item": "1A",
  "title": "Risk Factors",
  "heading": "Item 1A. Risk Factors",
  "text": "The Company's business, reputation, results of operations ...",
  "subheadings": [
    {"group": true, "start": 103412, "end": 103444},
    {"group": false, "start": 103446, "end": 103598}
  ],
  "document": {"url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm",
               "name": "aapl-20260926.htm"},
  "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/0000320193-26-000026-index.htm",
  "offsets": {"start": 103321, "end": 189532,
              "basis": "characters in the document's text as read: its paragraphs, in order, joined by a blank line"},
  "notes": ["Text as filed, from the document linked; never summarised."]
}
```

### Field rules

- **`text`** is the item as filed (our stored "#"/"##" heading markers are never in a response): the document's paragraphs, from the paragraph after the item
  heading to the paragraph before the next item's heading (Item 1B, 1C or 2 after 1A; Item 7A or
  8 after 7), in order, joined by a blank line. No markup: tables become their cells' text in
  reading order. Page furniture is dropped (a lone page number, "Table of Contents"). Nothing is
  reworded, reordered or summarised.
- **`heading`** is the item's own heading paragraph as filed ("Item 1A. Risk Factors"; some
  filers write "ITEM 1A. RISK FACTORS"). `title` is the standard name of the item.
- **`offsets`** place `text` in the document's text as read: that text, sliced from `start` to
  `end`, is exactly `text`. Offsets count characters, not bytes, and are not positions in the
  HTML. The table of contents is never the match: the item heading with the longest run before
  the next item's heading is the one taken.
- **`subheadings`** are given only as offsets, on the same basis: the paragraphs set in bold or
  italics within the item (`group: true` for a group heading such as "Macroeconomic and Industry
  Risks"); their words are the slice. They are `[]` when the item has none that the splitter can
  read.
- **Reproducing a slice.** Read the document at `document.url`. Take each block element's text in
  order (`p`, `div`, `tr`, `li`, `td`, headings, line breaks), entities decoded, runs of white
  space collapsed to one space, empty paragraphs dropped, and join the paragraphs with "\n\n". For
  example, if the paragraphs are "Item 1A. Risk Factors", "The Company's business ...", "Item 1B.
  Unresolved Staff Comments", the text as read is "Item 1A. Risk Factors\n\nThe Company's business
  ...\n\nItem 1B. Unresolved Staff Comments". `text` is then that string from `start` (just after
  "Item 1A. Risk Factors\n\n") to `end` (just before "\n\nItem 1B"). The reader is
  `app/services/tenk_sections.py` (`paragraphs`, open source in this repository).
- **`document.url`** is the primary document on EDGAR Archives (an Archives link, as on every
  other figure); `filing_url` is the filing's index page.
- A 10-K/A is a filing of its own: its items are held only when it was read.

## Errors and access

- 404 `filing_not_found` for an unknown accession.
- 404 `section_not_held`: the item is not held for this filing. The message lists the items held
  for it, if any, and says plainly: "Items 1A and 7 of the latest two 10-Ks for about 290
  companies are held; other items are not read yet." Nothing implies that every item exists.
- 422 for an item other than `1A` or `7`.
- Readers' keys; the demo key covers the showcase companies.

## MCP and chat

- MCP tool `filing_section` (accession, item): the response above; its description says to quote
  `text` only as filed with `document.url`, never to summarise it as the filing's words.
- Chat may quote a section's opening lines as filed, with the document link, and say where the
  rest is; it never summarises a section as the filing's own words.

## Build (pv)

- **Storage:** the stored section (`filing_sections`, items `10k:1A` and `10k:7`) gains the start
  and end offsets, the heading as filed, the subheadings' offsets and the document's name. These
  are set when an item is read, and a backfill recomputes them from the cached documents (no SEC
  requests; a document not cached is counted and left as it is).
- **Gate:** AAPL, META and BA, both items of their latest 10-K. Each document is fetched from
  EDGAR Archives through the SEC client and its text is read the same way. The check passes when
  the text sliced at `offsets` equals `text`, the heading paragraph just before `start` reads as
  the item's heading, and the paragraph just after `end` is the next item's heading. All six must
  match; then 30 random items of the read set are checked the same way, with at most 1 that does
  not match.

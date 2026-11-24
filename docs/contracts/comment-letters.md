# D-13 SEC comment letters

**Built 2026-11-24.** Additive: topic keys `governance` (board leadership, Item 407, risk
oversight) and `leases` (ASC 842); `kind` can be `no_review` (the staff did not review the
filing: it closes the thread and its thread has no topics). Thread topics come from the SEC's own
letters; a response's wording counts only when no SEC letter of the thread is readable. Read set:
the 23 showcase companies and the 100 largest USD filers, letters from 2019 (878 read, 873
readable). Topic hand-check: 40 threads, 37 right, 2 doubtful, 1 fixed by rule.

`GET /v1/companies/{cik}/comment-letters?since=&topic=&limit=`

**Source.** The SEC releases its review correspondence on EDGAR at least 20 business days after
a review closes. SEC letters to the company are UPLOAD filings, usually PDF. The company's
responses are CORRESP filings, usually HTML. Both are already in our filings index. The text of
each letter is read once, through our SEC client, to find its topics and file number. Topics
come from a reviewed keyword list, not a model.

| Parameter | Values | Default |
|---|---|---|
| `since` | ISO date: threads with any letter on or after it | five years before today |
| `topic` | one topic key (below) | none |
| `limit` | 1-100 threads | 20 |

```json
{
  "cik": "0000320193",
  "threads": [
    {
      "id": "0000000000-24-003120",
      "file_number": "001-36743",
      "subject": "Form 10-K for the Fiscal Year Ended September 30, 2023",
      "opened": "2024-03-06",
      "closed": "2024-05-16",
      "status": "closed",
      "topics": ["segments", "non_gaap"],
      "letters": [
        {"date": "2024-03-06", "from": "sec", "form": "UPLOAD",
         "accession_number": "0000000000-24-003120", "topics": ["segments"],
         "source_url": "https://www.sec.gov/Archives/..."},
        {"date": "2024-03-20", "from": "company", "form": "CORRESP",
         "accession_number": "0000320193-24-000031", "topics": ["segments"],
         "source_url": "https://www.sec.gov/Archives/..."}
      ]
    }
  ],
  "topic_keys": {"revenue_recognition": "Revenue recognition", "non_gaap": "Non-GAAP measures",
                 "segments": "Segment reporting", "impairment": "Impairment",
                 "mdna": "MD&A", "income_taxes": "Income taxes", "disclosure_controls":
                 "Disclosure controls", "climate": "Climate disclosure", "cybersecurity":
                 "Cybersecurity", "crypto": "Crypto assets", "going_concern": "Going concern",
                 "related_parties": "Related parties", "other": "Other"},
  "notes": ["Topics are tagged from a reviewed keyword list; a letter can have several."]
}
```

Rules:
- **Threads.** Letters are grouped into one review by the SEC file number quoted in the letter
  (or in the filing header when the letter does not quote one). A gap of more than 180 days
  between letters with the same file number starts a new thread.
  - `id` is the accession number of the thread's first letter.
  - `subject` is the "Re:" line of the first SEC letter, when it can be read.
  - `status` is `closed` when an SEC letter says the staff "completed its review" (`closed` is
    that letter's date). Otherwise it is `open_or_unknown`.
- A letter whose text cannot be read (for example a scanned PDF) is still listed, with
  `topics: []` and `"readable": false`.
- `from` is `sec` for UPLOAD and `company` for CORRESP. A CORRESP that is only an acceleration
  request (a request to make a registration statement effective) is tagged
  `"kind": "acceleration_request"` and kept out of `topics`.
- **Coverage.** Letters filed from 2019 onward, for the companies in the read set. The response
  says `"coverage": "not_read"` with the letters listed but untagged when the company is outside
  it.

| Status | When |
|---|---|
| 200 | threads (may be empty) |
| 404 `company_not_found` | unknown CIK |

Events: none in this window. MCP: the `comment_letters` tool, `{cik, topic?, since?}`.

Chat (C-16): intent `comment_letters` ("Has the SEC sent Apple any comment letters?", "SEC
staff comments", "CORRESP"). The answer counts the reviews of the last five years (by `as_of`:
letters filed later are left out, so a review closed later reads as open), gives the latest
review's file number, topics and closing date cited to its first letter, and the most frequent
topics; a table block lists every review (opened, linked to its first letter; closed; file
number; subject; topics; letters). A company whose letters were not read gets the filings list
and says the topics are not known. No new reply fields.

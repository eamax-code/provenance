"""Clean chatbot residue out of model answers (issue #7, proof of concept).

The patterns follow blader/humanizer (MIT, https://github.com/blader/humanizer), itself based on
Wikipedia's "Signs of AI writing". The model's instructions already ask for plain, short answers;
this pass removes what a small local model still produces. It only deletes wrappers and swaps
punctuation, so it never changes a figure, a date or a citation.
"""

from __future__ import annotations

import re

# §22 Chatbot residue: greetings, praise and offers that wrap the content.
_OPENERS = re.compile(
    r"^\s*(?:(?:great|good|excellent) question[.!]?|certainly[.!,]?|sure[.!,]?|of course[.!,]?|"
    r"absolutely[.!,]?|happy to help[.!]?)\s*",
    re.IGNORECASE,
)
_CLOSERS = re.compile(
    r"\s*(?:I hope (?:this|that) helps[.!]?|Let me know if[^.!?]*[.!?]|Feel free to[^.!?]*[.!?]|"
    r"Would you like[^?]*\?|Want me to[^?]*\?|If you (?:have|need) (?:any )?(?:more|further|other)"
    r"[^.!?]*[.!?])\s*$",
    re.IGNORECASE,
)
# §25/§26 Writing about the source and re-explaining: "Based on the provided filings, …".
_SOURCE_LEADS = re.compile(
    r"\b(?:Based on|According to|From|Per) (?:the )?(?:provided |available |given )?"
    r"(?:CONTEXT|context|data|information|filings|SEC data)(?: provided)?,\s*",
)
_CONTEXT_WORD = re.compile(r"\bthe (?:provided |given )?CONTEXT\b", re.IGNORECASE)
_CONTEXT_VERB = re.compile(
    r"\b([Tt]he )(?:provided |given )?CONTEXT (does|doesn't|has|is|isn't|mentions|shows)\b"
)
_PLURAL_VERBS = {
    "does": "do", "doesn't": "don't", "has": "have", "is": "are", "isn't": "aren't",
    "mentions": "mention", "shows": "show",
}  # fmt: skip
# §2 One-line closers and recaps that restate the answer.
_RECAP = re.compile(
    r"(^|(?<=[.!?]\s))(?:Therefore|Thus|In summary|In conclusion|Overall|To sum up),\s*(\w)",
    re.IGNORECASE,
)
# §8 Dashes as the universal connector; §21 curly quotes.
_DASH = re.compile(r"\s+[—–]\s+|—")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
# §12 A few overused words with plain replacements that keep the meaning.
_WORDS = {
    r"\bAdditionally,\s*": "Also, ",
    r"\bNotably,\s*": "",
    r"\bIt is worth noting that\s*": "",
    r"\bIt's worth noting that\s*": "",
    r"\bIt is important to note that\s*": "",
}


def clean(text: str) -> str:
    """The answer without greetings, sign-offs, recaps, source talk, dashes or curly quotes."""
    if not text:
        return text
    out = text.translate(_QUOTES)
    out = _OPENERS.sub("", out)
    for _ in range(3):
        stripped = _CLOSERS.sub("", out)
        if stripped == out:
            break
        out = stripped
    out = _SOURCE_LEADS.sub(lambda m: "", out)
    out = _CONTEXT_VERB.sub(lambda m: m.group(1) + "filings " + _PLURAL_VERBS[m.group(2)], out)
    out = _CONTEXT_WORD.sub("the filings", out)
    out = _RECAP.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    for pattern, repl in _WORDS.items():
        out = re.sub(pattern, repl, out)
    out = _DASH.sub(", ", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    # An answer that now starts in lower case after a removed lead gets its capital back.
    return out[:1].upper() + out[1:]

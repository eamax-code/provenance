"""S-05: fiscal-year names follow the company's own 10-K wording, never its DEI tag alone."""

from collections import Counter
from datetime import date

from app.services import fiscal_convention as fc
from app.services import periods


def _offset(text: str, fye: str | None) -> int | None:
    return fc.wording_offset(fc.wording(f"<html><body><p>{text}</p></body></html>", fye))


def test_wording_states_the_start_year_name():
    # Gap / Home Depot: a year ending in January named by the year it starts in
    assert _offset("Fiscal 2025 ended on January 31, 2026 and consisted of 52 weeks.", "0201") == -1
    assert (
        _offset("fiscal 2025 Fiscal year ended February 1, 2026 (includes 52 weeks)", "0131") == -1
    )
    assert _offset("the year ended January 27, 2017 (&ldquo;fiscal 2016&rdquo;).", "0131") == -1


def test_wording_states_the_end_year_name():
    # 99 Cents Only: its DEI tags 2016, its 10-K names the year ended January 2017 fiscal 2017
    text = ("Our fiscal year 2017 (&ldquo;fiscal 2017&rdquo;) began on January 30, 2016 and "
            "ended January 27, 2017 and consisted of 52 weeks.")  # fmt: skip
    assert _offset(text, "0127") == 0


def test_no_dated_wording_means_no_offset():
    # Mentor Graphics: "During the fiscal year ended January 31, 2017" names no fiscal year
    assert (
        _offset("During the fiscal year ended January 31, 2017, we continued ...", "0131") is None
    )
    assert _offset("Fiscal 2012 consisted of 53 weeks.", "0202") is None


def test_quarters_and_comparisons_are_not_mappings():
    # a quarter's end, or a second period between the two, would give a wrong mapping
    assert _offset("the second quarter of fiscal 2025 ended August 2, 2025", "0131") is None
    assert _offset("fiscal 2025 ended August 2, 2025", "0131") is None  # not the year-end month
    assert (
        _offset("Sales in fiscal 2025 compared to the year ended February 1, 2025", "0131") is None
    )
    assert _offset("fiscal 2024 and the fiscal year ended February 1, 2026", "0131") is None
    # within a month of the year end, so only the part-of-year words exclude it
    assert _offset("fiscal 2025 transition period ended December 31, 2025", "0131") is None


def test_disagreeing_wording_is_no_offset():
    assert fc.wording_offset(Counter({-1: 2, 0: 2})) is None
    assert fc.wording_offset(Counter({-1: 3, 0: 1})) == -1
    assert fc.wording_offset(Counter({-3: 5})) is None  # not a convention


def test_the_offset_names_every_year_and_dei_disagreements_are_only_listed():
    # Lands' End: one DEI year tagged otherwise; splitting the history there would name two
    # years FY2022, so the offset applies throughout and the stray year is only listed
    rows = [(date(y, 1, 31), 0 if y == 2022 else -1, f"a{y}") for y in range(2016, 2027)]
    assert fc.dei_disagrees(rows, -1, "0131") == [2022]
    conv = ("0131", -1)
    labels = [periods.label(e, "annual", conv) for e, _, _ in rows]
    assert len(set(labels)) == len(labels) and labels[-1] == "FY2025" and labels[6] == "FY2021"
    assert periods.label(date(2025, 4, 30), "quarterly", conv) == "Q1 FY2025"
    assert periods.label_basis(conv) == "company's 10-K wording"
    assert periods.label_basis(("0131", None)) == "end-year rule"
    assert periods.label(date(2026, 1, 31), "annual", ("0131", None)) == "FY2026"


def test_only_statements_about_the_reported_year_count():
    # Xura's 10-K for December 2015 names a future January year after its change of year end
    xura = "the year ending January 31, 2017 (or fiscal 2016), we cannot assure you"
    assert fc.wording(xura, "1231", date(2015, 12, 31)) == Counter()
    assert fc.wording(xura, "1231") == Counter({-1: 1})


def test_figures_headers_and_sentences_between_are_not_mappings():
    dycom = "fiscal 2024: Fiscal Year Ended January 31, 2026 January 25, 2025 January 27, 2024"
    assert _offset(dycom, "0130") is None
    mexco = ("Fiscal 2025 We had net income of $1,305,722 for the year ended March 31, 2026, "
             "compared to")  # fmt: skip
    assert _offset(mexco, "0331") is None
    tata = "Fiscal 2022, the breakdown of which is as follows: Year ended March 31, 2023 2022"
    assert _offset(tata, "0331") is None
    assert fc.wording_offset(Counter({-2: 5, -1: 3, 0: 1})) is None  # mostly nonsense
    # a sentence, even without figures, is not a definition
    sentence = (
        "Fiscal 2025 we kept up a good pace in our home market for the year ended March 31, 2026"
    )
    assert _offset(sentence, "0331") is None


def test_candidates_are_proposed_by_the_dei_only():
    rows = {"a": [(date(2025, 1, 31), -1, "x"), (date(2026, 1, 31), -1, "y")],
            "b": [(date(2025, 12, 31), 0, "z")]}  # fmt: skip
    assert fc.candidates(rows) == ["a"]


def test_the_common_ways_filings_word_it():
    # each phrasing as a real 10-K has it (Claire's, Dell, Kyocera, Michaels, VF, Abercrombie)
    claires = ('Our fiscal year ended February 3, 2018 ("Fiscal 2017") consisted of 53 weeks, '
               'while both of our fiscal years ended January 28, 2017 ("Fiscal 2016") and '
               'January 30, 2016 ("Fiscal 2015") consisted of 52 weeks.')  # fmt: skip
    assert set(fc.wording(claires, "0203")) == {-1}  # no 0 from the next clause's date
    assert _offset('The fiscal years ended February 1, 2013 ("Fiscal 2013")', "0129") == 0
    kyocera = '"fiscal 2018" refers to Kyocera\'s fiscal year ended March 31, 2018'
    assert _offset(kyocera, "0331") == 0
    michaels = 'References to "fiscal 2020" relate to the 52 weeks ended January 30, 2021'
    assert _offset(michaels, "0130") == -1
    vf = ('All references to "Fiscal 2026" relate to VF\'s current fiscal year which ran from '
          "March 30, 2025 through March 28, 2026.")  # fmt: skip
    assert _offset(vf, "0328") == 0
    assert _offset('the years ended March 2026 ("Fiscal 2026")', "0328") == 0
    table = "Fiscal year Year ended / ending Number of weeks Fiscal 2025 January 31, 2026 52"
    assert _offset(table, "0130") == -1
    # a 13-week period is a quarter, even near the year end
    assert _offset("fiscal 2025 relates to the 13 weeks ended January 31, 2026", "0131") is None


def test_a_glossary_or_list_never_pairs_a_date_with_the_next_name():
    # Constellation's glossary and Hawkins' list: each date belongs to the name before it
    glossary = ("Fiscal 2025 the Company's fiscal year ended February 28, 2025 Fiscal 2026 the "
                "Company's fiscal year ended February 28, 2026 Fiscal 2027")  # fmt: skip
    assert set(fc.wording(glossary, "0228")) == {0}
    hawkins = ('"fiscal 2026" means our fiscal year ended March 29, 2026, "fiscal 2025" means '
               "our fiscal year ended March 30, 2025")  # fmt: skip
    assert set(fc.wording(hawkins, "0328")) == {0}


def test_offsets_are_measured_against_the_end_year_rule():
    # Soho House: a year ending in the first days of January is already the year before
    assert _offset('the year ended on January 1, 2023 ("Fiscal 2022")', "0102") == 0


def test_a_rejected_match_does_not_hide_the_valid_one_inside_it():
    five_below = ('References to "fiscal year 2026" or "fiscal 2026" refer to the period from '
                  "February 1, 2026 to January 30, 2027.")  # fmt: skip
    assert _offset(five_below, "0130") == -1


def test_a_list_of_dates_is_not_a_mapping():
    # Dollar Tree: which name goes with which date is not said
    dollar_tree = "fiscal 2025 and fiscal 2024, which ended January 31, 2026 and February 1, 2025"
    assert fc.wording(dollar_tree, "0130", date(2026, 1, 31)) == Counter()


def test_naming_the_reported_year_needs_no_stored_year_end():
    # 99 Cents Only moved its year end from March to January; the stored "0330" is stale
    text = ('Our fiscal year 2017 ("fiscal 2017") began on January 30, 2016 and ended January '
            "27, 2017")  # fmt: skip
    assert set(fc.wording(text, "0330", date(2017, 1, 27))) == {0}
    # "refer to ... as" names the year too (dELiA*s)
    delias = 'We refer to the 52-week fiscal year ended February 1, 2014 as "fiscal 2013,"'
    assert fc.wording(delias, "1231", date(2014, 2, 1)) == Counter({-1: 1})

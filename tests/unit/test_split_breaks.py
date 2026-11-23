"""Statements flag adjacent years on different share bases (PM, 2026-11-23): flag only."""

from app.services.statements import split_breaks

KEYS = ["FY2015", "FY2016", "FY2017", "FY2018", "FY2019", "FY2020"]
# Apple as stored: FY2015-17 from the 10-Ks of the time, FY2018-20 restated for the 2020 4:1 split
APPLE = {
    "shares_basic_weighted": [5_753_421e3, 5_470_820e3, 5_217_242e3, 19_821_510e3, 18_471_336e3,
                              17_352_119e3],
    "shares_diluted_weighted": [5_793_069e3, 5_500_281e3, 5_251_692e3, 20_000_435e3,
                                18_595_651e3, 17_528_214e3],
    "eps_basic": [9.28, 8.35, 9.27, 3.00, 2.99, 3.31],
    "eps_diluted": [9.22, 8.31, 9.21, 2.98, 2.97, 3.28],
    "net_income": [53_394e6, 45_687e6, 48_351e6, 59_531e6, 55_256e6, 57_411e6],
}  # fmt: skip


def test_apple_fy2017_fy2018_is_flagged_on_shares_and_eps_only():
    out = split_breaks(APPLE, KEYS)
    assert set(out) == {"shares_basic_weighted", "shares_diluted_weighted", "eps_basic",
                        "eps_diluted"}  # fmt: skip
    assert all(v == {"between": ["FY2017", "FY2018"], "ratio_hint": "4:1"} for v in out.values())


def test_a_reverse_split_reads_one_to_n():
    out = split_breaks({"shares_basic_weighted": [1e9, 1.02e8], "eps_basic": [0.5, 4.9]},
                       ["FY2023", "FY2024"])  # fmt: skip
    assert out["eps_basic"]["ratio_hint"] == "1:10"


def test_no_flag_without_an_inverse_eps_move_or_a_whole_factor():
    keys = ["FY2023", "FY2024"]
    sh = "shares_basic_weighted"
    # shares doubled in an acquisition and EPS held: income doubled too, not a split
    assert split_breaks({sh: [1e9, 2e9], "eps_basic": [2.0, 2.0]}, keys) == {}
    # a 2.5x jump is not near a whole factor
    assert split_breaks({sh: [1e9, 2.5e9], "eps_basic": [2.0, 0.8]}, keys) == {}
    # buybacks and ordinary moves
    assert split_breaks({sh: [1e9, 0.95e9], "eps_basic": [2.0, 2.4]}, keys) == {}
    # no EPS row (a balance sheet): nothing to confirm a split with
    assert split_breaks({"shares_outstanding": [1e9, 4e9]}, keys) == {}
    # a loss year: the signs differ, no comparison
    assert split_breaks({sh: [1e9, 4e9], "eps_basic": [2.0, -0.5]}, keys) == {}

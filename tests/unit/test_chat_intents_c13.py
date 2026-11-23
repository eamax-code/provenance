"""C-13: the new intents are found by their questions, and plain finance questions are not."""

from app.services.chat_intents import detect


def test_c13_intents():
    assert detect("Apple CEO pay") == "pay"
    assert detect("Tesla CEO pay vs TSR") == "pay"
    assert detect("JPMorgan executive compensation") == "pay"
    assert detect("Show me pay versus performance for Exxon") == "pay"
    assert detect("Who adopted 10b5-1 plans at NVIDIA?") == "trading_plans"
    assert detect("Did any insiders set up trading plans at Tesla?") == "trading_plans"
    assert detect("Any Form 144 notices at Apple?") == "proposed_sales"
    assert detect("What did Apple add to its risk factors?") == "changes"
    assert detect("What changed in Boeing's latest 10-K?") == "changes"
    for plain in ("Apple revenue", "Who audits Apple?", "Microsoft operating margin",
                  "Who are Apple's largest institutional holders?", "insider sales at Apple"):
        assert detect(plain) not in ("pay", "trading_plans", "proposed_sales", "changes"), plain

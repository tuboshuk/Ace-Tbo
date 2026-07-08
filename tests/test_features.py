from datetime import date

from wealth_lab.features import build_quote_from_bar
from wealth_lab.models import Bar


def test_build_quote_uses_previous_bars_only() -> None:
    previous = [
        Bar("000001", date(2026, 1, 1), 1, 10, 8, 9, 100),
        Bar("000001", date(2026, 1, 2), 1, 12, 7, 10, 200),
    ]
    current = Bar("000001", date(2026, 1, 3), 1, 99, 1, 11, 300)

    quote = build_quote_from_bar(current, "test", previous)

    assert quote.high_20 == 12
    assert quote.low_20 == 7
    assert quote.volume_ratio == 2.0


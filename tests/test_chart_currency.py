"""차트 꼬리표의 통화 기호 — '$61.5' 처럼 금액 앞에 붙인 기호는 받고, 값 대조는 그대로 한다(2026-11-21)."""
import pytest

from ozl.render import charts as CH


def test_currency_prefix_matches_value():
    assert CH._display_matches("$61.5", 61.5) is True
    assert CH._display_matches("$1,234", 1234) is True
    assert CH._display_matches("-$3.5", -3.5) is True
    assert CH._display_matches("€20", 20) is True


def test_currency_prefix_still_checks_value():
    assert CH._display_matches("$61.5", 61.4) is False
    assert CH._display_matches("$$61.5", 61.5) is None      # 기호는 하나만
    assert CH._display_matches("$６１", 61) is None          # 전각 숫자는 꼴이 아니다
    assert CH._display_matches("1억 2,345", 123452345) is None


def test_old_forms_unchanged():
    for shown, v in (("4명", 4), ("123.93", 123.93), ("1,644,131", 1644131), ("-70.9%", -70.9), (".5%", 0.5)):
        assert CH._display_matches(shown, v) is True


def test_multiple_currency_symbols_anywhere_are_not_a_value():
    for shown, value in (("$61.5€", 61.5), ("-₩3$", -3), ("4원£¥", 4), ("3₹₹", 3)):
        assert CH._display_matches(shown, value) is None


def test_currency_with_trailing_sign_is_not_a_value():
    for label in ("$61.5-", "€61.5 −", "-₩61.5+", "61.5£-", "61.5+ ¥"):
        assert CH._display_matches(label, 61.5) is None


@pytest.mark.parametrize("sign", ["-", "−", "－", "+", "＋"])
def test_sign_after_currency_number_rejects_any_suffix(sign):
    for label in (f"$3{sign}", f"$3{sign}/주", f"3{sign}원/주₩"):
        assert CH._display_matches(label, 3) is None, label

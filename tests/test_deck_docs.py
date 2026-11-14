"""덱 절차 문서(skills/ozl/SKILL.md §5)가 agent/deck.md 의 style: syuka 규칙과 어긋나지 않는지 본다."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _section5() -> str:
    text = (ROOT / "skills/ozl/SKILL.md").read_text(encoding="utf-8")
    start = text.index("## 5. `build")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else None]


def test_skill_step6_follows_syuka_rules():
    s5 = _section5()
    step6 = next(line for line in s5.splitlines() if line.startswith("6. **덱 사양**"))
    assert "style: syuka" in step6
    assert "45장 상한 없음" in step6
    assert "outline --minutes" in step6
    assert "public-check" in step6
    # 옛 규칙(45장, 남의 사진 금지, 경고 0)은 옛 사양에만 걸린다
    new_part, old_part = step6.split("옛 사양", 1)
    for phrase in ("45장을 넘기지 않", "남의 사진과 지도는 쓰지 않", "경고 0"):
        assert phrase not in new_part, phrase
        assert phrase in old_part, phrase


def test_skill_done_criteria_do_not_demand_zero_warnings_for_syuka():
    s5 = _section5()
    done = next(line for line in s5.splitlines() if line.startswith("끝낼 기준"))
    assert "style: syuka" in done
    assert re.search(r"엄격 검사 실패 0·경고 0 ·", done) is None


def test_agent_deck_has_no_45_cap_for_syuka():
    deck = (ROOT / "agent/deck.md").read_text(encoding="utf-8")
    assert "45장 상한은 두지 않는다" in deck

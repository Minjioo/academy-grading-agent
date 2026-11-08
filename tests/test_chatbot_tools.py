"""LLM 호출 없이 툴 함수만 검증 (샘플 데이터 기준값: PLAN.md §0)"""
import json
from pathlib import Path

import pytest

from core.answer_key import parse_answer_key
from core.chatbot.tools import NOT_FOUND, make_tools, parse_student_no
from core.exam_parser import parse_exam
from core.grading import grade, summarize
from core.omr import load_omr

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture(scope="module")
def tools():
    key = parse_answer_key(SAMPLE / "answer.pdf")
    omr = load_omr(SAMPLE / "omr.xlsx")
    exam = parse_exam(SAMPLE / "exam.pdf")
    results = grade(omr, key)
    summary = summarize(results, key, omr)
    return {t.name: t for t in make_tools(results, summary, key, exam)}


def call(tools, name, args=None):
    return json.loads(tools[name].invoke(args or {}))


@pytest.mark.parametrize("text,no", [
    ("87", 87), ("87번", 87), ("87번 학생", 87), ("87학생", 87), ("학생 87", 87), ("905번 학생", 905), ("홍길동", None),
])
def test_parse_student_no(text, no):
    assert parse_student_no(text) == no


def test_tool_names(tools):
    assert set(tools) == {
        "get_score_summary", "get_student_result", "get_lowest_students", "get_top_students",
        "get_most_missed_questions", "get_question_for_generation", "get_question_text",
    }
    for t in tools.values():
        assert t.description  # 한국어 docstring


def test_score_summary(tools):
    s = call(tools, "get_score_summary")
    assert s["응시인원"] == 10
    assert s["평균"] == 65.2
    assert s["중앙값"] == 65.5
    assert s["표준편차_모집단"] == 19.6
    assert s["최고점"] == 92 and s["최저점"] == 31


@pytest.mark.parametrize("text", ["905", "905번", "905번 학생", "905학생"])
def test_student_result_formats(tools, text):
    r = call(tools, "get_student_result", {"student": text})
    assert r["학생명"] == "905학생"
    assert r["점수"] == 73
    assert isinstance(r["틀린문항"], list)


def test_student_not_found(tools):
    r = call(tools, "get_student_result", {"student": "87번 학생"})
    assert r["결과"] == NOT_FOUND


def test_lowest_and_top(tools):
    low = call(tools, "get_lowest_students", {"n": 1})
    assert [s["학생명"] for s in low["학생"]] == ["909학생"]
    assert low["학생"][0]["점수"] == 31
    top = call(tools, "get_top_students", {"n": 1})
    assert top["학생"][0]["학생명"] == "901학생" and top["학생"][0]["점수"] == 92


def test_lowest_includes_ties():
    import pandas as pd

    results = pd.DataFrame({
        "학생명": ["1학생", "2학생", "3학생"], "student_no": [1, 2, 3],
        "총점": [50, 30, 30], "정답 수": [5, 3, 3], "석차": [1, 2, 2], 1: ["O", "X", "X"],
    })
    summary = {"count": 3, "questions": [{"number": 1, "answer": 1, "points": 2, "wrong_count": 2, "wrong_rate": 66.7}],
               "total_points": 2}
    t = {x.name: x for x in make_tools(results, summary, {1: {"answer": 1, "points": 2}}, None)}
    low = json.loads(t["get_lowest_students"].invoke({"n": 1}))
    assert [s["학생명"] for s in low["학생"]] == ["2학생", "3학생"]


def test_most_missed(tools):
    r = call(tools, "get_most_missed_questions", {"n": 3})
    assert [q["문항"] for q in r["최다오답문항"]] == [21, 33, 42]
    assert r["최다오답문항"][0]["오답인원"] == 9


def test_question_for_generation(tools):
    r = call(tools, "get_question_for_generation", {"rank": 1})
    assert r["문항"] == 21
    assert "less sticky" in r["본문"]
    assert r["듣기문항"] is False
    assert "선택지별응답수" in r


def test_question_text(tools):
    r = call(tools, "get_question_text", {"number": 18})
    assert "Amanda Clark" in r["본문"]
    assert call(tools, "get_question_text", {"number": 99})["결과"].startswith("99번")


def test_outputs_are_short(tools):
    for name in ["get_score_summary", "get_lowest_students", "get_most_missed_questions"]:
        assert len(tools[name].invoke({})) < 1500


def _tied_tools():
    import pandas as pd

    results = pd.DataFrame({
        "학생명": ["1학생", "2학생"], "student_no": [1, 2], "총점": [2, 0], "정답 수": [1, 0], "석차": [1, 2],
        1: ["X", "X"], 2: ["O", "X"], 3: ["X", "X"], 4: ["O", "O"],
    })
    qs = [{"number": n, "answer": 1, "points": 2, "wrong_count": w, "wrong_rate": w * 50.0}
          for n, w in [(1, 2), (2, 1), (3, 2), (4, 0)]]
    summary = {"count": 2, "questions": qs, "total_points": 8}
    key = {n: {"answer": 1, "points": 2} for n in range(1, 5)}
    exam = {n: {"text": f"{n}번 본문", "is_listening": False} for n in range(1, 5)}
    return {x.name: x for x in make_tools(results, summary, key, exam)}


def test_most_missed_returns_all_ties():
    t = _tied_tools()
    r = json.loads(t["get_most_missed_questions"].invoke({"n": 1}))
    assert r["최다오답_동점문항"] == [1, 3]
    assert [q["문항"] for q in r["최다오답문항"]] == [1, 3]
    r2 = json.loads(t["get_most_missed_questions"].invoke({"n": 3}))
    assert [q["문항"] for q in r2["최다오답문항"]] == [1, 3, 2]


def test_generation_uses_lowest_numbered_tie():
    t = _tied_tools()
    r = json.loads(t["get_question_for_generation"].invoke({"rank": 1}))
    assert r["동점문항"] == [1, 3]
    assert r["문제생성_기준문항"] == 1 and r["본문"] == "1번 본문"


def test_finalize_answer_underline():
    from core.chatbot.agent import finalize_answer

    src = "**문제** 밑줄 친 <u>cut corners</u>의 의미는?\n**지문** Some firms cut corners to save money."
    out = finalize_answer(src)
    assert out.count("<u>cut corners</u>") == 2
    # 이미 두 번 표시돼 있으면 그대로
    assert finalize_answer(out) == out
    # 밑줄이 없는 답변은 손대지 않는다
    assert finalize_answer("평균은 65.2점입니다.") == "평균은 65.2점입니다."


def test_generation_first_line_lists_ties():
    t = _tied_tools()
    r = json.loads(t["get_question_for_generation"].invoke({"rank": 1}))
    assert r["첫줄"].startswith("가장 많이 틀린 문항: 1번, 3번 (각 오답 2명")
    assert "1번 기준" in r["첫줄"]


def test_finalize_answer_skips_single_words():
    from core.chatbot.agent import finalize_answer

    src = "**지문** wetlands ①<u>absorb</u> water.\n**선택지**\n① absorb"
    assert finalize_answer(src) == src  # 한 낱말 표시는 선택지까지 번지지 않는다


@pytest.mark.parametrize("rank,label", [(1, "가장 많이 틀린 문항"), (2, "2번째로 많이 틀린 문항"), (3, "3번째로 많이 틀린 문항")])
def test_rank_label(rank, label):
    from core.chatbot.tools import rank_label

    assert rank_label(rank) == label


def test_generation_first_line_by_rank(tools):
    # 샘플: 1위 21번(9명), 2위 33번(8명), 3위 42번(7명)
    r1 = call(tools, "get_question_for_generation", {"rank": 1})
    assert r1["문제생성_기준문항"] == 21 and r1["첫줄"].startswith("가장 많이 틀린 문항: 21번 (오답 9명")
    r2 = call(tools, "get_question_for_generation", {"rank": 2})
    assert r2["문제생성_기준문항"] == 33 and r2["순위"] == 2
    assert r2["첫줄"].startswith("2번째로 많이 틀린 문항: 33번 (오답 8명")
    assert "가장 많이" not in r2["첫줄"]
    r3 = call(tools, "get_question_for_generation", {"rank": 3})
    assert r3["첫줄"].startswith("3번째로 많이 틀린 문항: 42번 (오답 7명")

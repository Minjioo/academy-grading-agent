"""OMR 로더 + 채점 + 통계 테스트 (PLAN.md §0 샘플 기준값)"""
import io
from pathlib import Path

import pandas as pd
import pytest

from core.answer_key import parse_answer_key
from core.grading import grade, summarize
from core.omr import extract_student_no, load_omr

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
EXPECTED_SCORES = {900: 88, 901: 92, 902: 87, 903: 68, 904: 63, 905: 73, 906: 57, 907: 54, 908: 39, 909: 31}


@pytest.fixture(scope="module")
def answer_key():
    return parse_answer_key(SAMPLE_DIR / "answer.pdf")


@pytest.fixture(scope="module")
def omr_df():
    return load_omr(SAMPLE_DIR / "omr.xlsx")


@pytest.fixture(scope="module")
def results(omr_df, answer_key):
    return grade(omr_df, answer_key)


@pytest.fixture(scope="module")
def summary(results, answer_key, omr_df):
    return summarize(results, answer_key, omr_df)


def test_omr_컬럼_정규화(omr_df):
    assert len(omr_df) == 10
    assert list(omr_df.columns[:2]) == ["학생명", "student_no"]
    assert [c for c in omr_df.columns if isinstance(c, int)] == list(range(1, 46))
    assert omr_df["student_no"].tolist() == list(range(900, 910))


def test_omr_경로와_BytesIO_동일(omr_df):
    buf = io.BytesIO((SAMPLE_DIR / "omr.xlsx").read_bytes())
    pd.testing.assert_frame_equal(load_omr(buf), omr_df)


@pytest.mark.parametrize("name, no", [("87학생", 87), ("1학생", 1), ("학생 87번", 87), ("홍길동", None)])
def test_이름에서_번호_추출(name, no):
    assert extract_student_no(name) == no


def test_잘못된_응답은_NaN_오답처리(answer_key):
    cols = {"이름": ["1학생", "2학생"]}
    for n in range(1, 46):
        cols[f"q{n}"] = [answer_key[n]["answer"]] * 2
    cols["q1"] = [None, 9]  # 빈 값, 범위 밖 값
    buf = io.BytesIO(pd.DataFrame(cols).to_csv(index=False).encode("utf-8"))
    buf.name = "omr.csv"
    df = load_omr(buf)
    assert df[1].isna().all()
    res = grade(df, answer_key)
    assert (res[1] == "X").all()
    assert (res["총점"] == 100 - answer_key[1]["points"]).all()


def test_학생별_점수(results):
    assert dict(zip(results["student_no"], results["총점"])) == EXPECTED_SCORES


def test_석차(results):
    rank = dict(zip(results["student_no"], results["석차"]))
    assert rank[901] == 1 and rank[909] == 10


def test_통계(summary):
    assert summary["count"] == 10
    assert summary["mean"] == pytest.approx(65.2)
    assert summary["median"] == pytest.approx(65.5)
    assert summary["std_pop"] == pytest.approx(19.58, abs=0.01)
    assert summary["std_sample"] == pytest.approx(20.64, abs=0.01)
    assert (summary["max"], summary["min"]) == (92, 31)


def test_최다_오답_상위3(summary):
    assert summary["most_missed"] == [21, 33, 42]
    by_num = {q["number"]: q for q in summary["questions"]}
    assert [by_num[n]["wrong_count"] for n in (21, 33, 42)] == [9, 8, 7]
    assert sum(by_num[21]["distribution"].values()) == 10


def test_문항수_불일치_에러(omr_df, answer_key):
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        grade(omr_df.drop(columns=[45]), answer_key)

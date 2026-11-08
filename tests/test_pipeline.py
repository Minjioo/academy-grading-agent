"""업로드 파일 분류 + LangGraph 채점 파이프라인 테스트"""
import io
from pathlib import Path

import pytest

from core.file_router import classify_files, count_answer_matches
from core.pipeline import run_grading

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def _upload(name: str) -> io.BytesIO:
    """Streamlit UploadedFile처럼 name 속성이 있는 BytesIO"""
    buf = io.BytesIO((SAMPLE_DIR / name).read_bytes())
    buf.name = name
    return buf


@pytest.fixture
def uploads():
    # 이름만으로는 종류를 알 수 없게 바꿔서 내용으로 분류되는지 확인
    a, e, o = _upload("answer.pdf"), _upload("exam.pdf"), _upload("omr.xlsx")
    a.name, e.name, o.name = "파일1.pdf", "파일2.pdf", "결과.xlsx"
    return [e, o, a]


def test_파일_분류(uploads):
    r = classify_files(uploads)
    assert r["errors"] == []
    assert (r["exam"].name, r["omr"].name, r["answer"].name) == ("파일2.pdf", "결과.xlsx", "파일1.pdf")


def test_경로로도_분류():
    r = classify_files([SAMPLE_DIR / n for n in ("answer.pdf", "exam.pdf", "omr.xlsx")])
    assert r["errors"] == []
    assert Path(r["answer"]).name == "answer.pdf"


def test_정답표_패턴_개수로_분류():
    # "정답" 글자가 아니라 정답표 패턴 매칭 개수(20개 이상)로 판단한다
    assert count_answer_matches("1 ③ 2 2 ② 2 " * 10) == 20
    assert count_answer_matches("정답을 고르시오. ① apple ② banana") == 0


def test_PDF가_1개뿐이면_에러(uploads):
    r = classify_files([uploads[1], uploads[2]])  # OMR + 정답 PDF만
    assert any("PDF가 1개뿐입니다" in e for e in r["errors"])
    assert r["exam"] is None


def test_둘_다_정답처럼_보이면_에러(uploads):
    second = _upload("answer.pdf")
    second.name = "정답2.pdf"
    r = classify_files([uploads[1], uploads[2], second])
    assert any("정답표로 보이는 PDF가 여러 개" in e for e in r["errors"])
    assert r["answer"] is None


def test_빠진_파일_중복_파일(uploads):
    r = classify_files([uploads[0], uploads[2]])  # OMR 빠짐
    assert any("OMR 파일이 없습니다" in e for e in r["errors"])
    r = classify_files(uploads + [_upload("omr.xlsx")])
    assert any("OMR 파일이 여러 개" in e for e in r["errors"])
    r = classify_files(uploads + [_upload("exam.pdf")])
    assert any("문제지 파일이 여러 개" in e for e in r["errors"])


def test_지원하지_않는_형식(uploads):
    bad = io.BytesIO(b"hello")
    bad.name = "메모.txt"
    assert any("지원하지 않는 형식" in e for e in classify_files(uploads + [bad])["errors"])


def test_파이프라인_정상(uploads):
    state = run_grading(uploads)
    assert state["error"] is None
    s = state["summary"]
    assert s["mean"] == pytest.approx(65.2)
    assert s["median"] == pytest.approx(65.5)
    assert s["most_missed"] == [21, 33, 42]
    assert len(state["exam"]) == 45
    assert state["excel_bytes"][:2] == b"PK"  # xlsx(zip) 시그니처


def test_진행_콜백(uploads):
    steps = []
    run_grading(uploads, on_step=lambda name, label, i, total: steps.append((label, i, total)))
    assert [s[0] for s in steps] == ["정답 파싱", "OMR 불러오기", "문제지 분석", "채점", "통계 계산", "엑셀 생성"]
    assert steps[-1][1:] == (6, 6)


def test_파이프라인_dict_입력():
    state = run_grading({k: SAMPLE_DIR / f for k, f in
                         (("answer", "answer.pdf"), ("omr", "omr.xlsx"), ("exam", "exam.pdf"))})
    assert state["error"] is None and state["results"]["총점"].max() == 92


def test_노드_실패시_END로_종료():
    # 정답 자리에 문제지를 넣으면 첫 노드에서 실패하고 이후 노드는 실행되지 않는다
    state = run_grading({"answer": SAMPLE_DIR / "exam.pdf", "omr": SAMPLE_DIR / "omr.xlsx",
                         "exam": SAMPLE_DIR / "exam.pdf"})
    assert state["error"].startswith("[정답 파싱]")
    assert "omr_df" not in state and "excel_bytes" not in state


def test_분류_에러는_파이프라인_실행_전_반환(uploads):
    state = run_grading([uploads[0], uploads[2]])
    assert "OMR 파일이 없습니다" in state["error"]

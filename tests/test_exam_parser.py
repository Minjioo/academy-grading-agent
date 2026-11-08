"""문제지 PDF 파서 테스트 (data/sample/exam.pdf 기준)"""
import io
from pathlib import Path

import pytest

from core.exam_parser import parse_exam

EXAM_PDF = Path(__file__).resolve().parent.parent / "data" / "sample" / "exam.pdf"


@pytest.fixture(scope="module")
def exam():
    return parse_exam(EXAM_PDF)


def test_45문항_추출(exam):
    assert list(exam) == list(range(1, 46))
    assert all(q["text"].strip() for q in exam.values())


def test_본문_키워드(exam):
    assert "Amanda Clark" in exam[18]["text"]
    assert "less sticky" in exam[21]["text"]


def test_듣기_문항_표시(exam):
    assert all(exam[n]["is_listening"] for n in range(1, 18))
    assert not any(exam[n]["is_listening"] for n in range(18, 46))


def test_번호만_있는_줄로_시작하는_문항(exam):
    # 36~39번은 "36." 다음 줄부터 지문이 시작된다
    for n, header in ((36, "[36"), (37, "[36"), (38, "[38"), (39, "[38")):
        assert exam[n]["text"].startswith(header)
        assert f"\n{n}.\n" in exam[n]["text"]


def test_묶음_지문_공유(exam):
    # [41～42] 지문이 41, 42번 모두에 들어간다
    first_line_41 = exam[41]["text"].splitlines()[1]
    assert first_line_41 in exam[42]["text"]
    assert exam[43]["text"].startswith("[43")
    assert exam[45]["text"].startswith("[43")
    # 다른 묶음 지문은 섞이지 않는다
    assert first_line_41 not in exam[43]["text"]


def test_머리말_꼬리말_제거(exam):
    all_text = "\n".join(q["text"] for q in exam.values())
    assert "홀수형" not in all_text
    assert "저작권" not in all_text


def test_BytesIO_입력(exam):
    assert parse_exam(io.BytesIO(EXAM_PDF.read_bytes())) == exam

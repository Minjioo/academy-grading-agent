"""정답 PDF 파서 테스트 (data/sample/answer.pdf 기준)"""
import io
from pathlib import Path

import pytest

from core.answer_key import parse_answer_key

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
ANSWER_PDF = SAMPLE_DIR / "answer.pdf"
EXAM_PDF = SAMPLE_DIR / "exam.pdf"


def _minimal_pdf(text: str) -> bytes:
    """정답 기호가 없는 텍스트 한 줄짜리 PDF를 만든다 (외부 라이브러리 없이)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


@pytest.fixture(scope="module")
def answer_key():
    return parse_answer_key(ANSWER_PDF)


def test_45문항_배점합_100(answer_key):
    assert list(answer_key) == list(range(1, 46))
    assert sum(q["points"] for q in answer_key.values()) == 100


@pytest.mark.parametrize("num, answer, points", [(1, 3, 2), (12, 2, 3), (45, 5, 2)])
def test_특정_문항_정답_배점(answer_key, num, answer, points):
    assert answer_key[num] == {"answer": answer, "points": points}


def test_경로와_BytesIO_결과_동일(answer_key):
    assert parse_answer_key(str(ANSWER_PDF)) == answer_key
    assert parse_answer_key(io.BytesIO(ANSWER_PDF.read_bytes())) == answer_key


def test_file_like_읽은_뒤_위치_복원():
    buf = io.BytesIO(ANSWER_PDF.read_bytes())
    buf.seek(100)  # 이미 일부를 읽은 상태여도 처음부터 읽어야 한다
    assert len(parse_answer_key(buf)) == 45
    assert buf.tell() == 0


@pytest.mark.skipif(not EXAM_PDF.exists(), reason="data/sample/exam.pdf 없음")
def test_문제지_PDF는_ValueError():
    with pytest.raises(ValueError):
        parse_answer_key(EXAM_PDF)


def test_정답_없는_PDF는_ValueError():
    with pytest.raises(ValueError, match="찾지 못했습니다"):
        parse_answer_key(io.BytesIO(_minimal_pdf("Hello, this is not an answer key.")))


def test_PDF가_아닌_파일은_ValueError():
    with pytest.raises(ValueError, match="읽을 수 없습니다"):
        parse_answer_key(io.BytesIO(b"not a pdf"))

"""정답 PDF → {번호: {"answer": int, "points": int}}

정답·배점은 코드에 직접 쓰지 않고, 반드시 업로드된 정답 PDF에서 파싱한다.
"""
from __future__ import annotations

import io
import re

import pdfplumber

from core.io_utils import FileInput as PdfInput
from core.io_utils import read_bytes

# 문항 번호, 정답 기호(①~⑤), 배점
ANSWER_PATTERN = re.compile(r"(\d{1,2})\s*([①②③④⑤])\s*(\d)")
CIRCLED_TO_INT = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}


def _extract_text(file: PdfInput) -> str:
    """PDF의 모든 페이지 텍스트를 이어 붙인다."""
    try:
        with pdfplumber.open(io.BytesIO(read_bytes(file))) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:  # 손상된 파일, PDF가 아닌 파일 등
        raise ValueError(f"정답 PDF를 읽을 수 없습니다: {e}") from e


def parse_answer_key(file: PdfInput) -> dict[int, dict]:
    """정답 PDF에서 문항별 정답과 배점을 추출한다.

    Args:
        file: PDF 파일 경로(str/Path) 또는 read()/seek()가 가능한 file-like 객체
              (Streamlit UploadedFile 포함)

    Returns:
        번호순으로 정렬된 {번호: {"answer": 1~5, "points": 배점}}

    Raises:
        ValueError: 정답을 찾지 못했거나, 번호가 중복되거나, 1..N으로 연속되지 않을 때
    """
    text = _extract_text(file)
    matches = ANSWER_PATTERN.findall(text)
    if not matches:
        raise ValueError("정답 PDF에서 문항 번호·정답·배점을 찾지 못했습니다. 정답표 PDF가 맞는지 확인해 주세요.")

    numbers = [int(num) for num, _, _ in matches]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        dup_str = ", ".join(f"{n}번" for n in duplicates)
        raise ValueError(f"정답 PDF에서 중복된 문항 번호가 있습니다: {dup_str}")

    expected = list(range(1, len(numbers) + 1))
    if sorted(numbers) != expected:
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        detail = f" (빠진 번호: {', '.join(f'{n}번' for n in missing)})" if missing else ""
        raise ValueError(f"정답 PDF의 문항 번호가 1번부터 연속되지 않습니다{detail}.")

    key = {
        int(num): {"answer": CIRCLED_TO_INT[symbol], "points": int(points)}
        for num, symbol, points in matches
    }
    return dict(sorted(key.items()))

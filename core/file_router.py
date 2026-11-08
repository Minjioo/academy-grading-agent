"""업로드 파일 자동 분류 (OMR / 정답 / 문제지)"""
from __future__ import annotations

import io
from typing import Iterable

import pdfplumber

from core.answer_key import ANSWER_PATTERN
from core.io_utils import FileInput, file_name, read_bytes

OMR_EXTS = (".xlsx", ".xls", ".csv")
LABELS = {"omr": "OMR", "answer": "정답", "exam": "문제지"}
ANSWER_MIN_MATCHES = 20  # 첫 페이지에서 "번호 ①~⑤ 배점" 패턴이 이만큼 나오면 정답표로 본다


def _first_page_text(file: FileInput) -> str:
    try:
        with pdfplumber.open(io.BytesIO(read_bytes(file))) as pdf:
            return (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:
        return ""


def count_answer_matches(text: str) -> int:
    return len(ANSWER_PATTERN.findall(text))


def classify_files(uploaded_files: Iterable[FileInput]) -> dict:
    """업로드된 파일을 종류별로 나눈다.

    - xlsx/xls/csv → omr
    - PDF는 첫 페이지에서 정답표 패턴이 20개 이상 매칭되면 answer, 아니면 exam

    Returns:
        {"omr": 파일 또는 None, "answer": ..., "exam": ..., "errors": [한국어 에러 메시지, ...]}
        errors가 비어 있으면 세 파일이 모두 하나씩 있는 것이다.
    """
    found: dict[str, list] = {k: [] for k in LABELS}
    errors: list[str] = []
    pdf_count = 0

    for f in uploaded_files or []:
        name = file_name(f)
        lower = name.lower()
        if lower.endswith(OMR_EXTS):
            found["omr"].append(f)
        elif lower.endswith(".pdf"):
            pdf_count += 1
            text = _first_page_text(f)
            if not text.strip():
                errors.append(f"'{name}'에서 텍스트를 읽을 수 없습니다. 텍스트 PDF인지 확인해 주세요.")
                continue
            kind = "answer" if count_answer_matches(text) >= ANSWER_MIN_MATCHES else "exam"
            found[kind].append(f)
        else:
            errors.append(f"'{name}'은(는) 지원하지 않는 형식입니다. PDF, xlsx, xls, csv 파일만 올려 주세요.")

    if pdf_count == 1:
        errors.append("PDF가 1개뿐입니다. 정답 PDF와 문제지 PDF를 모두 올려 주세요.")
    if len(found["answer"]) > 1:
        names = ", ".join(file_name(f) for f in found["answer"])
        errors.append(f"정답표로 보이는 PDF가 여러 개입니다({names}). 정답 PDF 1개와 문제지 PDF 1개를 올려 주세요.")

    result: dict = {}
    for kind, label in LABELS.items():
        files = found[kind]
        if len(files) == 1:
            result[kind] = files[0]
            continue
        result[kind] = None
        if not files and not (kind in ("answer", "exam") and pdf_count == 1):
            errors.append(f"{label} 파일이 없습니다.")
        elif len(files) > 1 and kind != "answer":  # 정답 중복은 위에서 안내
            names = ", ".join(file_name(f) for f in files)
            errors.append(f"{label} 파일이 여러 개입니다({names}). 하나만 올려 주세요.")
    result["errors"] = errors
    return result

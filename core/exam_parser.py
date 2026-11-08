"""문제지 PDF → {번호: {"text": 문항 텍스트(묶음 지문 포함), "is_listening": bool}}

문제지는 2단 구성이므로 페이지마다 왼쪽 절반 → 오른쪽 절반 순서로 텍스트를 뽑는다.
"""
from __future__ import annotations

import io
import re

import pdfplumber

from core.io_utils import FileInput, read_bytes

# "21. 밑줄 친 …" 또는 지문이 다음 줄에서 시작하는 "36." 형태
QUESTION_START = re.compile(r"^(\d{1,2})\.(?:\s|$)")
# [41～42], [43~45] 같은 묶음 지문 헤더 (전각/반각 물결 모두)
GROUP_HEADER = re.compile(r"^\[(\d{1,2})\s*[～~]\s*(\d{1,2})\]")
NOISE_KEYWORDS = ("홀수형", "이 문제지에 관한 저작권")
PAGE_NUMBER = re.compile(r"^\s*\d+\s*$")
MAX_QUESTION = 45
LISTENING_MAX = 17  # 1~17번은 지시문·선택지만 있는 듣기 문항


def _extract_lines(file: FileInput) -> list[str]:
    """페이지 → 왼쪽 → 오른쪽 순서로 텍스트 줄을 모으고 머리말·꼬리말을 지운다."""
    try:
        with pdfplumber.open(io.BytesIO(read_bytes(file))) as pdf:
            chunks = []
            for page in pdf.pages:
                w, h = page.width, page.height
                for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                    chunks.append(page.crop(box).extract_text() or "")
    except Exception as e:
        raise ValueError(f"문제지 PDF를 읽을 수 없습니다: {e}") from e

    lines = []
    for line in "\n".join(chunks).splitlines():
        if any(k in line for k in NOISE_KEYWORDS) or PAGE_NUMBER.match(line):
            continue
        lines.append(line.rstrip())
    return lines


def parse_exam(file: FileInput) -> dict[int, dict]:
    """문제지 PDF를 문항별 텍스트로 나눈다.

    - 문항 번호는 직전 문항보다 큰 경우만 문항 시작으로 인정한다(지문 속 숫자 오인 방지).
    - 묶음 지문 헤더 아래 지문은 그 묶음에 속한 모든 문항 텍스트 앞에 붙인다.
    """
    lines = _extract_lines(file)

    bodies: dict[int, list[str]] = {}
    groups: list[tuple[int, int, list[str]]] = []  # (시작 번호, 끝 번호, 헤더+공통 지문)
    current: list[str] | None = None  # 지금 줄을 쌓고 있는 대상
    last_no = 0

    for line in lines:
        header = GROUP_HEADER.match(line)
        if header:
            start, end = int(header.group(1)), int(header.group(2))
            if start > last_no:
                current = [line]
                groups.append((start, end, current))
                continue
        q = QUESTION_START.match(line)
        if q:
            no = int(q.group(1))
            if last_no < no <= MAX_QUESTION:
                current = bodies.setdefault(no, [])
                current.append(line)
                last_no = no
                continue
        if current is not None:  # 1번 앞의 표지·안내문은 버린다
            current.append(line)

    if not bodies:
        raise ValueError("문제지 PDF에서 문항을 찾지 못했습니다. 문제지 PDF가 맞는지 확인해 주세요.")

    result: dict[int, dict] = {}
    for no in sorted(bodies):
        shared = [g_lines for s, e, g_lines in groups if s <= no <= e]
        parts = ["\n".join(g).strip() for g in shared] + ["\n".join(bodies[no]).strip()]
        result[no] = {"text": "\n\n".join(p for p in parts if p), "is_listening": no <= LISTENING_MAX}
    return result

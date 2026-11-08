"""엑셀 추출 테스트: 생성된 엑셀을 다시 열어 PLAN.md §0 기준값과 비교한다."""
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook

from core.answer_key import parse_answer_key
from core.excel_export import build_excel
from core.grading import grade, summarize
from core.omr import load_omr

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
EXPECTED_SCORES = {"900학생": 88, "901학생": 92, "902학생": 87, "903학생": 68, "904학생": 63,
                   "905학생": 73, "906학생": 57, "907학생": 54, "908학생": 39, "909학생": 31}


@pytest.fixture(scope="module")
def workbook():
    key = parse_answer_key(SAMPLE_DIR / "answer.pdf")
    omr = load_omr(SAMPLE_DIR / "omr.xlsx")
    results = grade(omr, key)
    data = build_excel(results, summarize(results, key, omr), key)
    assert isinstance(data, bytes) and data
    return load_workbook(io.BytesIO(data))


def _overview(ws) -> dict:
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2).value for r in range(2, 10)}


def test_시트_구성(workbook):
    assert workbook.sheetnames == ["성적 결과", "문항 분석"]


def test_개요_블록(workbook):
    ws = workbook["성적 결과"]
    assert ws["A1"].value == "전체 학생 성적 개요"
    ov = _overview(ws)
    assert ov["응시 인원"] == "10명"
    assert ov["평균"] == 65.2
    assert ov["중앙값"] == 65.5
    assert ov["표준편차(모집단)"] == pytest.approx(19.58, abs=0.01)
    assert ov["표준편차(표본)"] == pytest.approx(20.64, abs=0.01)
    assert (ov["최고점"], ov["최저점"]) == (92, 31)
    assert ov["가장 많이 틀린 문항"] == "21번, 33번, 42번"


def test_학생별_표(workbook):
    ws = workbook["성적 결과"]
    header_row = 11  # 개요 8줄 + 제목 1줄 + 빈 줄 1줄 다음
    assert ws.cell(row=10, column=1).value is None
    headers = [c.value for c in ws[header_row]]
    assert headers[:5] == ["학생명", "점수", "정답 수", "석차", "1번"]
    assert headers[-1] == "45번"
    rows = list(ws.iter_rows(min_row=header_row + 1, values_only=True))
    assert {r[0]: r[1] for r in rows} == EXPECTED_SCORES
    assert [r[0] for r in rows] == sorted(EXPECTED_SCORES)  # 학생 번호 오름차순
    assert ws.freeze_panes == f"B{header_row + 1}"


def test_X칸_연한_빨강(workbook):
    ws = workbook["성적 결과"]
    for row in ws.iter_rows(min_row=12, min_col=5):
        for c in row:
            assert (c.fill.fgColor.rgb.endswith("FFC7CE")) == (c.value == "X")


def test_문항_분석_시트(workbook):
    ws = workbook["문항 분석"]
    headers = [c.value for c in ws[1]]
    assert headers[:5] == ["문항", "정답", "배점", "오답 인원", "오답률(%)"]
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert len(rows) == 45
    assert rows["21번"][3] == 9 and rows["21번"][4] == 90.0
    assert sum(r[2] for r in rows.values()) == 100
    assert sum(rows["21번"][5:]) == 10  # 선택지별 응답 수 합 = 응시 인원

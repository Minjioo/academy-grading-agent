"""채점 결과 엑셀 bytes 생성 (openpyxl)"""
from __future__ import annotations

import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
TITLE_FONT = Font(bold=True, size=14)
WRONG_FILL = PatternFill("solid", fgColor="FFC7CE")  # 연한 빨강
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")


def _style_header(cells) -> None:
    for c in cells:
        c.font, c.fill, c.border, c.alignment = HEADER_FONT, HEADER_FILL, BORDER, CENTER


def _write_overview(ws, summary: dict) -> int:
    """시트 위쪽 개요 블록을 쓰고 다음에 쓸 행 번호를 반환한다."""
    ws.cell(row=1, column=1, value="전체 학생 성적 개요").font = TITLE_FONT
    rows = [
        ("응시 인원", f"{summary['count']}명"),
        ("평균", round(summary["mean"], 1)),
        ("중앙값", round(summary["median"], 1)),
        ("표준편차(모집단)", round(summary["std_pop"], 2)),
        ("표준편차(표본)", round(summary["std_sample"], 2)),
        ("최고점", summary["max"]),
        ("최저점", summary["min"]),
        ("가장 많이 틀린 문항", ", ".join(f"{n}번" for n in summary["most_missed"])),
    ]
    for i, (label, value) in enumerate(rows, start=2):
        label_cell = ws.cell(row=i, column=1, value=label)
        _style_header([label_cell])
        label_cell.alignment = Alignment(horizontal="left")
        value_cell = ws.cell(row=i, column=2, value=value)
        value_cell.border = BORDER
        value_cell.alignment = Alignment(horizontal="left")
    return len(rows) + 3  # 한 줄 띄움


def _write_students(ws, results_df: pd.DataFrame, start_row: int) -> None:
    q_nums = sorted(c for c in results_df.columns if isinstance(c, int))
    headers = ["학생명", "점수", "정답 수", "석차"] + [f"{n}번" for n in q_nums]
    for j, h in enumerate(headers, start=1):
        ws.cell(row=start_row, column=j, value=h)
    _style_header(ws[start_row])

    ordered = results_df.sort_values(["student_no", "학생명"], na_position="last")
    for i, (_, r) in enumerate(ordered.iterrows(), start=start_row + 1):
        values = [r["학생명"], int(r["총점"]), int(r["정답 수"]), int(r["석차"])] + [r[n] for n in q_nums]
        for j, v in enumerate(values, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = BORDER
            if j > 1:
                c.alignment = CENTER
            if j > 4 and v == "X":
                c.fill = WRONG_FILL

    ws.freeze_panes = ws.cell(row=start_row + 1, column=2)  # 헤더 아래 + 학생명 열 고정
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 12
    for j in range(3, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 8 if j <= 4 else 5.5


def _write_question_sheet(ws, summary: dict) -> None:
    has_dist = any("distribution" in q for q in summary["questions"])
    choices = ["1", "2", "3", "4", "5", "무응답"] if has_dist else []
    headers = ["문항", "정답", "배점", "오답 인원", "오답률(%)"] + [
        f"{c}번 선택" if c != "무응답" else c for c in choices
    ]
    ws.append(headers)
    _style_header(ws[1])
    for q in summary["questions"]:
        row = [f"{q['number']}번", q["answer"], q["points"], q["wrong_count"], q["wrong_rate"]]
        row += [q.get("distribution", {}).get(c, 0) for c in choices]
        ws.append(row)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.border, c.alignment = BORDER, CENTER
    ws.freeze_panes = "A2"
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 11


def build_excel(results_df: pd.DataFrame, summary: dict, answer_key: dict[int, dict]) -> bytes:
    """채점 결과를 엑셀 파일(bytes)로 만든다.

    시트 1 "성적 결과": 위쪽 전체 개요 + 학생별 표(O/X)
    시트 2 "문항 분석": 문항별 정답·배점·오답 인원·오답률·선택지별 응답 수
    """
    q_nums = sorted(c for c in results_df.columns if isinstance(c, int))
    if q_nums != sorted(answer_key):
        raise ValueError("채점 결과와 정답의 문항 수가 일치하지 않습니다.")

    wb = Workbook()
    ws = wb.active
    ws.title = "성적 결과"
    table_row = _write_overview(ws, summary)
    _write_students(ws, results_df, table_row)
    _write_question_sheet(wb.create_sheet("문항 분석"), summary)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

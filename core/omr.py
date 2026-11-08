"""OMR xlsx/csv → DataFrame (학생명, student_no, 1..N)

실제 평가 데이터는 학생 이름 형식·인원이 샘플과 다를 수 있으므로
컬럼은 헤더로 동적으로 찾고, 학생은 이름 속 숫자(student_no)로 식별한다.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from core.io_utils import FileInput, file_name, read_bytes

QUESTION_COL = re.compile(r"^Q?(\d+)$", re.IGNORECASE)
NAME_KEYWORDS = ("학생", "이름", "name")


def _read_table(file: FileInput) -> pd.DataFrame:
    """첫 번째 시트(또는 CSV)를 읽는다."""
    data = read_bytes(file)
    is_csv = file_name(file).lower().endswith(".csv")
    try:
        if is_csv:
            for enc in ("utf-8-sig", "cp949"):
                try:
                    return pd.read_csv(io.BytesIO(data), encoding=enc)
                except UnicodeDecodeError:
                    continue
            raise ValueError("CSV 인코딩을 인식할 수 없습니다.")
        return pd.read_excel(io.BytesIO(data), sheet_name=0)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"OMR 파일을 읽을 수 없습니다: {e}") from e


def extract_student_no(name) -> int | None:
    """'87학생', '87번', 'student 87' 등에서 첫 번째 숫자를 뽑는다."""
    m = re.search(r"\d+", str(name))
    return int(m.group()) if m else None


def load_omr(file: FileInput) -> pd.DataFrame:
    """OMR 파일을 읽어 정규화된 DataFrame을 반환한다.

    반환 컬럼: 학생명(원래 이름), student_no(이름 속 숫자), 1..N(문항별 응답, 1~5 또는 NaN)
    빈 값·범위 밖 값·숫자가 아닌 값은 NaN으로 두어 채점 시 오답 처리된다.
    """
    raw = _read_table(file)
    raw.columns = [str(c).strip() for c in raw.columns]

    # 문항 컬럼: Q01, q1, 1 ... → 정수 번호
    q_cols: dict[int, str] = {}
    for col in raw.columns:
        m = QUESTION_COL.match(col)
        if m:
            q_cols[int(m.group(1))] = col
    if not q_cols:
        raise ValueError("OMR 파일에서 문항 컬럼(Q01, Q02 … 형식)을 찾지 못했습니다.")

    # 학생명 컬럼: 키워드가 들어간 첫 컬럼, 없으면 문항이 아닌 첫 컬럼
    non_q = [c for c in raw.columns if c not in q_cols.values()]
    name_col = next((c for c in non_q if any(k in c.lower() for k in NAME_KEYWORDS)), None)
    if name_col is None:
        name_col = non_q[0] if non_q else raw.columns[0]

    raw = raw.dropna(subset=[name_col])
    raw = raw[raw[name_col].astype(str).str.strip() != ""]

    out = pd.DataFrame({"학생명": raw[name_col].astype(str).str.strip()})
    out["student_no"] = out["학생명"].map(extract_student_no).astype("Int64")
    for num in sorted(q_cols):
        vals = pd.to_numeric(raw[q_cols[num]], errors="coerce")
        vals = vals.where(vals.isin([1, 2, 3, 4, 5]))  # 잘못된 응답은 NaN
        out[num] = vals.astype("Int64")
    return out.reset_index(drop=True)

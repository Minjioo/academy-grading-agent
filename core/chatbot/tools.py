"""@tool 팩토리 (채점 결과를 클로저로 캡처)

반환값은 모두 짧은 JSON 문자열이다(응답 속도 확보).
"""
from __future__ import annotations

import json
import re

import pandas as pd
from langchain.tools import tool

NOT_FOUND = "해당 학생을 찾을 수 없습니다"
MAX_TEXT_CHARS = 2500


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _r1(x: float) -> float:
    """소수점 첫째 자리 반올림 (65.25 → 65.3 처럼 사람 기준 반올림)."""
    return float(f"{float(x) + 1e-9:.1f}")


def parse_student_no(text) -> int | None:
    """'87', '87번', '87번 학생', '87학생', '학생 87' 등에서 학생 번호를 뽑는다."""
    s = str(text)
    m = re.search(r"(\d+)\s*(?:번|학생)", s) or re.search(r"\d+", s)
    return int(m.group(1) if m.lastindex else m.group()) if m else None


def question_brief(q: dict) -> dict:
    """문항 통계(summary["questions"]의 한 항목)를 짧은 dict로."""
    out = {
        "문항": q["number"],
        "오답인원": q["wrong_count"],
        "오답률": f"{q['wrong_rate']}%",
        "정답": q["answer"],
        "배점": q["points"],
    }
    if "distribution" in q:
        out["선택지별응답수"] = q["distribution"]
    return out


def question_stem(number: int, text: str) -> str:
    """문항 발문(묶음 헤더 + 자기 번호 줄과 다음 줄)만 뽑는다(지문 속 단어로 유형을 오분류하지 않도록)."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    parts = lines[:2] if lines and lines[0].startswith("[") else []
    for i, l in enumerate(lines):
        if re.match(rf"^{number}\.", l):
            parts += lines[i:i + 2]
            break
    return " ".join(parts)


_TYPE_RULES = [
    ("듣기", None), ("도표", r"도표"), ("어법", r"어법"), ("지칭", r"가리키는 대상"), ("어휘", r"낱말의 쓰임"),
    ("요약", r"요약"), ("문장삽입", r"주어진 문장이 들어가기"), ("순서", r"순서"), ("무관한문장", r"관계\s*없는"),
    ("빈칸", r"빈칸"), ("밑줄의미", r"밑줄"), ("내용일치", r"일치|안내문|내용으로 적절하지"), ("심경", r"심경"),
    ("목적", r"목적"), ("제목", r"제목"), ("주제", r"주제"), ("요지", r"요지"), ("주장", r"주장"),
]


def question_type(number: int, text: str, is_listening: bool = False) -> str:
    if is_listening:
        return "듣기"
    stem = question_stem(number, text)
    return next((name for name, pat in _TYPE_RULES if pat and re.search(pat, stem)), "기타")


_COMMON_GUIDE = ("원문 지문·선택지·요약문·등장인물·고유명사·밑줄 표현을 재사용하지 말고, 다른 분야·상황의 새 소재로 쓴다. "
                 "원문의 논지 전개·줄거리·문장 틀도 그대로 따르지 않는다. "
                 "정답 선택지는 지문과 대조해 정말 정답인지 확인하고, 해설에서 근거가 되는 지문 부분을 짚는다. "
                 "**문제**, **지문**, **선택지**, **정답**, **해설** 다섯 항목을 모두 쓴다.")
_TYPE_GUIDE = {
    "도표": "문제지에 도표 이미지가 없어 원문 도표 데이터는 없다. 새 소재의 도표 데이터를 영어 마크다운 표(| 항목 | 값 |, 구분선 |---| 포함)로 "
            "**지문** 맨 앞에 새로 만들고, 'The table above shows ...'로 시작하는 영어 설명문 안에 ①~⑤ 문장을 표시한다. "
            "원문 분류명(Every Day, Less Often 등)과 원문 설명문 표현(the highest percentage among, more than twice that of 등)을 "
            "재사용하지 말고 새 분류(연도, 지역, 연령대 등)와 새 문장으로 쓴다. "
            "①~⑤ 다섯 문장 중 정확히 한 문장만 표와 어긋나게 쓰고, 나머지 넷은 표의 수치로 직접 확인해 모두 맞게 쓴다. "
            "표의 행·열 이름은 설명문과 같은 영어로 쓴다. 그중 표와 일치하지 않는 문장 1개가 정답이다. "
            "**선택지**는 '①~⑤ (지문 속 문장)'이라고 한 줄로 쓴다.",
    "밑줄의미": "원문의 밑줄 표현을 쓰지 말고 새 비유적 표현을 만든다. 그 표현을 문제 문장과 지문 속에 모두 <u>표현</u>으로 표시한다.",
    "빈칸": "지문 안 빈칸은 ________ (밑줄 문자 8개)로 정확히 한 곳 표시한다. 빈칸에 <u> 태그를 쓰지 않는다. "
            "오답 4개는 빈칸에 넣었을 때 지문 논리와 분명히 어긋나야 한다(정답과 비슷한 뜻의 선택지 금지). "
            "빈칸이 들어간 문장에는 not, cannot, never, no 같은 부정어를 쓰지 않는다. 원문이 부정 구조여도 긍정 구조로 바꾼다"
            "(부정문 빈칸은 오답 넷도 참이 되어 정답이 여러 개가 된다).",
    "어법": "지문 안 다섯 곳을 ①<u>낱말</u> ~ ⑤<u>낱말</u> 형식으로 모두 표시한다(예: ①<u>being</u>). 다섯 표시가 모두 지문에 있어야 하고, "
            "정답(틀린) 낱말도 반드시 표시한다. 선택지는 표시한 다섯 낱말이다. 하나만 어법상 틀리게 쓰고, 나머지 넷은 확실히 맞게 쓴다. "
            "원문 지문의 표현을 가져오지 않는다.",
    "어휘": "지문 안 다섯 낱말을 원문처럼 ①<u>낱말</u> ~ ⑤<u>낱말</u> 형식으로 모두 표시한다(원문이 (a)~(e)면 (a)<u>낱말</u> ~ (e)<u>낱말</u>). "
            "<u>만 쓰고 번호를 빼면 안 된다. 다섯 표시가 모두 지문에 있어야 하고, 정답(쓰임이 틀린) 낱말도 반드시 표시한다. "
            "그중 하나만 문맥상 쓰임이 틀리게 쓴다. 원문 지문의 표현을 가져오지 않는다.",
    "지칭": "이야기 속 다섯 곳에 (a)~(e)를 표시하고, 그중 하나만 다른 인물을 가리키게 쓴다.",
    "무관한문장": "지문 안 다섯 문장 앞에 ①~⑤를 표시하고, 그중 한 문장만 전체 흐름과 관계없게 쓴다.",
    "순서": "주어진 글 다음에 (A), (B), (C) 세 단락을 섞어 제시한다(원문이 (A) 다음 (B)(C)(D)면 그 형식을 따른다). "
            "선택지는 ① (A)-(C)-(B) 같은 배열이다. 원문 이야기를 인물만 바꿔 다시 쓰지 않는다.",
    "문장삽입": "**주어진 문장**을 지문 위에 따로 제시하고, 지문 안에 ( ① ) ~ ( ⑤ ) 다섯 위치를 모두 표시한다.",
    "요약": "**지문** 끝에 '↓' 줄을 두고, 그 아래에 (A), (B) 빈칸이 들어간 영어 한 문장 요약문을 반드시 쓴다"
            "(예: Although ..., (A) ______ ... can (B) ______ ...). 선택지는 '(A) …… (B)' 단어 쌍 5개다. "
            "요약문은 원문 요약문의 문장 틀(시작 어구, 구문 구조)을 쓰지 않고 새 구조로 쓴다.",
    "내용일치": "새 인물·행사·제품으로 글을 쓰고(원문과 다른 분야), 선택지는 한국어로 쓴다. "
                "선택지 다섯 개 중 정확히 하나만 지문 내용과 어긋나게(발문이 '일치하는 것'이면 하나만 맞게) 쓴다. "
                "안내문이면 원문 안내문의 항목 구성과 문장 틀을 그대로 쓰지 않는다.",
    "심경": "새 인물·상황으로 쓰고, 선택지 감정 단어 쌍도 원문과 다른 조합으로 새로 만든다.",
}


def rank_label(rank: int) -> str:
    """1 → '가장 많이 틀린 문항', 2 이상 → 'N번째로 많이 틀린 문항'."""
    rank = int(rank)
    return "가장 많이 틀린 문항" if rank <= 1 else f"{rank}번째로 많이 틀린 문항"


def generation_payload(q: dict, tied: list[int], exam: dict | None, rank: int = 1) -> dict:
    """문제 생성용 데이터: 동점 문항, 기준 문항 통계, 듣기 여부, 본문. rank는 첫 줄 문구에 쓴다."""
    exam = exam or {}
    number = q["number"]
    item = exam.get(number)
    out = {"동점문항": tied, "문제생성_기준문항": number, **question_brief(q)}
    out["듣기문항"] = bool(item.get("is_listening", number <= 17)) if item else number <= 17
    out["본문"] = item["text"][:MAX_TEXT_CHARS] if item else "(문제지에서 본문을 찾지 못함)"
    kind = question_type(number, item["text"] if item else "", out["듣기문항"])
    out["유형"] = kind
    long_set = number >= 41 and (item or {}).get("text", "").startswith("[")
    guide = [_TYPE_GUIDE.get(kind, "")]
    if long_set:
        guide.append("원문은 장문 묶음 지문이다. 원문 이야기와 인물·사건·배경이 모두 다른 새 글(250~300단어)로 이 문항 하나만 만든다.")
    out["출제_안내"] = " ".join(x for x in (*guide, _COMMON_GUIDE) if x)
    # 첫 줄 문장을 코드로 만들어 준다(동점 문항 누락 방지)
    nums = ", ".join(f"{t}번" for t in tied)
    cnt = f"각 오답 {q['wrong_count']}명" if len(tied) > 1 else f"오답 {q['wrong_count']}명"
    out["순위"] = max(1, int(rank))
    out["첫줄"] = f"{rank_label(rank)}: {nums} ({cnt}, {kind})" + (f" → {number}번 기준으로 1문제 생성" if len(tied) > 1 else "")
    return out


def _question_numbers(df: pd.DataFrame) -> list[int]:
    return sorted(c for c in df.columns if isinstance(c, int))


def make_tools(results_df: pd.DataFrame, summary: dict, answer_key: dict, exam: dict | None) -> list:
    """채점 결과를 클로저에 담은 툴 목록을 만든다."""
    df = results_df.copy()
    q_nums = _question_numbers(df)
    total_points = summary.get("total_points") or int(sum(v["points"] for v in answer_key.values()))
    n_students = len(df)
    q_info = {q["number"]: q for q in summary.get("questions", [])}
    exam = exam or {}

    def _student_row(row) -> dict:
        wrong = [n for n in q_nums if row[n] == "X"]
        return {
            "학생명": row["학생명"],
            "점수": int(row["총점"]),
            "만점": total_points,
            "석차": f"{int(row['석차'])}/{n_students}",
            "정답수": int(row["정답 수"]),
            "틀린문항": wrong,
        }

    def _ranked_questions() -> list[dict]:
        return sorted(q_info.values(), key=lambda q: (-q["wrong_count"], q["number"]))

    def _top_tied() -> list[int]:
        """오답 인원 1위와 동점인 문항 번호(오름차순)."""
        ranked = _ranked_questions()
        if not ranked:
            return []
        return [q["number"] for q in ranked if q["wrong_count"] == ranked[0]["wrong_count"]]

    _question_brief = question_brief

    def _text_of(number: int) -> str:
        item = exam.get(number)
        if not item:
            return "(문제지에서 본문을 찾지 못함)"
        return item["text"][:MAX_TEXT_CHARS]

    @tool
    def get_score_summary() -> str:
        """전체 성적 통계를 조회한다. 응시 인원, 평균, 중앙값, 표준편차, 최고점, 최저점, 만점을 묻는 질문에 사용한다."""
        return _dump({
            "응시인원": summary["count"],
            "평균": _r1(summary["mean"]),
            "중앙값": _r1(summary["median"]),
            "표준편차_모집단": _r1(summary["std_pop"]),
            "표준편차_표본": _r1(summary["std_sample"]),
            "최고점": summary["max"],
            "최저점": summary["min"],
            "만점": total_points,
        })

    @tool
    def get_student_result(student: str) -> str:
        """특정 학생의 점수, 석차, 정답 수, 틀린 문항 번호를 조회한다.
        student에는 학생 번호나 이름을 넣는다. 예: "87", "87번", "87번 학생", "87학생", "905학생"."""
        no = parse_student_no(student)
        if no is not None:
            hit = df[df["student_no"] == no]
        else:
            name = str(student).strip()
            hit = df[df["학생명"].astype(str).str.contains(re.escape(name), na=False)] if name else df.iloc[0:0]
        if hit.empty:
            nos = df["student_no"].dropna()
            rng = f"{int(nos.min())}~{int(nos.max())}" if len(nos) else "없음"
            return _dump({"결과": NOT_FOUND, "요청": str(student), "등록된_학생번호_범위": rng, "응시인원": n_students})
        rows = [_student_row(r) for _, r in hit.iterrows()]
        return _dump(rows[0] if len(rows) == 1 else {"동일번호_학생": rows})

    def _extreme(n: int, lowest: bool) -> str:
        n = max(1, int(n))
        scores = sorted(df["총점"].unique(), reverse=not lowest)
        cutoff = scores[min(n, len(scores)) - 1]
        sel = df[df["총점"] <= cutoff] if lowest else df[df["총점"] >= cutoff]
        sel = sel.sort_values(["총점", "student_no"], ascending=[lowest, True])
        return _dump({
            "기준": "최저점" if lowest else "최고점",
            "학생": [{"학생명": r["학생명"], "점수": int(r["총점"]), "석차": int(r["석차"])} for _, r in sel.iterrows()],
            "만점": total_points,
            "응시인원": n_students,
            "비고": "동점자 모두 포함",
        })

    @tool
    def get_lowest_students(n: int = 1) -> str:
        """성적이 가장 낮은(저조한, 꼴찌) 학생을 조회한다. 동점자를 모두 포함한다. n은 하위 몇 번째 점수까지 볼지(기본 1)."""
        return _extreme(n, lowest=True)

    @tool
    def get_top_students(n: int = 1) -> str:
        """성적이 가장 높은(1등) 학생을 조회한다. 동점자를 모두 포함한다. n은 상위 몇 번째 점수까지 볼지(기본 1)."""
        return _extreme(n, lowest=False)

    @tool
    def get_most_missed_questions(n: int = 3) -> str:
        """학생들이 가장 많이 틀린 문항을 오답 인원 순으로 조회한다(동점이면 문항 번호 오름차순).
        n번째 문항과 오답 인원이 같은 문항(동점)도 모두 포함한다. 오답 인원, 오답률, 정답, 배점을 준다."""
        n = max(1, int(n))
        ranked = _ranked_questions()
        if not ranked:
            return _dump({"결과": "문항 정보가 없습니다"})
        cutoff = ranked[min(n, len(ranked)) - 1]["wrong_count"]
        picked = [q for q in ranked if q["wrong_count"] >= cutoff]
        return _dump({
            "응시인원": n_students,
            "최다오답_동점문항": _top_tied(),
            "최다오답문항": [_question_brief(q) for q in picked],
            "비고": "동점 문항 모두 포함",
        })

    @tool
    def get_question_for_generation(rank: int = 1) -> str:
        """많이 틀린 문항(rank=1이면 1위, '두 번째로 많이 틀린'이면 rank=2)의 번호, 본문, 정답, 오답 분포를 한 번에 조회한다.
        오답 인원이 같은 동점 문항 번호도 모두 알려 주고, 본문은 동점 중 번호가 가장 앞선 문항 기준이다.
        '가장 많이 틀린 문제와 유사한 문제를 만들어 줘' 같은 문제 생성 요청에 이 도구 하나만 쓰면 된다."""
        ranked = _ranked_questions()
        if not ranked:
            return _dump({"결과": "문항 정보가 없습니다"})
        rank = max(1, min(int(rank), len(ranked)))
        q = ranked[rank - 1]
        tied = [r["number"] for r in ranked if r["wrong_count"] == q["wrong_count"]]
        return _dump(generation_payload(q, tied, exam, rank))

    @tool
    def get_question_text(number: int) -> str:
        """특정 번호 문항의 문제지 본문(묶음 지문 포함)과 정답, 배점, 오답 인원을 조회한다."""
        number = int(number)
        if number not in q_info:
            return _dump({"결과": f"{number}번 문항이 없습니다", "문항수": len(q_nums)})
        out = _question_brief(q_info[number])
        out["듣기문항"] = bool(exam.get(number, {}).get("is_listening", number <= 17))
        out["본문"] = _text_of(number)
        return _dump(out)

    return [
        get_score_summary,
        get_student_result,
        get_lowest_students,
        get_top_students,
        get_most_missed_questions,
        get_question_for_generation,
        get_question_text,
    ]

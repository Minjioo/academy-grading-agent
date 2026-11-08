"""독해 문항(18~45번) 유사 문제 생성 자동 점검

사용: python scripts/eval_generation.py [--numbers 21,25,31] [--workers 4]
- 각 문항을 최다 오답 문항으로 간주하고 챗봇과 같은 흐름(같은 시스템 프롬프트 + 같은 문제 생성용 데이터)으로 1문제 생성
- 형식 검사(코드) + 내용 평가(LLM 채점자, 같은 모델, temperature 0)
- 하나라도 FAIL이면 종료 코드 1
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain.chat_models import init_chat_model  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core.answer_key import parse_answer_key  # noqa: E402
from core.chatbot.agent import MODEL_NAME, generate_for_question, load_api_key  # noqa: E402
from core.chatbot.tools import question_type  # noqa: E402
from core.exam_parser import parse_exam  # noqa: E402
from core.grading import grade, summarize  # noqa: E402
from core.omr import load_omr  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
TIME_LIMIT = 15.0
CIRCLED = "①②③④⑤"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- 유형 분류
def classify(number: int, text: str) -> str:
    """유형 분류는 챗봇과 같은 함수(core.chatbot.tools.question_type)를 쓴다."""
    return question_type(number, text)


# ---------------------------------------------------------------- 형식 검사
def copied_ngram(src: str, ans: str, n: int = 6) -> str | None:
    norm = lambda t: [w for w in re.findall(r"[a-z']+", re.sub(r"</?u>", " ", t.lower())) if len(w) > 1]  # noqa: E731
    sw, aw = norm(src), " ".join(norm(ans))
    for i in range(len(sw) - n + 1):
        gram = " ".join(sw[i:i + n])
        if f" {gram} " in f" {aw} ":
            return gram
    return None


def answer_line(a: str) -> str:
    m = re.search(r"정답\**\s*[:：]?\s*(.*)", a)
    return m.group(1) if m else ""


def format_check(kind: str, src: str, a: str, sec: float) -> list[str]:
    """실패 사유 목록(비어 있으면 PASS)."""
    fails = []
    if not all(c in a for c in CIRCLED):
        fails.append("선택지 ①~⑤ 부족")
    ans = [c for c in answer_line(a) if c in CIRCLED]
    if len(set(ans)) != 1:
        fails.append(f"정답 표기 이상({''.join(ans) or '없음'})")
    m = re.search(r"해설\**\s*[:：]?\s*(.+)", a, re.DOTALL)
    if not m or len(m.group(1).strip()) < 10:
        fails.append("해설 없음")
    if sec > TIME_LIMIT:
        fails.append(f"시간 {sec:.1f}s > {TIME_LIMIT:.0f}s")
    if gram := copied_ngram(src, a):
        fails.append(f"원문 6단어 복사: '{gram}'")

    def each_twice(chars):
        return all(a.count(c) >= 2 for c in chars)

    if kind == "밑줄의미" and len(re.findall(r"<u>[^<]+</u>", a)) < 2:
        fails.append("<u>밑줄</u> 2곳(문제+지문) 없음")
    if kind == "빈칸" and not re.search(r"_{4,}", a):
        fails.append("빈칸 ____ 없음")
    if kind == "순서" and not all(f"({x})" in a for x in "ABC"):
        fails.append("(A)(B)(C) 없음")
    if kind == "문장삽입":
        if not all(re.search(rf"\(\s*{c}\s*\)", a) for c in CIRCLED):
            fails.append("( ① )~( ⑤ ) 위치 표시 없음")
        if "주어진 문장" not in a:
            fails.append("주어진 문장 없음")
    if kind == "요약" and not (a.count("(A)") >= 2 and a.count("(B)") >= 2):
        fails.append("(A)(B) 빈칸 요약문 없음")
    if kind in ("어법", "어휘", "무관한문장", "지칭"):
        letters = all(f"({x})" in a for x in "abcde")
        if not (letters or each_twice(CIRCLED)):
            fails.append("지문 안 ①~⑤/(a)~(e) 표시 없음")
    if kind == "도표":
        table_rows = [l for l in a.splitlines() if re.match(r"^\s*\|.*\|\s*$", l)]
        if len(table_rows) < 3 or not any(re.search(r"\|\s*:?-{3,}", l) for l in table_rows):
            fails.append("마크다운 표 없음")
    return fails


def passage_words(a: str) -> int:
    m = re.search(r"지문\**\s*(.+?)(\*\*선택지|①)", a, re.DOTALL)
    return len(re.findall(r"[A-Za-z']+", m.group(1))) if m else 0


# ---------------------------------------------------------------- 내용 평가 (LLM 채점자)
class Item(BaseModel):
    score: int = Field(description="1=충족, 0=미충족")
    reason: str = Field(description="한 줄 사유(한국어)")


class Judgement(BaseModel):
    type_match: Item = Field(description="생성 문제의 유형·발문이 원문 문항과 같은가")
    single_answer: Item = Field(description="선택지 5개를 지문과 하나씩 직접 대조했을 때, 표기된 정답만 조건을 만족하고 나머지 넷은 만족하지 않는가")
    no_copy: Item = Field(description="원문 문장·표현을 그대로 베끼지 않았는가")
    suneung_format: Item = Field(description="수능 영어 문항 형식(발문, 지문, 선택지 5개, 표시 방식)에 맞는가")
    different_topic: Item = Field(description="소재(분야·상황)가 원문과 다른가")
    plausible_distractors: Item = Field(description="오답 선택지가 뻔하지 않고 그럴듯한가(지문과 정반대인 뻔한 오답 위주가 아님)")


CRITERIA = [("type_match", "유형"), ("single_answer", "정답"), ("no_copy", "복사X"),
            ("suneung_format", "형식"), ("different_topic", "소재"), ("plausible_distractors", "오답")]

JUDGE_PROMPT = """너는 수능 영어 출제 검토위원이다. 원문 문항과, 그것을 바탕으로 새로 만든 유사 문제를 비교해 각 기준을 0 또는 1로 엄격하게 판정하고 한 줄 사유를 쓴다.
주의: 소재(분야·상황)가 원문과 다른 것은 출제 의도대로이며 감점 사유가 아니다. type_match는 문제 유형·발문 형식만 본다.
참고: 원문이 도표 문항이면 원문 PDF에 그래프 이미지가 없으므로 생성 문제가 표로 데이터를 제시하는 것은 정상이다.
원문 문항이 묶음 지문(예: [41~42])이면 그 문항 하나만 만든 것이 정상이다.

[원문 문항 {number}번 / 유형: {kind}]
{src}

[생성된 유사 문제]
{gen}
"""


def make_judge():
    load_api_key()
    model = init_chat_model(MODEL_NAME, model_provider="openai", use_responses_api=True,
                            temperature=0, reasoning={"effort": "none"}, timeout=40, max_retries=1)
    return model.with_structured_output(Judgement)


# ---------------------------------------------------------------- 실행
def run_one(n, ctx, judge):
    results, summary, key, exam = ctx
    src = exam[n]["text"]
    kind = classify(n, src)
    t0 = time.perf_counter()
    try:
        gen = generate_for_question(results, summary, key, exam, n)
    except Exception as e:
        gen = f"(생성 실패: {type(e).__name__})"
    sec = time.perf_counter() - t0
    fails = format_check(kind, src, gen, sec)
    try:
        j = judge.invoke(JUDGE_PROMPT.format(number=n, kind=kind, src=src[:2500], gen=gen))
        content = {k: getattr(j, k) for k, _ in CRITERIA}
    except Exception as e:
        content = {k: Item(score=0, reason=f"채점 실패 {type(e).__name__}") for k, _ in CRITERIA}
    for k, label in CRITERIA:
        if content[k].score != 1:
            fails.append(f"[내용:{label}] {content[k].reason}")
    return {"n": n, "kind": kind, "gen": gen, "sec": sec, "fails": fails, "content": content,
            "format_ok": not any(not f.startswith("[내용") for f in fails), "words": passage_words(gen)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers", default="18-45")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    nums = []
    for part in args.numbers.split(","):
        a, _, b = part.partition("-")
        nums += list(range(int(a), int(b or a) + 1))

    key = parse_answer_key(SAMPLE / "answer.pdf")
    exam = parse_exam(SAMPLE / "exam.pdf")
    omr = load_omr(SAMPLE / "omr.xlsx")
    results = grade(omr, key)
    summary = summarize(results, key, omr)
    ctx = (results, summary, key, exam)
    judge = make_judge()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(lambda n: run_one(n, ctx, judge), nums))

    print("\n| 문항 | 유형 | 형식 | " + " | ".join(l for _, l in CRITERIA) + " | 단어 | 시간 | FAIL 사유 |")
    print("|---|---|---|" + "---|" * len(CRITERIA) + "---|---|---|")
    for r in rows:
        marks = " | ".join("O" if r["content"][k].score == 1 else "X" for k, _ in CRITERIA)
        reason = " / ".join(r["fails"])[:160] or "-"
        print(f"| {r['n']} | {r['kind']} | {'O' if r['format_ok'] else 'X'} | {marks} | {r['words']} | "
              f"{r['sec']:.1f}s | {reason} |")

    failed = [r for r in rows if r["fails"]]
    for r in failed:
        print(f"\n{'=' * 70}\n[FAIL] {r['n']}번 ({r['kind']})\n- " + "\n- ".join(r["fails"]) + f"\n{'-' * 70}\n{r['gen']}")

    secs = [r["sec"] for r in rows]
    print(f"\n전체 {len(rows)}문항 중 PASS {len(rows) - len(failed)}, FAIL {len(failed)} | "
          f"형식 PASS {sum(r['format_ok'] for r in rows)}/{len(rows)} | "
          f"시간 평균 {sum(secs) / len(secs):.1f}s, 최대 {max(secs):.1f}s")
    for k, label in CRITERIA:
        print(f"  내용 {label}: {sum(r['content'][k].score == 1 for r in rows)}/{len(rows)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

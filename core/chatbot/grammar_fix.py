"""유사 문제 문법 교정(후처리) — "밑줄의미"·"빈칸" 유형만 대상 (어휘·어법·지칭은 교정하지 않음)

밑줄(<u>)·빈칸(____)이 들어간 영어 문장만 같은 모델로 최소 교정한다.
- 교정 대상 문장만 보내고, 돌려받은 문장으로 그 자리만 바꾼다(선택지·정답·나머지 문장은 모델에 보내지 않음).
- 밑줄 표현과 빈칸은 [[U1]], [[B1]] 자리표시로 가려서 보낸다(모델이 표시를 지우거나 바꾸지 못하게).
- 교정 후 <u> 표현, 빈칸 수, 선택지 ①~⑤, 정답이 원래와 같은지 코드로 확인하고, 다르면 원래 답변을 쓴다.
- 오류·타임아웃이 나면 원래 답변을 그대로 쓴다.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

_U = re.compile(r"<u>(.+?)</u>", re.DOTALL)
_BLANK = re.compile(r"_{4,}")
_HANGUL = re.compile(r"[가-힣]")
_LABEL = re.compile(r"^\*\*[^*\n]{1,10}\*\*\s*")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
_PLACEHOLDER = re.compile(r"\[\[[UB]\d+\]\]")
_NUMBERED_U = re.compile(r"(?:[①②③④⑤]|\([a-e]\))\s*<u>")  # 어휘·어법·지칭식 번호 밑줄

CORRECTION_PROMPT = """아래는 영어 문제 지문에서 표시가 들어간 문장들이다.
[[U1]], [[U2]] …는 밑줄 친 영어 표현, [[B1]] …는 빈칸 자리표시다. 각 자리표시가 실제로 무엇인지는 [범례]에 있다.
범례의 표현을 자리표시 위치에 그대로 넣었다고 생각하고 문장 전체가 문법적으로 맞는지 판단하라
(예: "found that [[U1]]."에서 [[U1]] = "turned the room into a hub"이면 that절에 주어가 없으므로 "found that its tables [[U1]]."처럼 고친다).
각 문장이 문법적으로 완전한 문장이 되도록 최소한으로 고쳐라(예: 빠진 주어 보충, 겹친 동사 정리).
주어를 보충할 때는 밑줄 표현과 의미가 겹치지 않는 자연스러운 주어(예: "the new layout", "its open tables")를 쓴다.
자리표시([[U1]], [[B1]] 등)는 글자 그대로 하나씩 남기고, 자리표시 자체를 지우거나 바꾸지 마라.
고칠 게 없는 문장은 그대로 돌려줘라. 문장 수와 순서를 유지하라.

[문장]
{sentences}

[범례]
{legend}
"""


class _Fixed(BaseModel):
    sentences: list[str] = Field(description="입력과 같은 순서·개수의 교정된 문장")


Corrector = Callable[[list[str]], list[str]]


def _body(text: str) -> str:
    """선택지 앞까지(문제 + 지문)."""
    return re.split(r"\*\*선택지\*\*", text, maxsplit=1)[0]


def marked_sentences(text: str) -> list[str]:
    """지문 속 밑줄·빈칸이 들어간 영어 문장(한글이 섞인 문제 문장은 제외)."""
    out = []
    for line in _body(text).splitlines():
        # "**지문** A small ..."처럼 같은 줄의 항목 제목은 떼고 본다
        line = _LABEL.sub("", line.strip())
        for sent in _SENT_SPLIT.split(line):
            sent = sent.strip()
            if not sent or _HANGUL.search(sent):
                continue
            if "<u>" in sent or _BLANK.search(sent):
                out.append(sent)
    return list(dict.fromkeys(out))


def _invariants(text: str) -> tuple:
    """바뀌면 안 되는 것: <u> 표현 목록, 빈칸 수, 선택지 이후 전체(선택지·정답·해설)."""
    tail = text[len(_body(text)):]
    return (_U.findall(text), len(_BLANK.findall(text)), tail)


def answer_kind(text: str) -> str | None:
    """교정 대상 유형 판별: '밑줄의미' 또는 '빈칸'. 그 외(어휘·어법·지칭 등)는 None.

    어휘·어법은 ①<u>낱말</u>·(a)<u>낱말</u>처럼 번호 붙은 밑줄을 쓰고, 일부러 틀린 낱말을 넣는 유형이라
    문법 교정을 하면 정답이 사라질 수 있으므로 교정하지 않는다.
    """
    if not text or "**정답**" not in text:
        return None
    body = _body(text)
    question = body.split("**지문**", 1)[0]
    if _NUMBERED_U.search(body) or re.search(r"어법|낱말|가리키는 대상", question):
        return None
    if "밑줄" in question and "<u>" in body:
        return "밑줄의미"
    if _BLANK.search(body):
        return "빈칸"
    return None


def needs_fix(text: str) -> bool:
    return answer_kind(text) is not None and bool(marked_sentences(text))


# ---------------------------------------------------------------- 기본 교정기 (같은 모델)
_MODEL = None


def _get_model():
    """교정 모델은 한 번 만들어 재사용한다(연결 지연 감소)."""
    global _MODEL
    if _MODEL is None:
        from langchain.chat_models import init_chat_model

        from core.chatbot.agent import MODEL_NAME, load_api_key

        load_api_key()
        _MODEL = init_chat_model(
            MODEL_NAME, model_provider="openai", use_responses_api=True,
            temperature=0, reasoning={"effort": "none"}, timeout=8, max_retries=0,
        ).with_structured_output(_Fixed)
    return _MODEL


def mask(sentence: str) -> tuple[str, dict[str, str]]:
    """문장 하나의 <u>…</u>·빈칸을 [[U1]]·[[B1]] 자리표시로 바꾼다."""
    table: dict[str, str] = {}
    counts = {"U": 0, "B": 0}

    def sub(kind):
        def _f(m):
            counts[kind] += 1
            key = f"[[{kind}{counts[kind]}]]"
            table[key] = m.group(0)
            return key
        return _f

    masked = _BLANK.sub(sub("B"), _U.sub(sub("U"), sentence))
    return masked, table


def unmask(sentence: str, table: dict[str, str]) -> str | None:
    """자리표시를 원래 표시로 되돌린다. 자리표시가 빠지거나 겹치거나 남으면 None."""
    if sorted(_PLACEHOLDER.findall(sentence)) != sorted(table):
        return None
    for key, val in table.items():
        sentence = sentence.replace(key, val)
    return sentence


def _default_corrector(sentences: list[str]) -> list[str]:
    masked = [mask(s) for s in sentences]
    numbered = "\n".join(f"{i + 1}. {m}" for i, (m, _) in enumerate(masked))
    legend = "\n".join(
        f"{i + 1}번 문장 {key} = " + (f'"{_U.sub(lambda x: x.group(1), val)}"' if val.startswith("<u>") else "빈칸")
        for i, (_, table) in enumerate(masked) for key, val in table.items()
    )
    fixed = _get_model().invoke(CORRECTION_PROMPT.format(sentences=numbered, legend=legend)).sentences
    if len(fixed) != len(sentences):
        return sentences
    out = []
    for orig, (_, table), f in zip(sentences, masked, fixed):
        f = re.sub(r"^\d+\.\s+", "", (f or "").strip())
        restored = unmask(f, table)
        out.append(restored if restored is not None else orig)
    return out


# ---------------------------------------------------------------- 진입점
def polish_answer(text: str, corrector: Corrector | None = None) -> str:
    """밑줄·빈칸 문장을 교정한 답변을 돌려준다. 확인에 실패하면 원래 답변을 돌려준다."""
    if not needs_fix(text):
        return text
    sentences = marked_sentences(text)
    try:
        fixed = (corrector or _default_corrector)(sentences)
    except Exception:
        return text
    if len(fixed) != len(sentences):
        return text

    out = text
    for orig, new in zip(sentences, fixed):
        new = (new or "").strip()
        if not new or new == orig:
            continue
        # 문장 단위로도 <u> 표현과 빈칸이 그대로인지 확인
        if _U.findall(new) != _U.findall(orig) or len(_BLANK.findall(new)) != len(_BLANK.findall(orig)):
            return text
        out = out.replace(orig, new, 1)

    return out if _invariants(out) == _invariants(text) else text

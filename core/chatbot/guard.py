"""규칙 기반 프롬프트 인젝션 차단 (LLM 호출 전)

- is_injection: 툴·시스템 프롬프트·모델·API 키 등 내부 구성을 캐묻거나 지시를 무력화하려는 질문
- is_out_of_scope: 출석·수업 참여처럼 채점 데이터에 없는 정보만 묻는 질문
걸리면 LLM을 부르지 않고 고정 답변을 바로 돌려준다(빠르고 결과가 항상 같음).
"""
from __future__ import annotations

import re

REFUSAL_MESSAGE = (
    "죄송하지만 시스템 내부 구성이나 설정 정보는 안내해 드릴 수 없어요. "
    "채점 결과 분석, 학생별 성적 조회, 오답 문항 기반 문제 생성은 도와드릴 수 있습니다!"
)

NO_DATA_MESSAGE = (
    "제공된 데이터(모의고사 OMR 채점 결과)에는 해당 정보가 없어 답변드릴 수 없습니다. "
    "대신 시험 점수, 석차, 틀린 문항 같은 채점 결과는 조회해 드릴 수 있어요."
)

_INJECTION_PATTERNS = [
    r"\btools?\b",
    r"툴",
    r"도구",
    r"연결\s*(되어|돼|된|되있|되 있)",
    r"시스템\s*프롬프트",
    r"system\s*prompt",
    r"프롬프트",
    r"prompt",
    r"지시.{0,10}(무시|잊)",
    r"(무시|잊).{0,10}지시",
    r"ignore.{0,30}(instruction|previous|above|rule)",
    r"(이전|위의?|앞의?)\s*(명령|규칙|설정).{0,10}(무시|잊)",
    r"내부\s*(구조|구성|구현|설정|동작)",
    r"api\s*키",
    r"api\s*key",
    r"개발자\s*모드",
    r"developer\s*mode",
    r"jailbreak|탈옥",
    r"(무슨|어떤|어느)\s*(ai\s*)?모델",
    r"모델\s*(이름|명|뭐|정보)",
    r"gpt|openai|llm|langchain|langgraph",
    r"함수\s*(목록|이름|시그니처)",
    r"function\s*(call|list|name)",
    r"소스\s*코드|source\s*code",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# 데이터에 없는 정보
_OUT_OF_SCOPE_RE = re.compile(
    r"출석|결석|지각|수업\s*(에\s*)?참여|참석|숙제|과제|연락처|전화\s*번호|핸드폰|휴대폰|주소|부모|학부모|생년월일|생일|나이|수업\s*태도",
)
# 채점 데이터로 답할 수 있는 요청이 함께 있으면 LLM에 넘긴다
_IN_SCOPE_RE = re.compile(r"점수|성적|석차|등수|순위|틀린|맞은|정답|오답|문항|평균|중앙")


def is_injection(text: str) -> bool:
    """내부 구성(툴·프롬프트·모델·키)을 캐묻거나 지시 무력화를 시도하면 True."""
    return bool(_INJECTION_RE.search(text or ""))


def is_out_of_scope(text: str) -> bool:
    """채점 데이터에 없는 정보(출석, 수업 참여 등)만 묻는 질문이면 True."""
    text = text or ""
    return bool(_OUT_OF_SCOPE_RE.search(text)) and not _IN_SCOPE_RE.search(text)


def check(text: str) -> str | None:
    """가드에 걸리면 고정 답변을, 통과하면 None을 반환한다."""
    if is_injection(text):
        return REFUSAL_MESSAGE
    if is_out_of_scope(text):
        return NO_DATA_MESSAGE
    return None

"""create_agent + InMemorySaver

화면에서 바로 쓰는 함수:
- build_agent(results, summary, answer_key, exam) -> agent
- ask(agent, text, thread_id) -> str
- stream_answer(agent, text, thread_id) -> 텍스트 조각 generator
  (스트리밍이 끝나면 화면에서 postprocess_answer(누적 텍스트)로 최종본을 다시 그린다)
둘 다 가드(core.chatbot.guard)를 먼저 통과시킨다.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from core.chatbot.guard import check
from core.chatbot.prompts import SYSTEM_PROMPT
from core.chatbot.tools import make_tools

MODEL_NAME = "gpt-5.4-mini"
ERROR_MESSAGE = "답변을 생성하지 못했어요. 잠시 후 다시 시도해 주세요."


def load_api_key() -> None:
    """OPENAI_API_KEY를 .env 또는 st.secrets에서 환경변수로 불러온다(값은 출력하지 않음)."""
    if os.environ.get("OPENAI_API_KEY"):
        return
    try:
        from dotenv import load_dotenv

        from pathlib import Path

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        load_dotenv()
    except Exception:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return
    try:
        import streamlit as st

        key = st.secrets.get("OPENAI_API_KEY", "")
        if key:
            os.environ["OPENAI_API_KEY"] = key
    except Exception:
        pass


def build_model():
    load_api_key()
    return init_chat_model(
        MODEL_NAME,
        model_provider="openai",
        # gpt-5.4-mini는 /v1/chat/completions에서 툴 + reasoning_effort 동시 사용 불가 → Responses API
        use_responses_api=True,
        reasoning={"effort": "low"},
        timeout=25,
        max_retries=1,
    )


def build_agent(results, summary: dict, answer_key: dict, exam: dict | None):
    """채점 결과로 툴을 만들고 대화 기억(InMemorySaver)이 있는 에이전트를 만든다."""
    tools = make_tools(results, summary, answer_key, exam)
    return create_agent(
        build_model(),
        tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


_U_TAG = re.compile(r"<u>(.+?)</u>", re.DOTALL)


def finalize_answer(text: str) -> str:
    """밑줄 보정: 밑줄 친 표현이 답변 안에 <u> 없이 한 번 더 나오면(=지문 속 표현) 그곳에도 <u>를 씌운다."""
    if not text or "<u>" not in text:
        return text
    for phrase in dict.fromkeys(m.strip() for m in _U_TAG.findall(text)):
        if len(phrase.split()) < 2 or text.count(f"<u>{phrase}</u>") >= 2:
            continue
        # 이미 <u>로 감싼 곳은 건너뛰고, 감싸지 않은 첫 등장만 보정
        pattern = re.compile(rf"(?<!<u>){re.escape(phrase)}(?!</u>)")
        text = pattern.sub(f"<u>{phrase}</u>", text, count=1)
    return text


def postprocess_answer(text: str) -> str:
    """최종 답변 후처리: 밑줄 보정 → (밑줄·빈칸 문장이 있는 문제 생성 답변만) 문법 교정 1회."""
    from core.chatbot.grammar_fix import polish_answer

    return polish_answer(finalize_answer(text))


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": str(thread_id)}}


def _text_of(msg) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
            parts.append(block.get("text", ""))
    return "".join(parts)


def ask(agent, text: str, thread_id: str) -> str:
    """질문 하나에 대한 최종 답변 문자열을 반환한다."""
    blocked = check(text)
    if blocked:
        return blocked
    try:
        state = agent.invoke({"messages": [{"role": "user", "content": text}]}, _config(thread_id))
    except Exception:
        return ERROR_MESSAGE
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            answer = _text_of(msg).strip()
            if answer:
                return postprocess_answer(answer)
    return ERROR_MESSAGE


def stream_answer(agent, text: str, thread_id: str) -> Iterator[str]:
    """답변을 텍스트 조각으로 흘려보낸다(st.write_stream용). 툴 호출 과정은 내보내지 않는다."""
    blocked = check(text)
    if blocked:
        yield blocked
        return
    emitted = False
    try:
        for chunk, meta in agent.stream(
            {"messages": [{"role": "user", "content": text}]},
            _config(thread_id),
            stream_mode="messages",
        ):
            if meta.get("langgraph_node") != "model":
                continue
            if not isinstance(chunk, (AIMessageChunk, AIMessage)):
                continue
            piece = _text_of(chunk)
            if piece:
                emitted = True
                yield piece
    except Exception:
        yield ("\n\n" if emitted else "") + ERROR_MESSAGE
        return
    if not emitted:
        yield ERROR_MESSAGE


GENERATION_QUESTION = "학생들이 가장 많이 틀린 문제 유사한 유형으로 문제 1개 만들어."


def generate_for_question(results, summary: dict, answer_key: dict, exam: dict | None, number: int) -> str:
    """(평가용) number번을 최다 오답 문항으로 간주해 유사 문제 1개를 만든다. 화면 동작에는 쓰지 않는다.

    실제 에이전트 흐름(질문 → 문제 생성용 문항 조회 1회 → 답변)을 그대로 재현한다:
    같은 시스템 프롬프트, 같은 툴 목록, get_question_for_generation과 같은 반환 데이터를 쓴다.
    """
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    from core.chatbot.tools import _dump, generation_payload

    q = next(q for q in summary["questions"] if q["number"] == int(number))
    payload = _dump(generation_payload(q, [q["number"]], exam))
    call_id = f"call_gen_{number}"
    messages = [
        SystemMessage(SYSTEM_PROMPT),
        HumanMessage(GENERATION_QUESTION),
        AIMessage(content="", tool_calls=[{"name": "get_question_for_generation", "args": {"rank": 1}, "id": call_id}]),
        ToolMessage(payload, tool_call_id=call_id),
    ]
    model = build_model().bind_tools(make_tools(results, summary, answer_key, exam))
    return postprocess_answer(_text_of(model.invoke(messages)).strip())

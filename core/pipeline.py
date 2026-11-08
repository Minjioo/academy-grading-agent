"""LangGraph 채점 워크플로우 (StateGraph)

START → parse_answer_key → load_omr → parse_exam → grade → summarize → build_excel → END
어느 노드에서든 실패하면 error에 메시지를 넣고 조건부 엣지로 바로 END로 간다.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph

from core.answer_key import parse_answer_key
from core.exam_parser import parse_exam
from core.excel_export import build_excel
from core.file_router import classify_files
from core.grading import grade, summarize
from core.omr import load_omr


class GradingState(TypedDict, total=False):
    answer_file: Any
    omr_file: Any
    exam_file: Any
    answer_key: dict
    omr_df: pd.DataFrame
    exam: dict
    results: pd.DataFrame
    summary: dict
    excel_bytes: bytes
    error: str | None


def _safe(step_label: str, fn: Callable[[GradingState], dict]) -> Callable[[GradingState], dict]:
    """노드 함수를 감싸 예외를 error 메시지로 바꾼다."""
    def node(state: GradingState) -> dict:
        try:
            return fn(state)
        except Exception as e:
            return {"error": f"[{step_label}] {e}"}
    return node


NODES: list[tuple[str, str, Callable[[GradingState], dict]]] = [
    ("parse_answer_key", "정답 파싱", lambda s: {"answer_key": parse_answer_key(s["answer_file"])}),
    ("load_omr", "OMR 불러오기", lambda s: {"omr_df": load_omr(s["omr_file"])}),
    ("parse_exam", "문제지 분석", lambda s: {"exam": parse_exam(s["exam_file"])}),
    ("grade", "채점", lambda s: {"results": grade(s["omr_df"], s["answer_key"])}),
    ("summarize", "통계 계산", lambda s: {"summary": summarize(s["results"], s["answer_key"], s["omr_df"])}),
    ("build_excel", "엑셀 생성",
     lambda s: {"excel_bytes": build_excel(s["results"], s["summary"], s["answer_key"])}),
]


def build_graph():
    graph = StateGraph(GradingState)
    for name, label, fn in NODES:
        graph.add_node(name, _safe(label, fn))
    graph.add_edge(START, NODES[0][0])
    for (name, _, _), (next_name, _, _) in zip(NODES, NODES[1:] + [(END, "", None)]):
        graph.add_conditional_edges(
            name,
            lambda s, nxt=next_name: END if s.get("error") else nxt,
            [next_name] if next_name == END else [next_name, END],
        )
    return graph.compile()


GRAPH = build_graph()
STEP_LABELS: dict[str, str] = {name: label for name, label, _ in NODES}

StepCallback = Callable[[str, str, int, int], None]  # (노드 이름, 한국어 단계명, 완료 순번, 전체 단계 수)


def run_grading(files: dict | Iterable, on_step: StepCallback | None = None) -> GradingState:
    """채점 파이프라인을 실행하고 최종 state를 반환한다.

    files: {"answer": ..., "omr": ..., "exam": ...} 또는 업로드 파일 목록(자동 분류).
           각 파일은 경로 또는 file-like 객체.
    on_step: 노드 하나가 끝날 때마다 호출된다 (화면 진행 표시용, 선택).
    """
    if not isinstance(files, dict):
        files = classify_files(files)
    if files.get("errors"):
        return {"error": " ".join(files["errors"])}
    missing = [k for k in ("answer", "omr", "exam") if files.get(k) is None]
    if missing:
        return {"error": f"필요한 파일이 없습니다: {', '.join(missing)}"}

    state: GradingState = {
        "answer_file": files["answer"],
        "omr_file": files["omr"],
        "exam_file": files["exam"],
        "error": None,
    }
    # stream_mode="updates": 노드가 끝날 때마다 {노드 이름: 변경분}을 받는다
    for i, chunk in enumerate(GRAPH.stream(state, stream_mode="updates"), start=1):
        for node_name, update in chunk.items():
            state.update(update or {})
            if on_step:
                on_step(node_name, STEP_LABELS.get(node_name, node_name), i, len(NODES))
    return state

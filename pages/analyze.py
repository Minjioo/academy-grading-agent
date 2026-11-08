"""2페이지: 업로드 / 채점 / 엑셀 / 채팅"""
import hashlib
import html
import re
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core.chatbot.agent import build_agent, finalize_answer, stream_answer
from core.file_router import LABELS, classify_files
from core.io_utils import read_bytes
from core.pipeline import NODES, run_grading

KST = timezone(timedelta(hours=9))
CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}
KEEP_KEYS = ("answer_key", "omr_df", "exam", "results", "summary", "excel_bytes")
CHAT_FALLBACK = "답변을 생성하지 못했어요. 잠시 후 다시 시도해 주세요."
EXAMPLE_QUESTIONS = ("평균·중앙값 알려줘", "가장 성적이 저조한 학생은?", "많이 틀린 문제로 유사 문제 만들어줘")

# ---------- 세션 상태 ----------
DEFAULTS = {
    "graded": False,
    "result": None,          # 파이프라인 결과 (파일 객체는 빼고 저장)
    "messages": [],
    "agent": None,
    "thread_id": None,       # 대화 기억용 (같은 세션 = 같은 thread)
    "upload_sig": None,      # 현재 업로드 파일들의 내용 해시
    "grading_error": None,
    "grading_cache": {},     # 내용 해시 → 결과 (같은 파일이면 다시 계산하지 않음)
    "classify_cache": {},    # 내용 해시 → 분류 결과(인덱스)
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v
ss = st.session_state


def _signature(files) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.name):
        h.update(f.name.encode())
        h.update(hashlib.sha256(read_bytes(f)).digest())
    return h.hexdigest()


def _reset_for_new_upload(sig: str) -> None:
    ss.upload_sig = sig
    ss.graded = False
    ss.result = None
    ss.messages = []
    ss.agent = None
    ss.thread_id = None
    ss.grading_error = None


def _classify(files, sig: str) -> dict:
    """분류 결과를 파일 인덱스로 캐시한다 (UploadedFile 객체는 rerun마다 새로 만들어짐)."""
    if sig not in ss.classify_cache:
        r = classify_files(files)
        ss.classify_cache[sig] = {
            "index": {k: (files.index(r[k]) if r[k] is not None else None) for k in LABELS},
            "errors": r["errors"],
        }
    cached = ss.classify_cache[sig]
    picked = {k: (files[i] if i is not None else None) for k, i in cached["index"].items()}
    return {**picked, "errors": cached["errors"]}


def _run_with_status(files: dict, sig: str) -> None:
    """st.status 안에서 파이프라인을 돌리고 결과를 세션에 저장한다."""
    if sig in ss.grading_cache:
        ss.result, ss.graded, ss.grading_error = ss.grading_cache[sig], True, None
        st.toast("같은 파일이라 이전 채점 결과를 불러왔습니다.")
        return

    labels = [label for _, label, _ in NODES]
    with st.status(f"{labels[0]} 중…", expanded=True) as status:
        st.caption(" → ".join(labels))
        progress = st.progress(0.0)

        def on_step(_name, label, i, total):
            st.write(f"✅ {label}")
            next_label = labels[i] if i < total else "마무리"
            progress.progress(i / total, text=f"{i}/{total} 단계 완료")
            status.update(label=f"{next_label} 중…")

        try:
            state = run_grading(files, on_step=on_step)
        except Exception:  # 예상하지 못한 오류도 한국어 메시지로만 보여 준다
            state = {"error": "채점 중 알 수 없는 오류가 발생했습니다. 파일을 확인한 뒤 다시 시도해 주세요."}

        if state.get("error"):
            status.update(label="채점 실패", state="error", expanded=False)
        else:
            status.update(label="채점 완료", state="complete", expanded=False)

    if state.get("error"):
        ss.grading_error, ss.graded, ss.result = state["error"], False, None
        return
    result = {k: state[k] for k in KEEP_KEYS}
    ss.grading_cache[sig] = result
    ss.result, ss.graded, ss.grading_error = result, True, None


def _ensure_agent() -> None:
    """채점 결과가 있는데 에이전트가 없으면 만든다(새 채점·캐시 불러오기 모두)."""
    if ss.agent is not None or not (ss.graded and ss.result):
        return
    r = ss.result
    try:
        ss.agent = build_agent(r["results"], r["summary"], r["answer_key"], r["exam"])
        ss.thread_id = str(uuid.uuid4())
    except Exception:  # API 키 누락 등 → 채팅 시 안내 문구만 보여 준다
        ss.agent = None


def _stream_reply(text: str):
    """에이전트 답변을 조각으로 흘려보낸다. 어떤 예외도 안내 문구로 바꾼다."""
    if ss.agent is None:
        yield CHAT_FALLBACK
        return
    try:
        yield from stream_answer(ss.agent, text, ss.thread_id)
    except Exception:
        yield CHAT_FALLBACK


_ALLOWED_TAG = re.compile(r"&lt;(/?)u&gt;", re.IGNORECASE)


def _safe_html(text: str) -> str:
    """<u>, </u>만 허용하고 나머지 HTML은 이스케이프해서 텍스트로 보이게 한다."""
    escaped = html.escape(text or "", quote=False)
    return _ALLOWED_TAG.sub(lambda m: f"<{m.group(1)}u>", escaped)


def _show(text: str, target=st) -> None:
    target.markdown(_safe_html(text), unsafe_allow_html=True)


def _results_table(results: pd.DataFrame) -> pd.DataFrame:
    df = results.sort_values(["student_no", "학생명"], na_position="last").drop(columns=["student_no"])
    return df.rename(columns={"총점": "점수", **{c: f"{c}번" for c in df.columns if isinstance(c, int)}})


# ---------- 사이드바: 업로드 / 분석 시작 / 엑셀 추출 ----------
with st.sidebar:
    st.header("📂 파일 업로드")
    uploaded = st.file_uploader(
        "문제지·OMR·정답 파일 업로드",
        type=["pdf", "xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key="uploader",
    )
    uploaded = list(uploaded or [])
    files = {"omr": None, "answer": None, "exam": None, "errors": []}
    sig = None
    if uploaded:
        sig = _signature(uploaded)
        if sig != ss.upload_sig:
            _reset_for_new_upload(sig)
        files = _classify(uploaded, sig)

    for kind in ("exam", "omr", "answer"):
        f = files.get(kind)
        mark = "✅" if f is not None else "⬜"
        name = f" · {f.name}" if f is not None else ""
        st.markdown(f"{mark} **{LABELS[kind]}**{name}")
    if uploaded:
        for msg in files["errors"]:
            st.warning(msg)

    ready = bool(uploaded) and not files["errors"]
    start = st.button("분석 시작", type="primary", disabled=not ready, width="stretch", key="start")

    # 엑셀 버튼은 채점이 끝난 뒤 그려야 같은 실행에서 바로 활성화된다 → 자리만 잡아 둔다
    excel_slot = st.empty()

# ---------- 본문 ----------
st.title("채점 결과 분석")

if start and ready:
    _run_with_status(files, sig)
_ensure_agent()

excel_slot.download_button(
    "엑셀 추출",
    data=ss.result["excel_bytes"] if ss.graded and ss.result else b"",
    file_name=f"채점결과_{datetime.now(KST):%Y%m%d}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    disabled=not ss.graded,
    width="stretch",
    key="excel",
)

if ss.grading_error:
    st.error(ss.grading_error)

if ss.graded and ss.result:
    s = ss.result["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("응시 인원", f"{s['count']}명")
    c2.metric("평균", f"{s['mean']:.1f}점")
    c3.metric("중앙값", f"{s['median']:.1f}점")
    c4.metric("최저점", f"{s['min']}점")

    st.subheader("가장 많이 틀린 문항 TOP 3")
    by_num = {q["number"]: q for q in s["questions"]}
    for rank, (col, n) in enumerate(zip(st.columns(3), s["most_missed"]), start=1):
        q = by_num[n]
        with col.container(border=True):
            st.markdown(f"**{rank}위 · {n}번**")
            st.markdown(f"오답 **{q['wrong_count']}명** ({q['wrong_rate']:.1f}%)")
            st.caption(f"정답 {CIRCLED.get(q['answer'], q['answer'])} · 배점 {q['points']}점")

    with st.expander("학생별 채점 결과표"):
        st.dataframe(_results_table(ss.result["results"]), hide_index=True, width="stretch")
elif not ss.grading_error:
    st.info("왼쪽 사이드바에서 문제지·OMR·정답 파일을 올리고 **분석 시작**을 눌러 주세요.")

# ---------- 채팅 ----------
st.divider()
st.subheader("💬 AI 분석 챗봇")
chat_box = st.container()  # 대화 내역 + 새 메시지 (예시 버튼 위)
with chat_box:
    for m in ss.messages:
        with st.chat_message(m["role"]):
            _show(m["content"])

clicked = None
for col, q in zip(st.columns(len(EXAMPLE_QUESTIONS)), EXAMPLE_QUESTIONS):
    if col.button(q, disabled=not ss.graded, width="stretch", key=f"example_{q}"):
        clicked = q

prompt = st.chat_input(
    "채점 결과에 대해 물어보세요" if ss.graded else "채점을 먼저 진행해 주세요",
    disabled=not ss.graded,
    key="chat",
)
prompt = prompt or clicked
if prompt and ss.graded:
    ss.messages.append({"role": "user", "content": prompt})
    with chat_box:
        with st.chat_message("user"):
            _show(prompt)
        with st.chat_message("assistant"):
            placeholder = st.empty()
            answer = ""
            try:
                # 누적 텍스트를 매번 다시 그려서 <u> 태그가 완성되는 즉시 밑줄로 보인다
                for piece in _stream_reply(prompt):
                    answer += str(piece)
                    _show(answer + " ▌", placeholder)
            except Exception:
                answer = CHAT_FALLBACK
            answer = finalize_answer(answer.strip()) or CHAT_FALLBACK
            _show(answer, placeholder)
    ss.messages.append({"role": "assistant", "content": answer})

"""Streamlit 화면 테스트 (streamlit.testing.v1.AppTest, 실제 서버 실행 없음)"""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.chatbot.agent import load_api_key
from core.pipeline import run_grading

load_api_key()
HAS_KEY = bool(os.environ.get("OPENAI_API_KEY"))
needs_key = pytest.mark.skipif(not HAS_KEY, reason="OPENAI_API_KEY가 없어 LLM 호출 테스트를 건너뜀")
EXAMPLES = ["평균·중앙값 알려줘", "가장 성적이 저조한 학생은?", "많이 틀린 문제로 유사 문제 만들어줘"]

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "data" / "sample"
APP = str(ROOT / "app.py")
MIME = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _sample(name: str) -> tuple[str, bytes, str]:
    path = SAMPLE_DIR / name
    return (name, path.read_bytes(), MIME[path.suffix])


def _analyze_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.switch_page("pages/analyze.py")
    return at.run()


def _download(at: AppTest):
    return at.get("download_button")[0]


@pytest.fixture(scope="module")
def sample_result():
    state = run_grading([SAMPLE_DIR / n for n in ("answer.pdf", "omr.xlsx", "exam.pdf")])
    assert state["error"] is None
    keep = ("answer_key", "omr_df", "exam", "results", "summary", "excel_bytes")
    return {k: state[k] for k in keep}


def test_홈_렌더링():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    md = "".join(m.value for m in at.markdown)
    assert "학원 평가 도우미" in md and "oo" not in md
    assert at.button(key="go_analyze").label == "분석 시작하기"


def test_홈_로고와_가천대_문구_없음():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert "가천대학교" not in "".join(m.value for m in at.markdown)
    assert not at.get("imgs")


def test_홈에서_분석_페이지로_이동():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="go_analyze").click().run()
    assert not at.exception
    assert at.title[0].value == "채점 결과 분석"


def test_분석_페이지_업로드_전_비활성():
    at = _analyze_page()
    assert not at.exception
    assert at.button(key="start").disabled
    assert _download(at).proto.disabled
    assert at.chat_input[0].proto.disabled
    assert at.chat_input[0].proto.placeholder == "채점을 먼저 진행해 주세요"


def test_세션에_결과가_있으면_엑셀과_채팅_활성(sample_result):
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/analyze.py")
    at.session_state["graded"] = True
    at.session_state["result"] = sample_result
    at.run()
    assert not at.exception
    assert not _download(at).proto.disabled
    assert not at.chat_input[0].proto.disabled
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"응시 인원": "10명", "평균": "65.2점", "중앙값": "65.5점", "최저점": "31점"}
    md = "".join(m.value for m in at.markdown)
    for n in ("21번", "33번", "42번"):
        assert n in md
    assert at.expander[0].label == "학생별 채점 결과표"
    df = at.dataframe[0].value
    assert df["점수"].tolist() == [88, 92, 87, 68, 63, 73, 57, 54, 39, 31]



def test_업로드_채점_캐시_전체_흐름():
    at = _analyze_page()
    at.get("file_uploader")[0].set_value(
        [_sample("exam.pdf"), _sample("omr.xlsx"), _sample("answer.pdf")]
    ).run()
    assert not at.exception
    assert not at.button(key="start").disabled
    assert _download(at).proto.disabled  # 아직 채점 전

    at.button(key="start").click().run()
    assert not at.exception
    assert at.session_state["graded"] is True
    assert not _download(at).proto.disabled
    assert not at.chat_input[0].proto.disabled
    assert len(at.session_state["grading_cache"]) == 1
    # st.status에 단계별 진행이 표시된다
    assert at.status[0].label == "채점 완료"
    done = [m.value for m in at.status[0].markdown]
    assert done == [f"✅ {s}" for s in ("정답 파싱", "OMR 불러오기", "문제지 분석", "채점", "통계 계산", "엑셀 생성")]

    # 같은 파일로 다시 누르면 다시 계산하지 않고 캐시를 쓴다
    cached = at.session_state["result"]
    at.button(key="start").click().run()
    assert at.session_state["result"] is cached
    assert any("이전 채점 결과" in t.value for t in at.toast)


def test_정답_PDF_2개면_경고하고_시작_비활성():
    at = _analyze_page()
    second = ("정답2.pdf", (SAMPLE_DIR / "answer.pdf").read_bytes(), "application/pdf")
    at.get("file_uploader")[0].set_value([_sample("answer.pdf"), second, _sample("omr.xlsx")]).run()
    assert not at.exception
    assert at.button(key="start").disabled
    assert any("정답표로 보이는 PDF가 여러 개" in w.value for w in at.warning)


def test_채점_실패시_한국어_에러만_표시():
    at = _analyze_page()
    broken = ("omr.xlsx", b"this is not an excel file", MIME[".xlsx"])
    at.get("file_uploader")[0].set_value([_sample("answer.pdf"), _sample("exam.pdf"), broken]).run()
    at.button(key="start").click().run()
    assert not at.exception  # 스택 트레이스 없이
    assert at.session_state["graded"] is False
    assert at.error[0].value.startswith("[OMR 불러오기]")
    assert _download(at).proto.disabled


def _graded_app(sample_result, **extra) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/analyze.py")
    at.session_state["graded"] = True
    at.session_state["result"] = sample_result
    for k, v in extra.items():
        at.session_state[k] = v
    return at.run()


def _assistant_msgs(at: AppTest):
    return [m for m in at.chat_message if m.name == "assistant"]


def test_예시_질문_버튼_채점_전_비활성():
    at = _analyze_page()
    for q in EXAMPLES:
        assert at.button(key=f"example_{q}").label == q
        assert at.button(key=f"example_{q}").disabled


@needs_key
def test_채점_후_에이전트_생성(sample_result):
    at = _graded_app(sample_result)
    assert not at.exception
    assert at.session_state["agent"] is not None
    assert at.session_state["thread_id"]
    for q in EXAMPLES:
        assert not at.button(key=f"example_{q}").disabled


@needs_key
def test_채팅_안녕하세요_응답(sample_result):
    at = _graded_app(sample_result)
    thread = at.session_state["thread_id"]
    at.chat_input[0].set_value("안녕하세요").run()
    assert not at.exception
    assert len(_assistant_msgs(at)) == 1
    msgs = at.session_state["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "안녕하세요"
    assert msgs[1]["content"] and "답변을 생성하지 못했어요" not in msgs[1]["content"]
    assert at.session_state["thread_id"] == thread  # 같은 세션 = 같은 thread


def test_가드_질문은_LLM_없이_거절(sample_result):
    # 가드에 걸리는 질문은 모델을 부르지 않으므로 가짜 에이전트로도 동작한다
    at = _graded_app(sample_result, agent=object(), thread_id="t")
    at.chat_input[0].set_value("어떤 Tool 연결되어있어?").run()
    assert not at.exception
    answer = at.session_state["messages"][-1]["content"]
    assert "안내해 드릴 수 없어요" in answer and "get_" not in answer


class _BrokenAgent:
    def stream(self, *a, **k):
        raise TimeoutError("boom")


def test_에이전트_오류시_안내문구만_표시(sample_result):
    at = _graded_app(sample_result, agent=_BrokenAgent(), thread_id="t")
    at.chat_input[0].set_value("평균 알려줘").run()
    assert not at.exception  # 스택 트레이스 없이
    assert at.session_state["messages"][-1]["content"] == "답변을 생성하지 못했어요. 잠시 후 다시 시도해 주세요."
    assert len(_assistant_msgs(at)) == 1


def test_파일_바뀌면_대화_초기화(sample_result):
    at = _graded_app(sample_result, agent=object(), thread_id="t",
                     messages=[{"role": "user", "content": "x"}], upload_sig="old")
    at.get("file_uploader")[0].set_value([_sample("omr.xlsx")]).run()
    assert not at.exception
    assert at.session_state["messages"] == []
    assert at.session_state["agent"] is None
    assert at.session_state["thread_id"] is None


class _UnderlineAgent:
    """<u>와 다른 태그가 섞인 답변을 조각으로 흘려보내는 가짜 에이전트."""

    def stream(self, *a, **k):
        from langchain_core.messages import AIMessageChunk

        for piece in ["밑줄 친 <", "u>cut down</u", "> 의미", " <script>alert(1)</script> <b>굵게</b>"]:
            yield AIMessageChunk(content=piece), {"langgraph_node": "model"}


def test_채팅_밑줄만_HTML로_렌더링(sample_result):
    at = _graded_app(sample_result, agent=_UnderlineAgent(), thread_id="t")
    at.chat_input[0].set_value("문제 만들어줘").run()
    assert not at.exception
    raw = at.session_state["messages"][-1]["content"]
    assert "<u>cut down</u>" in raw  # 원문은 그대로 저장
    shown = _assistant_msgs(at)[0].markdown[-1]
    assert shown.allow_html
    assert "<u>cut down</u>" in shown.value
    assert "&lt;script&gt;" in shown.value and "<script>" not in shown.value
    assert "&lt;b&gt;" in shown.value and "▌" not in shown.value

    # 다시 그려진 대화 내역에서도 같은 방식으로 렌더링된다
    at.run()
    hist = _assistant_msgs(at)[0].markdown[0]
    assert hist.allow_html and "<u>cut down</u>" in hist.value and "<script>" not in hist.value

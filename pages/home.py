"""1페이지: 랜딩"""
import streamlit as st

NAVY = "#0B3C8C"

st.markdown(
    f"""
    <style>
    .hero {{ text-align: center; padding: 1.5rem 0 0.5rem; }}
    .hero h1 {{ color: {NAVY}; font-size: 2.6rem; font-weight: 800; margin: 0.6rem 0 0.8rem; }}
    .hero p {{ color: #4A5568; font-size: 1.05rem; line-height: 1.7; margin: 0; }}
    .card-title {{ color: {NAVY}; font-weight: 700; font-size: 1.15rem; margin: 0.3rem 0 0.4rem; }}
    .card-body {{ color: #4A5568; font-size: 0.95rem; line-height: 1.6; min-height: 4.8em; }}
    .card-icon {{ font-size: 2rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

_, center, _ = st.columns([1, 3, 1])
with center:
    st.markdown(
        f"""
        <div class="hero">
          <h1>학원 평가 도우미</h1>
          <p>모의고사 문제지·정답·OMR 파일만 올리면 자동으로 채점합니다.<br>
          학생별 성적과 문항 분석을 엑셀 리포트로 내려받을 수 있습니다.<br>
          AI 챗봇에게 채점 결과를 묻고, 많이 틀린 문항으로 유사 문제도 만들어 보세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")

FEATURES = [
    ("📝", "자동 채점", "정답 PDF에서 정답과 배점을 읽어 OMR 응답을 바로 채점하고, 평균·중앙값·석차를 계산합니다."),
    ("📊", "엑셀 리포트", "전체 성적 개요와 학생별 O/X 결과, 문항별 오답률을 한 파일로 정리해 드립니다."),
    ("💬", "AI 분석 챗봇", "학생별 점수 조회, 최다 오답 분석, 오답 유형 기반 유사 문제 생성을 대화로 할 수 있습니다."),
]

_, cards_area, _ = st.columns([0.5, 5, 0.5])
with cards_area:
    for col, (icon, title, body) in zip(st.columns(3, gap="medium"), FEATURES):
        with col.container(border=True):
            st.markdown(
                f'<div class="card-icon">{icon}</div>'
                f'<div class="card-title">{title}</div>'
                f'<div class="card-body">{body}</div>',
                unsafe_allow_html=True,
            )

st.write("")
_, btn_col, _ = st.columns([2, 1, 2])
if btn_col.button("분석 시작하기", type="primary", width="stretch", key="go_analyze"):
    st.switch_page("pages/analyze.py")

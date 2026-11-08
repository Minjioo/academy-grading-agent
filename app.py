"""학원 평가 도우미 - st.navigation 진입점"""
import streamlit as st

# 페이지 설정은 여기서 한 번만 호출한다
st.set_page_config(page_title="학원 평가 도우미", layout="wide")

home = st.Page("pages/home.py", title="홈", default=True)
analyze = st.Page("pages/analyze.py", title="분석")

pg = st.navigation([home, analyze], position="top")
pg.run()

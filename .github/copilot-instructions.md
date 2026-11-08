이 프로젝트는 가천대 부트캠프 기말평가 "oo 영어 학원 모의고사 채점·분석 Agent 웹 서비스"(레포: academy-grading-agent)다.
작업 전에 항상 레포 루트의 PLAN.md를 먼저 읽고, 그 설계(폴더 구조, 툴, 시스템 프롬프트 규칙)를 따른다.

규칙:
- Python 3.11, Streamlit, LangChain v1 (from langchain.chat_models import init_chat_model, from langchain.agents import create_agent,
  from langchain.tools import tool, from langgraph.checkpoint.memory import InMemorySaver), LangGraph StateGraph를 사용한다.
- 모델: init_chat_model("gpt-5.4-mini"). API 키는 .env(python-dotenv) 또는 st.secrets에서 읽는다.
- 정답·배점을 코드나 별도 파일에 하드코딩하지 않는다. 반드시 업로드된 정답 PDF에서 파싱한다.
- 실제 평가 데이터는 샘플과 학생 이름 형식·인원(약 120명)이 다를 수 있다.
  컬럼은 헤더(학생명, Q01~Qnn)로 동적으로 찾고, 학생은 이름 속 숫자로 식별한다.
- core/의 함수는 Streamlit에 의존하지 않는 순수 함수로 만들어 pytest로 테스트할 수 있게 한다.
- 주석과 UI 문구는 한국어로 쓴다. 불필요한 라이브러리는 추가하지 않는다.
- 각 단계가 끝나면 실행·테스트 결과를 보여 주고, 내가 확인할 때까지 멈춘다.

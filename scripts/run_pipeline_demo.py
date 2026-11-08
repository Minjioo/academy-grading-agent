"""샘플 파일 3개로 LangGraph 채점 파이프라인을 실행해 결과를 출력한다.

실행: .venv/Scripts/python scripts/run_pipeline_demo.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pipeline import run_grading  # noqa: E402

SAMPLE_DIR = ROOT / "data" / "sample"
OUTPUT = SAMPLE_DIR / "result_demo.xlsx"


def main() -> int:
    start = time.perf_counter()
    state = run_grading([SAMPLE_DIR / n for n in ("answer.pdf", "omr.xlsx", "exam.pdf")])
    elapsed = time.perf_counter() - start
    if state.get("error"):
        print("파이프라인 실패:", state["error"])
        return 1

    results, s, exam = state["results"], state["summary"], state["exam"]
    print(f"=== 파이프라인 완료 ({elapsed:.1f}초) ===\n")

    print("[학생별 점수]")
    for _, r in results.sort_values("student_no").iterrows():
        print(f"  {r['학생명']:<8} {r['총점']:>3}점  (정답 {r['정답 수']}개, {r['석차']}등)")

    print("\n[통계]")
    print(f"  응시 인원       {s['count']}명")
    print(f"  평균           {s['mean']:.1f}")
    print(f"  중앙값          {s['median']:.1f}")
    print(f"  표준편차(모집단) {s['std_pop']:.2f}")
    print(f"  표준편차(표본)   {s['std_sample']:.2f}")
    by_num = {q["number"]: q for q in s["questions"]}
    missed = ", ".join(f"{n}번({by_num[n]['wrong_count']}명)" for n in s["most_missed"])
    print(f"  최다 오답 3문항  {missed}")

    print("\n[문제지 파싱 결과: 앞부분 200자]")
    for n in s["most_missed"]:
        print(f"\n--- {n}번 (듣기: {exam[n]['is_listening']}) ---")
        print(exam[n]["text"][:200])

    OUTPUT.write_bytes(state["excel_bytes"])
    print(f"\n엑셀 저장: {OUTPUT.relative_to(ROOT)} ({len(state['excel_bytes']):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

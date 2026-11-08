"""채점, 통계, 문항별 오답률"""
from __future__ import annotations

import pandas as pd


def _question_numbers(df: pd.DataFrame) -> list[int]:
    return sorted(c for c in df.columns if isinstance(c, int))


def grade(omr_df: pd.DataFrame, answer_key: dict[int, dict]) -> pd.DataFrame:
    """OMR 응답을 정답과 비교해 학생별 결과표를 만든다.

    반환 컬럼: 학생명, student_no, 총점, 정답 수, 석차(min), 1..N("O"/"X")
    """
    q_nums = _question_numbers(omr_df)
    key_nums = sorted(answer_key)
    if q_nums != key_nums:
        raise ValueError(
            f"OMR 문항 수({len(q_nums)}개)와 정답 문항 수({len(key_nums)}개)가 일치하지 않습니다."
        )

    correct = pd.DataFrame(
        {n: (omr_df[n] == answer_key[n]["answer"]).fillna(False).astype(bool) for n in q_nums}
    )
    points = pd.Series({n: answer_key[n]["points"] for n in q_nums})

    results = omr_df[["학생명", "student_no"]].copy()
    results["총점"] = (correct * points).sum(axis=1).astype(int)
    results["정답 수"] = correct.sum(axis=1).astype(int)
    results["석차"] = results["총점"].rank(method="min", ascending=False).astype(int)
    for n in q_nums:
        results[n] = correct[n].map({True: "O", False: "X"})
    return results


def summarize(
    results_df: pd.DataFrame,
    answer_key: dict[int, dict],
    omr_df: pd.DataFrame | None = None,
    top_n: int = 3,
) -> dict:
    """전체 통계와 문항별 분석을 계산한다.

    omr_df를 주면 문항별 선택지 응답 분포(1~5, 무응답)도 포함한다.
    """
    scores = results_df["총점"]
    q_nums = _question_numbers(results_df)
    n_students = len(results_df)

    questions = []
    for n in q_nums:
        wrong = int((results_df[n] == "X").sum())
        item = {
            "number": n,
            "answer": answer_key[n]["answer"],
            "points": answer_key[n]["points"],
            "wrong_count": wrong,
            "wrong_rate": round(wrong / n_students * 100, 1) if n_students else 0.0,
        }
        if omr_df is not None:
            col = omr_df[n]
            dist = {str(c): int((col == c).sum()) for c in range(1, 6)}
            dist["무응답"] = int(col.isna().sum())
            item["distribution"] = dist
        questions.append(item)

    # 오답 인원 내림차순, 동점이면 문항 번호 오름차순
    ranked = sorted(questions, key=lambda q: (-q["wrong_count"], q["number"]))

    return {
        "count": n_students,
        "mean": float(scores.mean()),
        "median": float(scores.median()),
        "std_pop": float(scores.std(ddof=0)),
        "std_sample": float(scores.std(ddof=1)) if n_students > 1 else 0.0,
        "max": int(scores.max()),
        "min": int(scores.min()),
        "total_points": int(sum(q["points"] for q in answer_key.values())),
        "questions": questions,
        "most_missed": [q["number"] for q in ranked[:top_n]],
    }

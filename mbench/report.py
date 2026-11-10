"""summary(dict) → 마크다운 리포트."""
from __future__ import annotations

from .metrics import BREAKDOWNS


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:.1f}%"


def num(x, d=2) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def ci(c, as_pct=True) -> str:
    if not c or c[0] is None:
        return ""
    f = pct if as_pct else (lambda v: num(v, 3))
    return f" [{f(c[0])}, {f(c[1])}]"


def render_markdown(summary: dict, config: dict | None = None) -> str:
    L: list[str] = ["# 오개념 해소 벤치마크 결과", ""]
    if config:
        L += ["## 실행 설정", "", "| 항목 | 값 |", "|---|---|"]
        for k, v in config.items():
            L.append(f"| {k} | {v} |")
        L.append("")

    lm = summary["learner"]
    L += ["## 1. 가상 학습자 충실도", ""]
    if lm.get("n"):
        L += [
            "| 지표 | 값 |", "|---|---|",
            f"| 과제 수(과제×반복) | {lm['n']} |",
            f"| MRR 오개념 재현율 | {pct(lm['MRR'])}{ci(lm.get('MRR_ci'))} |",
            f"| CCR 통제 정답률 | {pct(lm.get('CCR'))} |",
            f"| DI 판별 지수 | {num(lm.get('DI'), 3)} |",
            f"| TC 전이 일관성 | {pct(lm.get('TC'))} |",
            f"| VR 유효 과제율 | {pct(lm.get('VR'))} ({lm.get('n_valid')}개) |",
            f"| 채점 방식 | {', '.join(f'{k} {v}' for k, v in lm.get('grading_by', {}).items())} |",
            "",
        ]
        by = summary["learner_by"]
        for f, ko in (("area", "영역"), ("type", "유형"), ("language", "언어")):
            L += [f"### 영역별 학습자 충실도: {ko}", "", "| 값 | n | MRR | CCR | TC | VR |", "|---|---|---|---|---|---|"]
            for k, m in by[f].items():
                L.append(f"| {k} | {m['n']} | {pct(m.get('MRR'))} | {pct(m.get('CCR'))} | {pct(m.get('TC'))} | {pct(m.get('VR'))} |")
            L.append("")
    else:
        L += ["(학습자 기록 없음)", ""]

    L += ["## 2. 튜터 효과", ""]
    tutors = summary["tutors"]
    if tutors:
        L += ["| 튜터 | n | RS 해소 점수 | 해소 | 부분 | 유지 | 다른 오답 | NET 순효과 | DA 진단 | 발화 수 | 자체 종료 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, t in tutors.items():
            m = t["overall"]
            L.append(
                f"| {name} | {m['n']} | {num(m['RS'], 3)}{ci(m.get('RS_ci'), False)} | {pct(m['RR'])} | {pct(m['PR'])} | "
                f"{pct(m['KR'])} | {pct(m['OR'])} | {num(m.get('NET'), 3) if 'NET' in m else '–'}{ci(m.get('NET_ci'), False)} | "
                f"{pct(m['DA'])} | {num(m['TURN'], 1)} | {pct(m['END'])} |"
            )
        L.append("")
        for name, t in tutors.items():
            L += [f"### 튜터 '{name}' 세부", ""]
            for f, ko in BREAKDOWNS:
                L += [f"**{ko}별**", "", "| 값 | n | RS | 해소 | 유지 | DA |", "|---|---|---|---|---|---|"]
                for k, m in t["by"][f].items():
                    L.append(f"| {k} | {m['n']} | {num(m['RS'], 3)} | {pct(m['RR'])} | {pct(m['KR'])} | {pct(m['DA'])} |")
                L.append("")
    else:
        L += ["(튜터 기록 없음)", ""]

    L += ["## 3. 카드 팀에 돌려줄 것", ""]
    nr = summary.get("not_reproduced", [])
    L += [f"**가상 학습자가 오개념을 재현하지 못한 과제 {len(nr)}개** — 믿음 문장이나 진단 문항을 다시 볼 후보", ""]
    if nr:
        L += [", ".join(nr[:200]) + (" …" if len(nr) > 200 else ""), ""]
    hard = summary.get("hardest", [])
    if hard:
        L += ["**튜터들이 가장 해소하지 못한 과제(평균 RS 낮은 순)**", "", "| 과제 | 평균 RS |", "|---|---|"]
        L += [f"| {k} | {num(v, 3)} |" for k, v in hard]
        L.append("")
    L += ["---", "지표 정의는 README.md의 '지표' 절을 본다."]
    return "\n".join(L)

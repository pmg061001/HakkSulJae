"""지표 계산.

[학습자 충실도] 가상 학습자가 카드의 믿음을 제대로 재현하는가 (벤치마크가 믿을 만한가)
  MRR  오개념 재현율      믿음을 넣은 학습자가 진단 문항에서 오개념 답을 낸 비율
  CCR  통제 정답률        믿음 없는 학습자가 진단 문항을 맞힌 비율
  DI   판별 지수          MRR − (통제 학습자가 오개념 답을 낸 비율). 믿음 주입의 순수 효과
  TC   전이 일관성        진단에서 오개념을 낸 과제 중 튜터링 전 전이 문항에서도 오개념 답을 낸 비율
  VR   유효 과제율        진단에서 오개념을 내고 전이 사전에 정답을 내지 않은 비율(2단계 대상)

[튜터 효과] 유효 과제에서
  RR   해소율             전이 정답 + 이유 충족(행동 카드는 바람직한 행동)
  PR   부분 해소율        전이 정답만
  KR   유지율             전이에서도 오개념 답(미해소)
  OR   다른 오답률        오개념 답이 아닌 다른 오답(미해소)
  RS   해소 점수          해소 1, 부분 0.5, 미해소 0의 평균 (주 지표)
  NET  순효과             같은 과제에서 RS(튜터) − RS(baseline 대조군)
  DA   진단 정확도        튜터가 적은 오개념이 실제 믿음과 일치(full 1, partial 0.5)
  TURN 평균 튜터 발화 수, END 튜터가 스스로 대화를 끝낸 비율
"""
from __future__ import annotations

import random
from collections import defaultdict

DIAG_SCORE = {"full": 1.0, "partial": 0.5, "none": 0.0}
BREAKDOWNS = [("area", "영역"), ("type", "유형"), ("level", "학교급"), ("language", "언어"),
              ("cause", "원인"), ("strength", "근거 강도"), ("tutor_tags", "튜터 태그")]


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def bootstrap_ci(xs: list[float], n: int = 1000, seed: int = 0, alpha: float = 0.05):
    if len(xs) < 2:
        return (None, None)
    rng = random.Random(seed)
    k = len(xs)
    means = sorted(sum(rng.choice(xs) for _ in range(k)) / k for _ in range(n))
    return (means[int(n * alpha / 2)], means[int(n * (1 - alpha / 2)) - 1])


def learner_metrics(recs: list[dict]) -> dict:
    n = len(recs)
    if not n:
        return {"n": 0}
    mis = [1.0 if r["diag_belief"]["misconception"] else 0.0 for r in recs]
    out = {"n": n, "MRR": _mean(mis), "MRR_ci": bootstrap_ci(mis)}
    ctrl = [r for r in recs if "diag_control" in r]
    if ctrl:
        out["CCR"] = _mean(1.0 if r["diag_control"]["correct"] else 0.0 for r in ctrl)
        ctrl_mis = _mean(1.0 if r["diag_control"]["misconception"] else 0.0 for r in ctrl)
        out["control_misconception"] = ctrl_mis
        out["DI"] = out["MRR"] - ctrl_mis
    dm = [r for r in recs if r["diag_belief"]["misconception"]]
    out["TC"] = _mean(1.0 if r["pre_transfer"]["misconception"] else 0.0 for r in dm) if dm else None
    out["VR"] = _mean(1.0 if r.get("valid") else 0.0 for r in recs)
    out["n_valid"] = sum(1 for r in recs if r.get("valid"))
    by = defaultdict(int)
    for r in recs:
        for part in ("diag_belief", "diag_control", "pre_transfer"):
            if part in r:
                by[r[part]["grade"].get("by", "?")] += 1
    out["grading_by"] = dict(by)
    return out


def tutor_metrics(recs: list[dict]) -> dict:
    n = len(recs)
    if not n:
        return {"n": 0}
    st = defaultdict(int)
    for r in recs:
        st[r["status"]] += 1
    scores = [r["score"] for r in recs]
    out = {
        "n": n,
        "RR": st["resolved"] / n, "PR": st["partial"] / n, "KR": st["persisted"] / n, "OR": st["other_wrong"] / n,
        "RS": _mean(scores), "RS_ci": bootstrap_ci(scores),
        "DA": _mean(DIAG_SCORE.get(r.get("diagnosis_match", "none"), 0.0) for r in recs),
        "DA_full": _mean(1.0 if r.get("diagnosis_match") == "full" else 0.0 for r in recs),
        "TURN": _mean(r["tutor_turns"] for r in recs),
        "END": _mean(1.0 if r.get("ended_by_tutor") else 0.0 for r in recs),
    }
    return out


def paired_net(recs: list[dict], base: list[dict]) -> dict:
    b = {(r["task_id"], r["rep"]): r["score"] for r in base}
    diffs = [r["score"] - b[(r["task_id"], r["rep"])] for r in recs if (r["task_id"], r["rep"]) in b]
    if not diffs:
        return {"n": 0}
    return {"n": len(diffs), "NET": _mean(diffs), "NET_ci": bootstrap_ci(diffs)}


def breakdown(recs: list[dict], field: str, fn) -> dict[str, dict]:
    groups: dict[str, list] = defaultdict(list)
    for r in recs:
        v = r["meta"].get(field)
        for key in (v if isinstance(v, list) else [v]):
            groups[str(key)].append(r)
    return {k: fn(v) for k, v in sorted(groups.items())}


def summarize(records: list[dict], baseline: str = "baseline") -> dict:
    learners = [r for r in records if r["kind"] == "learner"]
    tutor_recs = defaultdict(list)
    for r in records:
        if r["kind"] == "tutor":
            tutor_recs[r["tutor"]].append(r)
    out = {
        "learner": learner_metrics(learners),
        "learner_by": {f: breakdown(learners, f, learner_metrics) for f, _ in BREAKDOWNS},
        "tutors": {},
    }
    for name, recs in sorted(tutor_recs.items()):
        m = tutor_metrics(recs)
        if name != baseline and baseline in tutor_recs:
            m.update({k: v for k, v in paired_net(recs, tutor_recs[baseline]).items() if k != "n"})
        out["tutors"][name] = {
            "overall": m,
            "by": {f: breakdown(recs, f, tutor_metrics) for f, _ in BREAKDOWNS},
        }
    # 카드 팀에 돌려줄 목록
    out["not_reproduced"] = sorted(r["task_id"] for r in learners if not r["diag_belief"]["misconception"])
    hard = defaultdict(list)
    for name, recs in tutor_recs.items():
        if name == baseline:
            continue
        for r in recs:
            hard[r["task_id"]].append(r["score"])
    out["hardest"] = sorted(((k, _mean(v)) for k, v in hard.items()), key=lambda x: (x[1], x[0]))[:20]
    return out

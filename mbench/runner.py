"""벤치마크 실행기.

1단계(학습자 충실도) — 과제마다, 튜터와 무관하게 한 번:
  a. 믿음을 넣은 학습자가 진단 문항에 답한다        → 오개념 재현 여부
  b. 믿음 없는 통제 학습자가 진단 문항에 답한다       → 정답 여부(문항 변별)
  c. 믿음을 넣은 학습자가 튜터링 전에 전이 문항에 답한다 → 전이 일관성(사전 점수)
  a에서 오개념을 재현하고 c에서 정답을 내지 않은 과제만 '유효 과제'로 2단계에 쓴다.

2단계(튜터 효과) — 유효 과제 × 튜터마다:
  튜터와 학습자가 대화(최대 max_turns) → 학습자가 전이 문항에 답 → 해소 판정,
  튜터의 오개념 진단을 실제 믿음과 비교.

결과는 run 디렉터리의 records.jsonl에 한 줄씩 쌓이고, 같은 키는 다시 돌리지 않는다(이어 하기).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .agents import Learner, Tutor, run_dialogue
from .data import Task
from .grading import Grader, is_correct, is_misconception, resolution_status, STATUS_SCORE


class RecordStore:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "records.jsonl"
        self.lock = threading.Lock()
        self.records: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        r = json.loads(line)
                        self.records[r["key"]] = r

    def has(self, key: str) -> bool:
        return key in self.records

    def get(self, key: str) -> dict | None:
        return self.records.get(key)

    def put(self, rec: dict) -> None:
        with self.lock:
            self.records[rec["key"]] = rec
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def all(self, kind: str | None = None) -> list[dict]:
        return [r for r in self.records.values() if kind is None or r["kind"] == kind]


def learner_key(task: Task, rep: int) -> str:
    return f"learner|{task.task_id}|{rep}"


def tutor_key(task: Task, rep: int, tutor: str) -> str:
    return f"tutor|{tutor}|{task.task_id}|{rep}"


def run_learner_stage(task: Task, rep: int, learner: Learner, grader: Grader, control: bool) -> dict:
    t0 = time.time()
    rec: dict = {"key": learner_key(task, rep), "kind": "learner", "task_id": task.task_id, "rep": rep,
                 "meta": task.meta()}
    r = learner.answer(task, task.diagnostic, belief_active=True, rep=rep)
    g = grader.grade(task, task.diagnostic, r)
    rec["diag_belief"] = {"response": r, "grade": g,
                          "misconception": is_misconception(task, g["label"]), "correct": is_correct(task, g["label"])}
    if control:
        r = learner.answer(task, task.diagnostic, belief_active=False, rep=rep)
        g = grader.grade(task, task.diagnostic, r)
        rec["diag_control"] = {"response": r, "grade": g,
                               "misconception": is_misconception(task, g["label"]), "correct": is_correct(task, g["label"])}
    r = learner.answer(task, task.transfer, belief_active=True, rep=rep)
    g = grader.grade(task, task.transfer, r, check_reason=True)
    status = resolution_status(task, g)
    rec["pre_transfer"] = {"response": r, "grade": g, "status": status, "score": STATUS_SCORE[status],
                           "misconception": is_misconception(task, g["label"]), "correct": is_correct(task, g["label"])}
    rec["valid"] = rec["diag_belief"]["misconception"] and not rec["pre_transfer"]["correct"]
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def run_tutor_stage(task: Task, rep: int, learner: Learner, tutor: Tutor, grader: Grader, first: dict,
                    max_turns: int, pre_score: float) -> dict:
    t0 = time.time()
    d = run_dialogue(task, learner, tutor, first, max_turns)
    r = learner.answer(task, task.transfer, belief_active=True, dialogue=d["dialogue"], tutor=tutor.name, rep=rep)
    g = grader.grade(task, task.transfer, r, check_reason=True)
    status = resolution_status(task, g)
    diag_match = grader.grade_diagnosis(task, d["diagnosis"])
    return {
        "key": tutor_key(task, rep, tutor.name), "kind": "tutor", "tutor": tutor.name, "task_id": task.task_id,
        "rep": rep, "meta": task.meta(),
        "dialogue": d["dialogue"], "tutor_turns": d["tutor_turns"], "ended_by_tutor": d["ended_by_tutor"],
        "diagnosis": d["diagnosis"], "diagnosis_match": diag_match,
        "post_transfer": {"response": r, "grade": g},
        "status": status, "score": STATUS_SCORE[status], "pre_score": pre_score,
        "seconds": round(time.time() - t0, 2),
    }


def _pool(jobs, workers: int, label: str, store: RecordStore, verbose: bool = True) -> int:
    errors = 0
    done = 0
    total = len(jobs)
    if not total:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn): key for key, fn in jobs}
        for fut in as_completed(futs):
            done += 1
            try:
                store.put(fut.result())
            except Exception as e:  # 한 과제의 실패가 전체를 멈추지 않게 한다. 다시 돌리면 이어서 한다.
                errors += 1
                print(f"  [오류] {futs[fut]}: {e}")
                if verbose:
                    traceback.print_exc(limit=2)
            if done % 10 == 0 or done == total:
                print(f"  {label}: {done}/{total} (오류 {errors})", flush=True)
    return errors


def run_benchmark(tasks: list[Task], run_dir: Path, learner: Learner, grader: Grader, tutors: list[Tutor],
                  reps: int = 1, max_turns: int = 4, workers: int = 4, control: bool = True,
                  verbose: bool = False) -> RecordStore:
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RecordStore(run_dir)

    print(f"[1단계] 학습자 충실도: 과제 {len(tasks)} × 반복 {reps}")
    jobs = []
    for t in tasks:
        for rep in range(reps):
            k = learner_key(t, rep)
            if not store.has(k):
                jobs.append((k, (lambda t=t, rep=rep: run_learner_stage(t, rep, learner, grader, control))))
    _pool(jobs, workers, "학습자", store, verbose)

    for tutor in tutors:
        jobs = []
        n_valid = 0
        for t in tasks:
            for rep in range(reps):
                lr = store.get(learner_key(t, rep))
                if not lr or not lr.get("valid"):
                    continue
                n_valid += 1
                k = tutor_key(t, rep, tutor.name)
                if store.has(k):
                    continue
                first = lr["diag_belief"]["response"]
                pre = lr["pre_transfer"]["score"]
                jobs.append((k, (lambda t=t, rep=rep, first=first, pre=pre, tutor=tutor:
                                 run_tutor_stage(t, rep, learner, tutor, grader, first, max_turns, pre))))
        print(f"[2단계] 튜터 '{tutor.name}': 유효 과제 {n_valid}개, 새로 돌릴 것 {len(jobs)}개")
        _pool(jobs, workers, tutor.name, store, verbose)
    return store

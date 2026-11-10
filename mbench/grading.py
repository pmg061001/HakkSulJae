"""채점: 결정적 규칙 채점을 먼저 하고, 안 되면 LLM 채점자에게 넘긴다.

지식 카드 라벨: correct / misconception / other
행동 카드 라벨: desired / partial / habit / other
"""
from __future__ import annotations

from . import prompts as P
from .data import Item, Task, leading_choices, learner_choices, main_answer, norm_output
from .llm import Backend, call_json

RULE_FORMATS = ("출력 예측", "개념 선택")


def rule_grade(item: Item, response: dict) -> str | None:
    """확실할 때만 라벨을 돌려준다. 모르면 None."""
    ans = response.get("answer", "")
    if item.format == "개념 선택":
        picked = set(learner_choices(ans))
        right = set(leading_choices(item.answer))
        wrong = set(leading_choices(item.misconception_answer))
        if not picked or not right or not wrong or right == wrong:
            return None
        if picked == right:
            return "correct"
        if picked == wrong:
            return "misconception"
        return None  # 다른 보기: 다른 오개념일 수 있어 채점자가 본다
    if item.format == "출력 예측":
        got = norm_output(ans)
        if not got:
            return None
        corrects = {norm_output(main_answer(item.answer)), norm_output(item.answer)}
        if item.run and item.run.get("stdout") and item.run.get("exit", 0) == 0:
            corrects.add(norm_output(item.run["stdout"]))
        corrects.discard("")
        if got in corrects:
            return "correct"
        if got == norm_output(main_answer(item.misconception_answer)):
            return "misconception"
    return None


class Grader:
    def __init__(self, backend: Backend, use_rules: bool = True):
        self.backend = backend
        self.use_rules = use_rules

    def grade(self, task: Task, item: Item, response: dict, check_reason: bool = False) -> dict:
        """문항 하나를 채점한다.

        check_reason=True(튜터링 뒤 전이)이면 해소 판정에 필요한 '이유' 충족 여부(reason_ok)도 본다.
        """
        if task.is_knowledge and self.use_rules and item.format in RULE_FORMATS:
            label = rule_grade(item, response)
            if label is not None and (label != "correct" or not check_reason):
                return {"label": label, "reason_ok": label == "correct", "by": "rule", "rationale": ""}
            if label == "correct" and check_reason:
                r = self._judge(task, item, response, True)
                # 답 자체는 규칙이 확정했으므로 라벨은 고정하고 이유 판정만 받아들인다.
                return {"label": "correct", "reason_ok": bool(r.get("reason_ok")), "by": "rule+judge",
                        "rationale": r.get("rationale", "")}
        r = self._judge(task, item, response, check_reason)
        return {"label": r.get("label", "other"), "reason_ok": bool(r.get("reason_ok")), "by": "judge",
                "rationale": r.get("rationale", "")}

    def _judge(self, task: Task, item: Item, response: dict, check_reason: bool) -> dict:
        schema = P.JUDGE_KNOWLEDGE_SCHEMA if task.is_knowledge else P.JUDGE_BEHAVIOR_SCHEMA
        meta = {
            "role": "judge_item",
            "response": response.get("answer", ""),
            "knowledge": task.is_knowledge,
            "item": {"answer": item.answer, "misconception_answer": item.misconception_answer},
        }
        msg = P.judge_item_message(task, item, response, check_reason)
        return call_json(self.backend, P.JUDGE_SYSTEM, [{"role": "user", "content": msg}], schema, meta=meta,
                         max_tokens=2000)

    def grade_diagnosis(self, task: Task, diagnosis: str) -> str:
        if not (diagnosis or "").strip():
            return "none"
        r = call_json(
            self.backend, P.JUDGE_SYSTEM,
            [{"role": "user", "content": P.judge_diagnosis_message(task, diagnosis)}],
            P.JUDGE_DIAGNOSIS_SCHEMA, meta={"role": "judge_diagnosis", "diagnosis": diagnosis}, max_tokens=1000,
        )
        return r.get("match", "none")


# ---------- 라벨 → 지표 값 ----------

def is_misconception(task: Task, label: str) -> bool:
    return label == ("misconception" if task.is_knowledge else "habit")


def is_correct(task: Task, label: str) -> bool:
    return label == ("correct" if task.is_knowledge else "desired")


def resolution_status(task: Task, grade: dict) -> str:
    """카드의 판정 규칙(해소/부분 해소/미해소)을 적용한다.

    지식: 정답 + 이유 충족 → 해소, 정답만 → 부분 해소, 오개념 답 → 미해소(유지), 그 밖 오답 → 미해소(다른 오답)
    행동: desired → 해소, partial → 부분 해소, habit → 미해소(유지), other → 미해소(다른 오답)
    """
    label = grade["label"]
    if task.is_knowledge:
        if label == "correct":
            return "resolved" if grade.get("reason_ok") else "partial"
        return "persisted" if label == "misconception" else "other_wrong"
    return {"desired": "resolved", "partial": "partial", "habit": "persisted"}.get(label, "other_wrong")


STATUS_SCORE = {"resolved": 1.0, "partial": 0.5, "persisted": 0.0, "other_wrong": 0.0}
STATUS_KO = {"resolved": "해소", "partial": "부분 해소", "persisted": "미해소(오개념 유지)", "other_wrong": "미해소(다른 오답)"}

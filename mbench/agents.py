"""가상 학습자와 튜터.

튜터는 평가 대상이다. 튜터에게는 카드의 믿음·전이 문항·해소 기준을 주지 않고,
학생에게 낸 진단 문항, 그 정답, 학생의 답과 이유만 준다(TutorContext).
"""
from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass

from . import prompts as P
from .data import Item, Task
from .llm import Backend, call_json


def _item_meta(item: Item) -> dict:
    return {
        "format": item.format,
        "answer": item.answer,
        "misconception_answer": item.misconception_answer,
        "run": item.run,
    }


def _merge(messages: list[dict]) -> list[dict]:
    """같은 역할이 이어지면 합친다(API는 user/assistant 교대를 요구)."""
    out: list[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(dict(m))
    return out


def format_answer(resp: dict) -> str:
    return f"답: {resp.get('answer', '')}\n이유: {resp.get('reason', '')}"


# ---------------- 가상 학습자 ----------------


class Learner:
    def __init__(self, backend: Backend):
        self.backend = backend

    def answer(self, task: Task, item: Item, belief_active: bool, dialogue: list[dict] | None = None,
               tutor: str | None = None, rep: int = 0) -> dict:
        """문항에 답한다. dialogue가 있으면 튜터와의 대화 뒤에 푼다."""
        system = P.learner_system(task, belief_active)
        msgs = self._history(task, dialogue) if dialogue is not None else []
        msgs.append({"role": "user", "content": P.learner_item_message(item, task.language, dialogue is not None)})
        meta = {
            "role": "learner_answer",
            "task_id": task.task_id,
            "item": _item_meta(item),
            "belief_active": belief_active,
            "after_tutoring": dialogue is not None,
            "tutor": tutor,
            "rep": rep,
            "resolution": task.resolution,
        }
        r = call_json(self.backend, system, _merge(msgs), P.LEARNER_ANSWER_SCHEMA, meta=meta)
        return {"answer": str(r.get("answer", "")), "reason": str(r.get("reason", ""))}

    def chat(self, task: Task, dialogue: list[dict], tutor: str | None = None) -> str:
        system = P.learner_system(task, True)
        msgs = self._history(task, dialogue)
        return self.backend.complete(system, _merge(msgs), meta={"role": "learner_chat", "tutor": tutor},
                                     max_tokens=1500)

    @staticmethod
    def _history(task: Task, dialogue: list[dict]) -> list[dict]:
        """학습자 시점의 대화: 진단 문항과 자기 답 → 튜터(user)/학생(assistant)."""
        msgs: list[dict] = []
        for turn in dialogue:
            if turn["speaker"] == "system":  # 진단 문항과 학생 첫 답
                msgs.append({"role": "user", "content": P.learner_item_message(task.diagnostic, task.language, False)})
                msgs.append({"role": "assistant", "content": turn["text"]})
            elif turn["speaker"] == "tutor":
                msgs.append({"role": "user", "content": f"선생님: {turn['text']}"})
            else:
                msgs.append({"role": "assistant", "content": turn["text"]})
        return msgs


# ---------------- 튜터 ----------------


@dataclass
class TutorContext:
    """튜터가 볼 수 있는 정보 전부."""

    task_id: str
    language: str
    item_text: str
    answer: str
    student_answer: str
    student_reason: str
    tutor_tags: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class Tutor:
    """튜터 인터페이스. 직접 만든 튜터는 이 클래스를 상속해 turn()과 diagnose()를 구현한다."""

    name = "tutor"

    def turn(self, ctx: TutorContext, dialogue: list[dict]) -> str:
        """다음 튜터 발화. 대화를 끝내려면 끝에 '[대화 끝]'을 붙인다."""
        raise NotImplementedError

    def diagnose(self, ctx: TutorContext, dialogue: list[dict]) -> str:
        """대화 뒤 튜터가 추정한 학생의 오개념(1~2문장). 진단 정확도 지표에 쓴다."""
        return ""


class BaselineTutor(Tutor):
    """대조군: 개입 없이 다시 생각해 보라고만 한다(튜터 효과의 기준선)."""

    name = "baseline"

    def turn(self, ctx, dialogue):
        n = sum(1 for t in dialogue if t["speaker"] == "tutor")
        return "다시 한번 천천히 생각해 볼까요?" if n == 0 else f"좋아요. 스스로 정리해 보세요. {P.END_MARK}"


class LLMTutor(Tutor):
    """시스템 프롬프트(프로필)로 정의하는 LLM 튜터."""

    def __init__(self, backend: Backend, profile: str = "socratic", system_prompt: str | None = None,
                 name: str | None = None):
        self.backend = backend
        self.system = system_prompt or P.TUTOR_PROFILES[profile]
        self.name = name or profile

    def _messages(self, ctx: TutorContext, dialogue: list[dict]) -> list[dict]:
        msgs = [{
            "role": "user",
            "content": P.TUTOR_CONTEXT.format(
                lang=P.LANG_NAME.get(ctx.language, ctx.language),
                item=ctx.item_text,
                answer=ctx.answer,
                student_answer=ctx.student_answer,
                student_reason=ctx.student_reason,
            ),
        }]
        for turn in dialogue:
            if turn["speaker"] == "tutor":
                msgs.append({"role": "assistant", "content": turn["text"]})
            elif turn["speaker"] == "student":
                msgs.append({"role": "user", "content": f"학생: {turn['text']}"})
        return msgs

    def turn(self, ctx, dialogue):
        return self.backend.complete(self.system, _merge(self._messages(ctx, dialogue)),
                                     meta={"role": "tutor", "tutor": self.name}, max_tokens=2000)

    def diagnose(self, ctx, dialogue):
        msgs = self._messages(ctx, dialogue) + [{"role": "user", "content": P.TUTOR_DIAGNOSIS_REQUEST}]
        return self.backend.complete(self.system, _merge(msgs),
                                     meta={"role": "tutor_diagnosis", "tutor": self.name,
                                           "belief": getattr(ctx, "_belief", "")}, max_tokens=800)


def load_tutor(spec: str, backend: Backend) -> Tutor:
    """튜터 지정 문자열을 튜터 객체로 바꾼다.

    - 'baseline'               대조군
    - 'socratic' / 'direct'    내장 LLM 튜터 프로필
    - 'prompt:경로.txt'        파일의 시스템 프롬프트를 쓰는 LLM 튜터(이름은 파일 이름)
    - 'module.path:ClassName'  직접 만든 Tutor 하위 클래스. 생성자는 backend 하나를 받는다.
    """
    if spec == "baseline":
        return BaselineTutor()
    if spec in P.TUTOR_PROFILES:
        return LLMTutor(backend, profile=spec)
    if spec.startswith("prompt:"):
        from pathlib import Path

        p = Path(spec.split(":", 1)[1])
        return LLMTutor(backend, system_prompt=p.read_text(encoding="utf-8"), name=p.stem)
    if ":" in spec:
        mod, cls = spec.split(":", 1)
        return getattr(importlib.import_module(mod), cls)(backend)
    raise SystemExit(f"알 수 없는 튜터: {spec}")


def run_dialogue(task: Task, learner: Learner, tutor: Tutor, first_response: dict, max_turns: int) -> dict:
    """튜터와 학습자의 대화를 돌린다. 튜터가 먼저 말하고, 최대 max_turns번 말한다."""
    ctx = TutorContext(
        task_id=task.task_id,
        language=task.language,
        item_text=P.render_item(task.diagnostic, task.language),
        answer=task.diagnostic.answer,
        student_answer=first_response.get("answer", ""),
        student_reason=first_response.get("reason", ""),
        tutor_tags=task.tutor_tags,
    )
    object.__setattr__(ctx, "_belief", task.belief)  # 모의 백엔드 전용 힌트(튜터 구현은 쓰지 말 것)
    dialogue: list[dict] = [{"speaker": "system", "text": format_answer(first_response)}]
    ended_by_tutor = False
    for _ in range(max_turns):
        t = tutor.turn(ctx, dialogue).strip()
        done = P.END_MARK in t
        dialogue.append({"speaker": "tutor", "text": t.replace(P.END_MARK, "").strip()})
        if done:
            ended_by_tutor = True
            break
        dialogue.append({"speaker": "student", "text": learner.chat(task, dialogue, tutor=tutor.name).strip()})
    diagnosis = tutor.diagnose(ctx, dialogue)
    return {
        "dialogue": dialogue,
        "tutor_turns": sum(1 for t in dialogue if t["speaker"] == "tutor"),
        "ended_by_tutor": ended_by_tutor,
        "diagnosis": diagnosis,
    }


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)

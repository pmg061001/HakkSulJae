"""가상 학습자·튜터·채점자 프롬프트."""
from __future__ import annotations

from .data import Item, Task

LANG_FENCE = {"Python": "python", "C": "c", "공통": ""}
LANG_NAME = {"Python": "파이썬", "C": "C 언어", "공통": "프로그래밍(언어 무관)"}

# ---------------- 가상 학습자 ----------------

LEARNER_PERSONA = """너는 한국 고등학교 1학년 학생이다. 정보 수업에서 {lang}를 배우고 있다.
너는 AI가 아니라 이 학생으로서만 말한다. 말투는 고1 학생답게 짧고 자연스럽게 한다."""

LEARNER_BELIEF = """
[너의 생각]
{belief}
{remark}
이 생각은 너에게 당연한 사실이다. 이 생각이 쓰이는 문제에서는 이 생각을 따라 답하고 행동한다.
이 생각과 관계없는 부분은 고1 학생 수준에서 정확히 알고 있다.
이 생각을 먼저 꺼내 설명하거나 '오개념', '믿음' 같은 말을 쓰지 않는다. 누가 물으면 네 말로 이유를 말한다.

[선생님과 대화할 때]
- 선생님이 그냥 '틀렸다'고 하거나 정답만 알려 주면 쉽게 납득하지 않는다. 원래 생각이 왜 안 되는지 모르면 원래 생각을 유지한다.
- 선생님이 네 생각과 부딪치는 구체적인 예를 직접 따라가 보게 하거나, 실행 결과를 확인하게 하거나, 네 생각으로는 설명되지 않는 점을 스스로 알아차리게 하면 그때 생각을 고친다.
- 생각을 고쳤다면 이후 문제에서도 고친 생각대로 푼다. 반쯤만 이해했다면 반쯤만 고친다.
- 한 번에 1~4문장으로 답한다."""

LEARNER_CONTROL = """
너는 지금까지 배운 내용을 정확히 이해하고 있다. 문제를 차분히 따져 보고 답한다."""


def learner_system(task: Task, belief_active: bool) -> str:
    s = LEARNER_PERSONA.format(lang=LANG_NAME.get(task.language, task.language))
    if belief_active:
        remark = f"평소에 너는 이런 말을 한다: \"{task.typical_remark}\"" if task.typical_remark else ""
        s += LEARNER_BELIEF.format(belief=task.belief, remark=remark)
    else:
        s += LEARNER_CONTROL
    return s


def render_item(item: Item, language: str) -> str:
    """문항을 학생에게 보여 줄 글로 바꾼다. 정답·오개념 답·채점 기준은 넣지 않는다."""
    parts = [item.prompt.strip()]
    if item.code:
        parts.append(f"```{LANG_FENCE.get(language, '')}\n{item.code.rstrip()}\n```")
    if item.stdin:
        parts.append(f"(키보드 입력)\n```\n{item.stdin.rstrip()}\n```")
    if item.files:
        for name, content in item.files.items():
            parts.append(f"(파일 {name} 내용)\n```\n{str(content).rstrip()}\n```")
    return "\n\n".join(parts)


ANSWER_INSTRUCTIONS = {
    "출력 예측": "answer에는 화면에 출력될 내용을 그대로 쓴다(여러 줄이면 줄바꿈 포함). 오류가 난다고 생각하면 '오류'와 어떤 오류인지 쓴다.",
    "개념 선택": "answer에는 고른 번호(①, ② …)를 쓴다.",
    "오류 예측": "answer에는 오류가 나는지, 난다면 어디서 어떤 오류인지, 안 나면 출력이 무엇인지 쓴다.",
    "판단": "answer에는 네 판단(예: 항상 같은 값, 정해지지 않음 등)을 쓴다.",
}
DEFAULT_INSTRUCTION = "answer에는 네 답(코드, 단계, 선택 등)을 그대로 쓴다."

LEARNER_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["answer", "reason"],
    "additionalProperties": False,
}


def learner_item_message(item: Item, language: str, after_tutoring: bool) -> str:
    head = "선생님과 이야기를 마쳤어요. 이제 새 문제를 혼자 풀어 보세요.\n\n" if after_tutoring else ""
    inst = ANSWER_INSTRUCTIONS.get(item.format, DEFAULT_INSTRUCTION)
    return (
        f"{head}[문제]\n{render_item(item, language)}\n\n"
        f"JSON으로만 답한다. {inst} reason에는 왜 그렇게 답했는지 학생으로서 1~3문장으로 쓴다."
    )


# ---------------- 튜터 ----------------

TUTOR_PROFILES = {
    "socratic": """너는 고1 학생을 돕는 프로그래밍 튜터다. 학생이 방금 문제를 틀렸다.
목표: 학생의 잘못된 생각이 무엇인지 찾아내고, 학생 스스로 그 생각을 고치게 돕는다.
- 정답을 먼저 말하지 말고 질문, 코드 따라가기, 작은 반례로 학생이 스스로 알아차리게 한다.
- 학생의 말에서 어떤 생각을 하고 있는지 확인한 뒤 그 생각을 직접 겨냥한다.
- 한 번에 짧게(2~5문장) 말하고, 한 번에 질문은 하나만 한다.
- 학생이 생각을 고쳤다고 판단되면 핵심을 한 문장으로 정리하고 끝에 [대화 끝]을 붙인다.""",
    "direct": """너는 고1 학생을 돕는 프로그래밍 튜터다. 학생이 방금 문제를 틀렸다.
학생의 답에서 잘못된 생각을 짚고, 올바른 개념을 분명하게 설명한 뒤 간단한 예로 확인시킨다.
한 번에 3~6문장으로 말한다. 학생이 이해했다고 판단되면 끝에 [대화 끝]을 붙인다.""",
}

TUTOR_CONTEXT = """[수업 상황]
언어: {lang}
학생에게 낸 문제:
{item}

정답: {answer}
학생의 답: {student_answer}
학생이 쓴 이유: {student_reason}

이제 학생과 대화를 시작한다. 첫 말을 해라."""

TUTOR_DIAGNOSIS_REQUEST = """대화를 마쳤다. 학생에게는 보이지 않는 기록이다.
이 학생이 처음에 가지고 있던 잘못된 생각(오개념)을 학생의 말처럼 1~2문장으로 써라. 다른 말은 쓰지 마라."""

END_MARK = "[대화 끝]"


# ---------------- 채점자 ----------------

JUDGE_SYSTEM = """너는 프로그래밍 교육 연구의 채점자다. 주어진 채점 기준만으로 엄격하고 일관되게 판정한다.
학생 답이 정답과 겉모양(따옴표, 공백, 표현)만 다르고 뜻이 같으면 정답으로 본다."""

JUDGE_KNOWLEDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["correct", "misconception", "other"]},
        "reason_ok": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["label", "reason_ok", "rationale"],
    "additionalProperties": False,
}

JUDGE_BEHAVIOR_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["desired", "partial", "habit", "other"]},
        "reason_ok": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["label", "reason_ok", "rationale"],
    "additionalProperties": False,
}


def judge_item_message(task: Task, item: Item, response: dict, check_reason: bool) -> str:
    lines = [
        f"[문항 형식] {item.format}",
        f"[문항]\n{render_item(item, task.language)}",
        f"[정답]\n{item.answer}",
    ]
    if item.run and item.run.get("stdout") is not None and item.format in ("출력 예측", "오류 예측"):
        lines.append(f"[실제 실행 결과 stdout]\n{item.run.get('stdout')}")
    lines.append(f"[이 오개념을 가진 학생의 전형적인 답]\n{item.misconception_answer}")
    lines.append(f"[오개념(학생의 믿음/행동)]\n{task.belief}")
    if item.observable:
        lines.append(f"[관찰할 것]\n{item.observable}")
    if item.grading:
        lines.append(f"[채점 기준]\n{item.grading}")
    if check_reason:
        lines.append(f"[해소 판정 기준 — 이유에 들어가야 할 내용]\n{task.resolution}")
    lines.append(f"[학생 답]\n{response.get('answer', '')}")
    lines.append(f"[학생이 쓴 이유]\n{response.get('reason', '')}")
    if task.is_knowledge:
        lines.append(
            "판정: label은 correct(정답), misconception(위 오개념에서 나온 답), other(그 밖의 오답) 중 하나.\n"
            + (
                "reason_ok는 label이 correct이고 학생의 이유가 '해소 판정 기준'의 핵심 내용을 담았을 때만 true."
                if check_reason
                else "reason_ok는 label이 correct이면 true, 아니면 false."
            )
        )
    else:
        lines.append(
            "판정: label은 desired(바람직한 행동), partial(부분적으로 바람직함), habit(위 오개념/습관 행동), other(그 밖) 중 하나.\n"
            "'관찰할 것'과 '채점 기준'으로 판정하고, 출력이 맞는지는 기준이 요구할 때만 본다.\n"
            + (
                "reason_ok는 학생의 설명이 '해소 판정 기준'의 핵심을 담았을 때 true."
                if check_reason
                else "reason_ok는 label이 desired이면 true."
            )
        )
    lines.append("rationale에는 판정 근거를 한두 문장으로 쓴다.")
    return "\n\n".join(lines)


JUDGE_DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "match": {"type": "string", "enum": ["full", "partial", "none"]},
        "rationale": {"type": "string"},
    },
    "required": ["match", "rationale"],
    "additionalProperties": False,
}


def judge_diagnosis_message(task: Task, diagnosis: str) -> str:
    return (
        f"[실제 오개념]\n{task.belief}\n\n[튜터가 진단한 오개념]\n{diagnosis}\n\n"
        "튜터의 진단이 실제 오개념과 같은 생각을 가리키면 full, 관련은 있지만 핵심이 빠지거나 너무 일반적이면 partial, "
        "다른 생각이거나 진단이 없으면 none. rationale에 한 문장 근거."
    )

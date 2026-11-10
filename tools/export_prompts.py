"""PROMPTS.md를 mbench/prompts.py에서 다시 만든다. 실행: python tools/export_prompts.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from mbench import prompts as P  # noqa: E402
from mbench.data import build_tasks, load_cards  # noqa: E402


def fence(s, lang=""):
    return f"```{lang}\n{s.strip(chr(10)).rstrip()}\n```"


def j(o):
    return fence(json.dumps(o, ensure_ascii=False, indent=1), "json")


_, cards = load_cards()
t = next(x for x in build_tasks(cards) if x.task_id == "VAR-01/Python")

L = ["# AI 지침(프롬프트) 모음", "",
     "이 벤치마크에서 LLM에 주는 지침 전부다. `mbench/prompts.py`에서 그대로 뽑았다(`python tools/export_prompts.py`로 다시 만든다).",
     "`{중괄호}`는 실행할 때 카드 내용으로 채워진다. 예시는 카드 VAR-01(파이썬)로 채운 것이다.", "",
     "## 1. 가상 학습자", "", "모든 학습자에게 공통으로 주는 인물 설정:", "", fence(P.LEARNER_PERSONA), "",
     "### 1-1. 믿음을 넣은 학습자(오개념 학생)", "",
     "인물 설정 뒤에 붙인다. `{belief}`에 카드의 믿음 문장, `{remark}`에 '학생이 흔히 하는 말'이 들어간다.", "",
     fence(P.LEARNER_BELIEF), "",
     "### 1-2. 통제 학습자(믿음 없음)", "", fence(P.LEARNER_CONTROL), "",
     "### 1-3. 예시: VAR-01로 채운 믿음 학습자 시스템 프롬프트", "", fence(P.learner_system(t, True)), "",
     "### 1-4. 문항을 낼 때 붙이는 답 형식 지시", "",
     "문항 형식별로 `answer` 칸에 무엇을 쓸지 정한다. 응답은 아래 JSON 스키마를 따른다.", "",
     "| 문항 형식 | 지시 |", "|---|---|"]
L += [f"| {k} | {v} |" for k, v in P.ANSWER_INSTRUCTIONS.items()]
L += [f"| 그 밖 | {P.DEFAULT_INSTRUCTION} |", "", j(P.LEARNER_ANSWER_SCHEMA), "",
      "예시(VAR-01 진단 문항을 학습자에게 보낸 메시지):", "",
      fence(P.learner_item_message(t.diagnostic, t.language, False)), "",
      "## 2. 튜터(평가 대상)", "",
      "튜터에게는 진단 문항, 정답, 학생의 답과 이유만 준다. 카드의 믿음, 전이 문항, 해소 기준은 주지 않는다.", "",
      "### 2-1. 내장 튜터 프로필(시스템 프롬프트)", ""]
for k, v in P.TUTOR_PROFILES.items():
    L += [f"**{k}**", "", fence(v), ""]
L += ["**baseline**(대조군)은 LLM을 쓰지 않는다. 첫 발화는 \"다시 한번 천천히 생각해 볼까요?\", 다음 발화에서 대화를 끝낸다.", "",
      "`profiles/example_tutor.txt`는 직접 만든 프롬프트 튜터의 예시다(`--tutors prompt:profiles/example_tutor.txt`).", "",
      fence(Path("profiles/example_tutor.txt").read_text(encoding="utf-8")), "",
      "### 2-2. 대화 시작 때 튜터에게 주는 수업 상황", "", fence(P.TUTOR_CONTEXT), "",
      "### 2-3. 대화 뒤 오개념 진단 요청(진단 정확도 지표용)", "", fence(P.TUTOR_DIAGNOSIS_REQUEST), "",
      f"튜터가 발화 끝에 `{P.END_MARK}`를 붙이면 대화가 끝난다. 붙이지 않으면 최대 발화 수(기본 4)까지 간다.", "",
      "## 3. 채점자", "",
      "출력 예측과 개념 선택은 먼저 규칙으로 채점하고(실제 실행 결과, 보기 번호), 확정하지 못한 경우와 '이유' 판정만 채점자에게 넘긴다.", "",
      "### 3-1. 채점자 시스템 프롬프트", "", fence(P.JUDGE_SYSTEM), "",
      "### 3-2. 문항 채점 메시지", "",
      "`judge_item_message()`가 문항, 정답, 실제 실행 결과, 오개념 답, 믿음, 관찰할 것, 채점 기준, (튜터링 뒤에는) 해소 판정 기준, "
      "학생 답과 이유를 차례로 넣는다. 예시(VAR-01 전이 문항, 튜터링 뒤 정답을 낸 학생):", "",
      fence(P.judge_item_message(t, t.transfer, {"answer": "I live in Jeju",
                                                  "reason": "변수에 새 값을 넣으면 앞 값이 지워지고 마지막 값만 남아서요."}, True)), "",
      "지식 카드 응답 스키마:", "", j(P.JUDGE_KNOWLEDGE_SCHEMA), "",
      "행동 카드 응답 스키마:", "", j(P.JUDGE_BEHAVIOR_SCHEMA), "",
      "### 3-3. 튜터 진단 채점 메시지", "", fence(P.judge_diagnosis_message(t, "{튜터가 적은 진단}")), "",
      j(P.JUDGE_DIAGNOSIS_SCHEMA), ""]
Path("PROMPTS.md").write_text("\n".join(L), encoding="utf-8")
print("PROMPTS.md 작성")

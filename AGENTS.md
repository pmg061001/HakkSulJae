# AI 작업 지침 (AGENTS.md)

이 레포에서 일하는 AI 코딩 도우미(Claude Code, Codex, Cursor 등)가 따를 규칙이다. 사람 기여자도 같은 규칙을 따른다.

## 이 레포가 하는 일

오개념 카드(`data/cards_v2.json`)로 AI 튜터를 평가하는 벤치마크다. 가상 학습자(LLM)에게 카드의 믿음을 넣고,
튜터가 대화로 그 믿음을 해소하는지 전이 문항으로 판정한다. 지표 정의는 `README.md`, LLM에 주는 지침 전문은 `PROMPTS.md`에 있다.

## 꼭 지킬 것

1. **실제 모델 호출은 사람의 허락 없이 돌리지 않는다.** `python -m mbench run`에 mock이 아닌 모델(`claude-…`, `gemini:…`)을
   넣으면 비용이 든다. 파이썬 과제 283개 전체는 호출이 수천 번이다. 먼저 `--dry-run`으로 호출 수를 보여 주고 허락을 받는다.
   허락을 받아도 `--limit 20`처럼 작은 표본부터 돌린다.
2. **확인은 API 없이 한다.** 코드를 바꾼 뒤에는 시험을 돌린다:
   `python -m unittest discover -s tests -t .`
   파이프라인 전체는 모의 백엔드로 확인한다:
   `python -m mbench run --run-dir runs/mock --learner mock --tutor-model mock --judge mock --tutors baseline,socratic`
3. **보고서는 기록에서 만든다.** `python -m mbench report --run-dir <폴더> --html`은 모델을 부르지 않는다.
4. **튜터에게 정답을 흘리지 않는다.** 튜터는 `TutorContext`(진단 문항, 정답, 학생 답·이유)만 본다. 카드의 믿음, 전이 문항,
   해소 기준을 튜터 쪽 코드나 프롬프트에 넣지 않는다. `tests/test_mbench.py`의 누설 시험이 이를 확인한다.
5. **카드 데이터는 고치지 않는다.** `data/` 파일은 카드 팀의 산출물이다. 문제를 찾으면 `python -m mbench validate` 결과와 함께
   보고만 한다.
6. **프롬프트를 바꾸면 `PROMPTS.md`를 다시 만든다:** `python tools/export_prompts.py`
7. **API 키를 코드나 커밋에 넣지 않는다.** 키는 환경 변수(`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`)로만 읽는다.

## 구조

| 파일 | 역할 |
|---|---|
| `mbench/data.py` | 카드 로드, 과제(카드×언어) 만들기, 거르기, 답 정규화 |
| `mbench/prompts.py` | 가상 학습자·튜터·채점자 프롬프트(지침의 원본) |
| `mbench/agents.py` | 학습자, 튜터(baseline·LLM·사용자 정의), 대화 루프 |
| `mbench/grading.py` | 규칙 채점 + LLM 채점자, 해소 판정 |
| `mbench/runner.py` | 1단계(학습자 충실도)·2단계(튜터 효과) 실행, 이어 하기 |
| `mbench/metrics.py` | 지표, 부트스트랩 신뢰구간, 하위 집단별 집계 |
| `mbench/report.py`, `mbench/html_report.py` | 마크다운·HTML 보고서 |
| `mbench/llm.py` | Claude·Gemini 백엔드, 모의 백엔드 |
| `mbench/validate.py` | 카드 형식 점검, 코드 재실행 |

## 글쓰기

코드 주석, 문서, 보고서 문구는 한국어로 쓴다. 학습자·튜터 프롬프트는 고1 학생과 교사가 쓰는 말로 쓴다.

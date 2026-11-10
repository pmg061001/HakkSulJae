# 오개념 해소 벤치마크 (mbench)

> LLM 지침 전문은 [PROMPTS.md](PROMPTS.md), AI 코딩 도우미용 작업 규칙은 [AGENTS.md](AGENTS.md),
> 첫 시험 실행 결과는 [results/](results/2026-11-10_gemini-3.8-flash_20/)에 있다.

「1단계 오개념 카드 2판」(354장, 과제 544개)의 지표(진단 문항 · 전이 문항 · 해소 판정 기준)를 그대로 써서
**AI 튜터가 학생의 프로그래밍 오개념을 얼마나 해소하는지**를 재는 벤치마크다.
학생 역할은 카드의 믿음 문장을 넣은 **가상 학습자**(LLM)가 맡고, 튜터는 평가 대상이다.

```
카드(믿음·문항·해소 기준)
   │
   ├─ 1단계 학습자 충실도 ── 믿음 넣은 학습자 → 진단 문항 ──┐
   │                          믿음 없는 통제 학습자 → 진단 문항 ├─ 채점(규칙 → LLM 채점자)
   │                          믿음 넣은 학습자 → 전이 문항(사전) ┘
   │        └ 진단에서 오개념을 재현하고 사전 전이를 맞히지 않은 과제 = 유효 과제
   │
   └─ 2단계 튜터 효과 ───── 유효 과제마다: 튜터 ⇄ 학습자 대화(최대 N번)
                              → 학습자가 전이 문항에 답(답 + 이유) → 해소/부분 해소/미해소
                              → 튜터가 적은 오개념 진단 ↔ 실제 믿음 비교
```

## 빠른 시작

```bash
cd misconception-bench
pip install -r requirements.txt
```

API 없이 파이프라인만 확인(모의 백엔드, 점수에는 의미 없음):

```bash
python -m mbench run --run-dir runs/mock --learner mock --tutor-model mock --judge mock --tutors baseline,socratic,direct
```

실제 실행(ANTHROPIC_API_KEY 또는 `ant auth login` 필요). 먼저 작은 표본으로:

```bash
python -m mbench run --run-dir runs/pilot --limit 20 --sample-seed 1 --tutors baseline,socratic,direct --dry-run
```

```bash
python -m mbench run --run-dir runs/pilot --limit 20 --sample-seed 1 --tutors baseline,socratic,direct
```

Gemini로 돌리기(`GEMINI_API_KEY` 필요, `pip install google-genai`). 모델 이름 앞에 `gemini:`를 붙인다:

```bash
python -m mbench run --run-dir runs/gemini --limit 20 --sample-seed 1 --learner gemini:gemini-2.5-pro --tutor-model gemini:gemini-2.5-pro --judge gemini:gemini-2.5-pro --tutors baseline,socratic,direct
```

학습자·튜터·채점자에 서로 다른 회사의 모델을 섞어 쓸 수도 있다(예: 튜터는 Gemini, 채점자는 Claude).

결과는 `runs/pilot/report.md`(사람용), `summary.json`(프로그램용), `records.jsonl`(모든 대화·채점 기록)에 남는다.
중간에 끊겨도 같은 명령을 다시 돌리면 끝난 과제는 건너뛰고 이어서 한다.

```bash
python -m mbench show --run-dir runs/pilot --task VAR-01 --tutor socratic
```

```bash
python -m mbench report --run-dir runs/pilot
```

## 명령

| 명령 | 하는 일 |
|---|---|
| `stats` | 거른 과제 집합의 개요(유형·영역·형식, 규칙 채점 가능 문항 수) |
| `validate [--rerun]` | 카드 형식 점검. `--rerun`이면 코드 문항을 지금 환경에서 다시 실행해 카드의 `run.stdout`과 비교 |
| `run` | 벤치마크 실행 |
| `report` | 기록으로 리포트 다시 만들기(`--tutors`로 일부만, `--baseline`으로 NET 기준 바꾸기) |
| `show` | 과제 하나의 학습자 답, 대화, 채점 근거 보기 |

과제 거르기(모든 명령 공통, 쉼표로 여러 값): `--languages`(기본 `Python`, 전부는 `all`), `--types`, `--areas`,
`--levels`, `--tags`(튜터 태그), `--strengths`, `--ids`, `--experiment 실험`, `--limit`, `--sample-seed`.

기본 언어가 Python인 것은 "가상 학습자는 우선 고1 파이썬 학생으로 만든다(2026-11-07 결정)"를 따른 것이다.
퀴즈 튜터처럼 한 종류의 튜터를 평가할 때는 `--tags 퀴즈`처럼 그 튜터 태그가 붙은 카드만 쓴다.

`run`의 주요 설정: `--learner`, `--tutor-model`, `--judge`(기본 모두 `claude-opus-5-5`), `--effort`, `--reps`(과제당 반복),
`--max-turns`(튜터 최대 발화 수, 기본 4), `--workers`, `--no-control`(통제 학습자 생략), `--no-rules`(규칙 채점 끄기).

## 지표

### 1단계: 가상 학습자 충실도 — "이 벤치마크를 믿을 수 있는가"

| 지표 | 정의 | 바라는 값 |
|---|---|---|
| **MRR** 오개념 재현율 | 믿음을 넣은 학습자가 진단 문항에서 오개념 답(행동 카드는 습관 행동)을 낸 비율 | 높을수록 |
| **CCR** 통제 정답률 | 믿음 없는 학습자가 진단 문항을 맞힌 비율. 낮으면 문항이 어렵거나 애매하다는 뜻 | 높을수록 |
| **DI** 판별 지수 | MRR − 통제 학습자의 오개념 답 비율. 믿음 주입만의 효과 | 1에 가깝게 |
| **TC** 전이 일관성 | 진단에서 오개념을 낸 과제 중 튜터링 전 전이 문항에서도 오개념 답을 낸 비율. 진단과 전이가 같은 믿음을 묻는지 | 높을수록 |
| **VR** 유효 과제율 | 진단에서 오개념을 내고 사전 전이에서 정답을 내지 않은 비율. 2단계는 이 과제만 쓴다 | 높을수록 |

MRR·TC가 낮은 과제는 리포트 3절 "재현하지 못한 과제"에 나온다. 카드 팀이 믿음 문장이나 문항을 다시 볼 후보다.

### 2단계: 튜터 효과 — 유효 과제에서

카드의 판정 규칙을 그대로 쓴다.

| 상태 | 지식 카드 | 행동 카드(습관·실수·디버깅·환경·설계) | 점수 |
|---|---|---|---|
| 해소 | 전이 정답 + 이유에 '해소 판정' 내용이 들어감 | 전이 과제에서 '관찰할 것'의 바람직한 행동 | 1 |
| 부분 해소 | 전이 정답만 | 부분적으로 바람직한 행동 | 0.5 |
| 미해소(유지) | 전이에서도 오개념 답 | 습관 행동 그대로 | 0 |
| 미해소(다른 오답) | 오개념 답이 아닌 다른 오답 | 그 밖 | 0 |

| 지표 | 정의 |
|---|---|
| **RS** 해소 점수(주 지표) | 위 점수의 평균, 부트스트랩 95% 신뢰구간 |
| **RR / PR / KR / OR** | 해소 / 부분 해소 / 유지 / 다른 오답 비율 |
| **NET** 순효과 | 같은 과제·반복에서 RS(튜터) − RS(baseline). baseline은 "다시 생각해 볼까요?"만 하는 대조군이라 학습자가 혼자 고치는 몫을 뺀다 |
| **DA** 진단 정확도 | 대화 뒤 튜터가 적은 학생의 오개념이 실제 믿음과 같은지(full 1, partial 0.5, none 0) |
| **TURN / END** | 평균 튜터 발화 수 / 튜터가 스스로 대화를 끝낸 비율(효율) |

모든 튜터 지표는 영역, 유형, 학교급, 언어, 원인, 근거 강도, 튜터 태그별로도 나온다.

## 공정성을 위한 설계

- **튜터에게 주는 정보**: 진단 문항, 그 정답, 학생의 답과 이유뿐이다(`TutorContext`). 카드의 믿음 문장, 전이 문항,
  해소 기준은 주지 않는다. 시험(`test_tutor_sees_no_belief_or_transfer`)이 이를 확인한다.
- **전이 문항**은 진단과 겉모양이 다른 새 문항이라, 튜터가 진단 문항 답을 알려 주는 것만으로는 해소가 안 된다.
- **이유 채점**: 지식 카드의 '해소'는 정답에 더해 이유가 해소 판정 기준을 담아야 한다. 답만 외운 경우는 부분 해소다.
- **가상 학습자의 저항**: 학습자는 "틀렸다"는 말이나 정답 제시만으로는 생각을 바꾸지 않고, 자기 생각과 부딪치는
  구체적 예를 따라가 볼 때 고치도록 지시받는다(`prompts.py`의 `LEARNER_BELIEF`). 이 수준이 실제 학생과 맞는지는
  팀이 사람 학생 자료로 맞춰 볼 일이다(아래 한계).
- **채점**: 출력 예측은 카드의 실제 실행 결과(`run.stdout`)와, 개념 선택은 보기 번호로 먼저 규칙 채점한다.
  규칙으로 확정 못 하면(다른 오답, 서술형, 코드 작성·디버깅·설계·상황 판단) LLM 채점자가 카드의 '채점 기준',
  '관찰할 것', '해소 판정'을 근거로 판정한다. 규칙 채점은 카드의 정답을 오개념으로, 오개념 답을 정답으로 매기는
  일이 없음을 전체 카드로 시험한다.
- **분리**: 학습자·튜터·채점자 모델을 따로 정할 수 있다. 같은 모델이 튜터와 채점을 함께 하면 유리할 수 있으니,
  본 실험에서는 채점자를 다른 모델로 두거나 사람 채점 표본으로 채점자 일치도를 확인하길 권한다.

## 내 튜터 평가하기

프롬프트만 바꾼 LLM 튜터: 시스템 프롬프트를 파일에 쓰고 `--tutors prompt:my_tutor.txt`.
`profiles/example_tutor.txt`가 예시다. 대화를 끝낼 때 튜터가 `[대화 끝]`을 붙이면 된다.

코드로 만든 튜터: `mbench.agents.Tutor`를 상속해 `turn()`과 `diagnose()`를 구현하고 `--tutors 모듈:클래스`.

```python
from mbench.agents import Tutor

class MyTutor(Tutor):
    name = "my-tutor"
    def __init__(self, backend):          # --tutor-model로 만든 백엔드를 받는다
        self.backend = backend
    def turn(self, ctx, dialogue):        # ctx: TutorContext, dialogue: [{"speaker": "system|tutor|student", "text": ...}]
        return "이 줄이 끝나면 score에는 무엇이 들어 있을까요?"
    def diagnose(self, ctx, dialogue):    # 진단 정확도(DA)용, 학생의 오개념 1~2문장
        return "변수에 다시 대입하면 값이 더해진다고 생각한다."
```

## 데이터 점검 결과(2판, 2026-11-10 이 환경에서 실행)

`python -m mbench validate --languages all`의 형식 점검에서 26건이 나왔다. 대부분 '개념 선택' 형식인데 보기 번호
(①, (가))가 없는 문항(IO-01/C 전이, SEQ-24/C 전이, FUN-30/C 진단, MEM-03/C, MEM-08/C 전이, ALG-30, ALG-42 등)이고,
ENV-11(환경·도구)은 '관찰할 것'이 비어 있다. 이런 문항은 LLM 채점자가 맡으므로 실행에는 문제없다.

`--rerun`(Python 3.13, clang)에서 Python 465건이 카드 출력과 일치하고 17건이 달랐다. 다른 것은 주로 코드 작성 과제(코드가
정답이 아니라 주어진 일부)다. C는 270건 일치, 38건 다름(대부분 정의되지 않은 동작을 묻는 '판단' 문항), 113건은 함수
정의가 들어 있는 조각이라 자동으로 감싸 컴파일하지 못했다. 시간 초과 12건은 무한 반복을 묻는 문항이다.
판·컴파일러가 다르면 차이가 날 수 있으므로 이 목록은 확인할 후보일 뿐이다.

## 한계와 다음 일

1. **가상 학습자 타당도**: MRR·DI는 학습자가 믿음을 "재현"하는지만 본다. 실제 고1 학생의 답·대화와 비교하는
   보정(사람 학생 자료로 해소 난이도 맞추기)이 필요하다.
2. **채점자 신뢰도**: LLM 채점 문항은 사람 두 명이 표본(예: 50건)을 채점해 일치도(κ)를 보고하길 권한다.
   `records.jsonl`의 `grade.by`와 `rationale`로 표본을 뽑을 수 있다.
3. **실험 카드 12장 재선정**: 「팀이 판단할 것」 1번이 끝나면 카드의 `experiment` 칸을 고치고 `--experiment 실험`으로 돌린다.
4. **비용**: `--dry-run`이 최대 호출 수를 알려 준다. 파이썬 과제 283개 × 튜터 3(baseline 포함) × 반복 1이면
   대략 수천 번 호출한다. 먼저 `--limit 20`으로 시험한다.

## 파일

```
mbench/
  data.py      카드 로드, 과제(카드×언어) 만들기, 거르기, 답 정규화
  prompts.py   가상 학습자·튜터·채점자 프롬프트
  agents.py    Learner, Tutor(baseline·LLM·사용자 정의), 대화 루프
  grading.py   규칙 채점 + LLM 채점자, 해소 판정
  runner.py    1·2단계 실행, records.jsonl 저장·이어 하기, 병렬 실행
  metrics.py   지표 계산, 부트스트랩 신뢰구간, 하위 집단별 집계
  report.py    마크다운 리포트
  validate.py  카드 형식 점검, 코드 재실행
  llm.py       Claude API 백엔드(거절 시 서버 측 대체 모델 사용), 모의 백엔드
data/cards_v2.json, cards_v2.md   오개념 카드 2판
PROMPTS.md                        LLM에 주는 지침 전문(가상 학습자·튜터·채점자)
AGENTS.md, CLAUDE.md              이 레포에서 일하는 AI 코딩 도우미용 작업 지침
tools/export_prompts.py           PROMPTS.md 다시 만들기
results/                          시험 실행 결과(보고서 HTML, 대화 기록)
profiles/example_tutor.txt        프롬프트 튜터 예시
tests/test_mbench.py              API 없이 도는 시험
```

시험 실행:

```bash
python -m unittest discover -s tests -t .
```

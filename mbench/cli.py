"""명령줄: python -m mbench {stats,validate,run,report,show}"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .data import build_tasks, filter_tasks, load_cards


def _add_filters(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("과제 거르기(쉼표로 여러 값)")
    g.add_argument("--cards", help="카드 JSON 경로(기본: data/cards_v2.json)")
    g.add_argument("--languages", default="Python",
                   help="Python, C, 공통. 기본은 고1 파이썬 가상 학습자 결정(2026-11-07)에 맞춰 Python. 'all'이면 전부")
    g.add_argument("--types", help="지식, 습관, 실수, 환경·도구, 디버깅·테스트, 문제 해결·설계")
    g.add_argument("--areas", help="VAR, OPR, IO, CND, LOOP, SEQ, FUN, OOP, MEM, ALG, DES, DBG, ENV")
    g.add_argument("--levels", help="중, 고, 대1")
    g.add_argument("--tags", help="튜터 태그: 퀴즈, 코드 추적, 코드 작성, 디버깅, 설계·계획, 개념 대화")
    g.add_argument("--strengths", help="강, 중, 약")
    g.add_argument("--ids", help="카드 번호나 과제 번호(VAR-01 또는 VAR-01/Python)")
    g.add_argument("--experiment", help="실험 카드만: '실험' 또는 '예비'")
    g.add_argument("--limit", type=int, help="과제 수 제한")
    g.add_argument("--sample-seed", type=int, help="--limit을 무작위 표본으로(재현용 시드)")


def _tasks(a):
    _, cards = load_cards(a.cards)
    tasks = build_tasks(cards)
    langs = None if a.languages in (None, "all") else a.languages
    return filter_tasks(tasks, languages=langs, types=a.types, areas=a.areas, levels=a.levels, tags=a.tags,
                        strengths=a.strengths, ids=a.ids, experiment=a.experiment, limit=a.limit,
                        sample_seed=a.sample_seed)


def cmd_stats(a) -> None:
    tasks = _tasks(a)
    print(f"과제 {len(tasks)}개 (카드 {len({t.card_id for t in tasks})}장)")
    for name, fn in [("언어", lambda t: [t.language]), ("유형", lambda t: [t.type]), ("영역", lambda t: [t.area]),
                     ("학교급", lambda t: [t.level]), ("근거", lambda t: [t.strength]),
                     ("튜터 태그", lambda t: t.tutor_tags),
                     ("진단 형식", lambda t: [t.diagnostic.format]), ("전이 형식", lambda t: [t.transfer.format])]:
        c = Counter(x for t in tasks for x in fn(t))
        print(f"  {name}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    from .grading import RULE_FORMATS

    rule = sum(1 for t in tasks for it in (t.diagnostic, t.transfer) if t.is_knowledge and it.format in RULE_FORMATS)
    print(f"  규칙 채점 가능 문항: {rule}/{2 * len(tasks)} (나머지는 LLM 채점자)")


def cmd_validate(a) -> None:
    from .validate import rerun, schema_issues

    tasks = _tasks(a)
    issues = schema_issues(tasks)
    print(f"형식 점검: 과제 {len(tasks)}개, 문제 {len(issues)}건")
    for s in issues[:100]:
        print("  -", s)
    if a.rerun:
        r = rerun(tasks, timeout=a.timeout)
        print(f"\n코드 재실행 (Python {r['python']}, 컴파일러 {r['cc']}; 카드 기준 Python 3.11.1 / Apple clang 17)")
        for k, v in sorted(r["stats"].items()):
            print(f"  {k}: {v}")
        if r["diffs"]:
            print(f"\n차이 {len(r['diffs'])}건 (판·컴파일러 차이일 수 있음)")
            for s in r["diffs"][: a.show]:
                print("  -", s)


def cmd_run(a) -> None:
    from .agents import Learner, load_tutor
    from .grading import Grader
    from .llm import make_backend
    from .metrics import summarize
    from .runner import run_benchmark

    tasks = _tasks(a)
    run_dir = Path(a.run_dir)
    learner_be = make_backend(a.learner, a.effort, a.seed)
    tutor_be = make_backend(a.tutor_model, a.effort, a.seed) if a.tutor_model != a.learner else learner_be
    judge_be = make_backend(a.judge, a.judge_effort, a.seed) if a.judge != a.learner else learner_be
    tutors = [load_tutor(s.strip(), tutor_be) for s in a.tutors.split(",") if s.strip()]
    config = {
        "learner": a.learner, "tutor_model": a.tutor_model, "judge": a.judge, "effort": a.effort,
        "judge_effort": a.judge_effort, "tutors": ",".join(t.name for t in tutors), "reps": a.reps,
        "max_turns": a.max_turns, "control": not a.no_control, "rules": not a.no_rules, "n_tasks": len(tasks),
        "filters": {k: getattr(a, k) for k in ("languages", "types", "areas", "levels", "tags", "strengths",
                                                 "ids", "experiment", "limit", "sample_seed") if getattr(a, k)},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = run_dir / "config.json"
    if cfg_path.exists():
        old = json.loads(cfg_path.read_text(encoding="utf-8"))
        for k in ("learner", "judge", "max_turns", "effort"):
            if old.get(k) != config.get(k):
                print(f"[주의] 이전 실행과 설정이 다릅니다: {k} {old.get(k)!r} → {config.get(k)!r}. "
                      "같은 run 디렉터리의 기록이 섞입니다.", file=sys.stderr)
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")

    n_llm_tutors = sum(1 for t in tutors if t.name != "baseline")
    est = len(tasks) * a.reps * ((3 if not a.no_control else 2) * 2 + len(tutors) * (2 * a.max_turns + 3))
    print(f"과제 {len(tasks)}개, 반복 {a.reps}, 튜터 {[t.name for t in tutors]} (LLM 튜터 {n_llm_tutors})")
    print(f"최대 LLM 호출 수(대략, 규칙 채점·조기 종료 전): {est}")
    if a.dry_run:
        return
    store = run_benchmark(tasks, run_dir, Learner(learner_be), Grader(judge_be, use_rules=not a.no_rules), tutors,
                          reps=a.reps, max_turns=a.max_turns, workers=a.workers, control=not a.no_control,
                          verbose=a.verbose)
    usage = {b.name: {"calls": b.usage.calls, "input_tokens": b.usage.input_tokens,
                      "output_tokens": b.usage.output_tokens} for b in {learner_be, tutor_be, judge_be}}
    print("사용량:", json.dumps(usage, ensure_ascii=False))
    (run_dir / "usage.json").write_text(json.dumps(usage, ensure_ascii=False), encoding="utf-8")
    task_ids = {t.task_id for t in tasks}
    summary = summarize([r for r in store.all() if r["task_id"] in task_ids])
    _write_report(run_dir, summary, config)


def _write_report(run_dir: Path, summary: dict, config: dict | None) -> None:
    from .report import render_markdown

    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown(summary, config), encoding="utf-8")
    lm = summary["learner"]
    print(f"\n학습자: MRR {lm.get('MRR', 0) or 0:.3f}, 유효 과제 {lm.get('n_valid', 0)}")
    for name, t in summary["tutors"].items():
        m = t["overall"]
        net = f", NET {m['NET']:+.3f}" if "NET" in m else ""
        print(f"튜터 {name}: n {m['n']}, RS {m['RS']:.3f}, 해소 {m['RR']:.1%}, 유지 {m['KR']:.1%}, DA {m['DA']:.1%}{net}")
    print(f"리포트: {run_dir / 'report.md'}")


def cmd_report(a) -> None:
    from .metrics import summarize
    from .runner import RecordStore

    run_dir = Path(a.run_dir)
    store = RecordStore(run_dir)
    cfg = run_dir / "config.json"
    config = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else None
    recs = store.all()
    if a.tutors:
        keep = set(a.tutors.split(","))
        recs = [r for r in recs if r["kind"] == "learner" or r["tutor"] in keep]
    _write_report(run_dir, summarize(recs, baseline=a.baseline), config)
    if a.html:
        from .html_report import write_html

        print(f"HTML 보고서: {write_html(run_dir)}")


def cmd_show(a) -> None:
    from .runner import RecordStore

    store = RecordStore(Path(a.run_dir))
    for r in store.all():
        if a.task not in (r["task_id"], r["task_id"].split("/")[0]):
            continue
        if r["kind"] == "learner":
            print(f"=== [학습자] {r['task_id']} rep {r['rep']} 유효={r['valid']}")
            for part in ("diag_belief", "diag_control", "pre_transfer"):
                if part in r:
                    x = r[part]
                    print(f"  {part}: {x['grade']['label']} ({x['grade'].get('by')}) ← {x['response']['answer'][:120]!r}")
        elif not a.tutor or r["tutor"] == a.tutor:
            print(f"=== [튜터 {r['tutor']}] {r['task_id']} rep {r['rep']} → {r['status']} "
                  f"(진단 {r['diagnosis_match']})")
            for turn in r["dialogue"]:
                print(f"  [{turn['speaker']}] {turn['text']}")
            print(f"  [튜터 진단] {r['diagnosis']}")
            pt = r["post_transfer"]
            print(f"  [전이 답] {pt['response']} → {pt['grade']}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mbench", description="오개념 카드 기반 튜터·가상 학습자 벤치마크")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stats", help="거른 과제 집합 개요")
    _add_filters(s)
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("validate", help="카드 형식 점검(+ --rerun 코드 재실행)")
    _add_filters(s)
    s.add_argument("--rerun", action="store_true")
    s.add_argument("--timeout", type=float, default=5.0)
    s.add_argument("--show", type=int, default=40)
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="벤치마크 실행")
    _add_filters(s)
    s.add_argument("--run-dir", required=True)
    s.add_argument("--learner", default="claude-opus-5-5", help="가상 학습자 모델. 'mock'은 API 없이 시험")
    s.add_argument("--tutor-model", default="claude-opus-5-5", help="내장 LLM 튜터가 쓸 모델")
    s.add_argument("--judge", default="claude-opus-5-5", help="채점자 모델")
    s.add_argument("--tutors", default="baseline,socratic",
                   help="baseline, socratic, direct, prompt:파일.txt, 모듈:클래스 (쉼표로 여러 개)")
    s.add_argument("--effort", default="medium", help="학습자·튜터 effort (low|medium|high|xhigh|max)")
    s.add_argument("--judge-effort", default="medium")
    s.add_argument("--reps", type=int, default=1, help="과제당 반복 수(학습자 응답의 변동 측정)")
    s.add_argument("--max-turns", type=int, default=4, help="튜터 최대 발화 수")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--no-control", action="store_true", help="통제 학습자 생략(비용 절감, CCR·DI 없음)")
    s.add_argument("--no-rules", action="store_true", help="규칙 채점 끄고 모두 LLM 채점")
    s.add_argument("--dry-run", action="store_true", help="호출 수만 추정")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("report", help="기록으로 리포트 다시 만들기")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--tutors", help="리포트에 넣을 튜터만")
    s.add_argument("--baseline", default="baseline", help="순효과(NET) 기준 튜터 이름")
    s.add_argument("--html", action="store_true", help="report.html도 만든다(LLM 호출 없음)")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("show", help="과제 하나의 대화·채점 보기")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--task", required=True, help="VAR-01 또는 VAR-01/Python")
    s.add_argument("--tutor")
    s.set_defaults(fn=cmd_show)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

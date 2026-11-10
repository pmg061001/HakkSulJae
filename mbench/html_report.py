"""저장된 실행 기록(records.jsonl, summary.json, config.json)으로 읽기 쉬운 HTML 보고서를 만든다.

LLM을 부르지 않는다. 사용: python -m mbench report --run-dir 경로 --html
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .data import load_cards
from .grading import STATUS_KO
from .metrics import summarize

STATUS_ORDER = ["resolved", "partial", "persisted", "other_wrong"]
STATUS_SHORT = {"resolved": "해소", "partial": "부분", "persisted": "유지", "other_wrong": "다른 오답"}
DIAG_KO = {"full": "일치", "partial": "부분 일치", "none": "불일치"}
LABEL_KO = {"correct": "정답", "misconception": "오개념 답", "other": "다른 오답", "desired": "바람직한 행동",
            "partial": "부분적", "habit": "습관 행동"}
SPEAKER_KO = {"system": "학생 첫 답", "tutor": "튜터", "student": "학생"}
TUTOR_DESC = {
    "baseline": "대조군. \"다시 생각해 볼까요?\"만 말한다",
    "socratic": "질문과 반례로 학생이 스스로 알아차리게 한다",
    "direct": "잘못된 생각을 짚고 개념을 바로 설명한다",
}


def e(x) -> str:
    return escape("" if x is None else str(x))


def pct(x, d=0) -> str:
    return "–" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=2) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def _ci(c, f=num) -> str:
    if not c or c[0] is None:
        return ""
    return f'<span class="ci">{f(c[0])}–{f(c[1])}</span>'


CSS = """
/* 레이아웃: 한 열 보고서. 위에서 아래로 요약 → 튜터 비교 → 학습자 점검 → 과제별 → 해석 → 용어 */
:root {
  --bg: #f6f7f5; --surface: #ffffff; --fg: #1d2421; --muted: #5c6863; --line: #dde3df;
  --accent: #2f6b5a; --accent-soft: #e3efe9;
  --ok: #2e8b57; --part: #c98a12; --keep: #c2453b; --other: #8a94a0;
  --ok-soft: #e2f3e8; --part-soft: #fbf0d9; --keep-soft: #f9e2df; --other-soft: #eceff2;
  --f-head: "IBM Plex Sans KR", "Noto Sans KR", system-ui, sans-serif;
  --f-body: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121715; --surface: #1a211e; --fg: #e4ebe7; --muted: #9aa8a1; --line: #2c3632;
  --accent: #6fbfa3; --accent-soft: #1f3a31;
  --ok: #5cc48a; --part: #e0ad4a; --keep: #ec7a6f; --other: #9aa5b1;
  --ok-soft: #1c3527; --part-soft: #3a2f17; --keep-soft: #3d221f; --other-soft: #262d33; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121715; --surface: #1a211e; --fg: #e4ebe7; --muted: #9aa8a1; --line: #2c3632;
  --accent: #6fbfa3; --accent-soft: #1f3a31;
  --ok: #5cc48a; --part: #e0ad4a; --keep: #ec7a6f; --other: #9aa5b1;
  --ok-soft: #1c3527; --part-soft: #3a2f17; --keep-soft: #3d221f; --other-soft: #262d33; color-scheme: dark }
* { box-sizing: border-box }
body { background: var(--bg); color: var(--fg); font-family: var(--f-body); font-size: 15px; line-height: 1.65;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.wrap { max-width: 1040px; margin: 0 auto; padding-block: 40px 80px; display: flex; flex-direction: column; gap: 48px }
h1, h2, h3 { font-family: var(--f-head); text-wrap: balance; margin: 0; line-height: 1.3 }
h1 { font-size: 2rem; font-weight: 700 }
h2 { font-size: 1.35rem; font-weight: 600; padding-bottom: 8px; border-bottom: 1px solid var(--line) }
h3 { font-size: 1.05rem; font-weight: 600 }
p { margin: 0; max-width: 68ch }
section { display: flex; flex-direction: column; gap: 18px; min-width: 0 }
.eyebrow { font-size: .78rem; letter-spacing: .08em; color: var(--accent); font-weight: 600 }
.meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font-size: .88rem }
.meta b { color: var(--fg); font-weight: 500 }
.lead { font-size: 1.05rem }
.num { font-family: var(--f-mono); font-variant-numeric: tabular-nums }
.ci { font-family: var(--f-mono); font-size: .78rem; color: var(--muted); margin-left: 6px; white-space: nowrap }
.callout { background: var(--accent-soft); border-radius: 10px; padding: 16px 18px; display: flex; flex-direction: column; gap: 8px }
.callout ul { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px }

/* 튜터 비교 */
.tutors { display: flex; flex-direction: column; gap: 14px }
.trow { display: grid; grid-template-columns: 170px 1fr 92px; gap: 6px 16px; align-items: center }
.tname { font-family: var(--f-head); font-weight: 600 }
.tname small { display: block; font-family: var(--f-body); font-weight: 400; color: var(--muted); font-size: .78rem; line-height: 1.4 }
.bar { display: flex; height: 30px; border-radius: 6px; overflow: hidden; background: var(--other-soft) }
.bar span { display: flex; align-items: center; justify-content: center; font-size: .78rem; color: #fff; font-weight: 600; min-width: 0; overflow: hidden; white-space: nowrap }
.s-resolved { background: var(--ok) } .s-partial { background: var(--part) } .s-persisted { background: var(--keep) } .s-other_wrong { background: var(--other) }
.rs { text-align: right; font-family: var(--f-mono); font-size: 1.25rem; font-weight: 600 }
.rs small { display: block; font-size: .7rem; color: var(--muted); font-weight: 400 }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: .82rem; color: var(--muted) }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px }

.tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; background: var(--surface) }
table { border-collapse: collapse; width: 100%; font-size: .88rem }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top }
th { font-weight: 600; color: var(--muted); font-size: .8rem; white-space: nowrap; background: var(--bg) }
tr:last-child td { border-bottom: 0 }
td.r, th.r { text-align: right }

/* 학습자 지표 */
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px }
.metric { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px }
.metric .k { font-size: .8rem; color: var(--muted) }
.metric .v { font-family: var(--f-mono); font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums }
.metric .d { font-size: .8rem; color: var(--muted); line-height: 1.5 }

/* 과제별 */
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .76rem; font-weight: 600; white-space: nowrap }
.c-resolved { background: var(--ok-soft); color: var(--ok) } .c-partial { background: var(--part-soft); color: var(--part) }
.c-persisted { background: var(--keep-soft); color: var(--keep) } .c-other_wrong { background: var(--other-soft); color: var(--other) }
.c-yes { background: var(--ok-soft); color: var(--ok) } .c-no { background: var(--keep-soft); color: var(--keep) }
.filters { display: flex; flex-wrap: wrap; gap: 8px }
.filters button { font: inherit; font-size: .85rem; border: 1px solid var(--line); background: var(--surface); color: var(--fg);
  border-radius: 999px; padding: 4px 14px; cursor: pointer }
.filters button[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--surface) }
.filters button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
.tasks { display: flex; flex-direction: column; gap: 8px }
details.task { background: var(--surface); border: 1px solid var(--line); border-radius: 10px }
details.task > summary { list-style: none; cursor: pointer; padding: 12px 16px; display: grid;
  grid-template-columns: 1fr auto; gap: 6px 16px; align-items: center }
details.task > summary::-webkit-details-marker { display: none }
.tt { min-width: 0 }
.tt .id { font-family: var(--f-mono); font-size: .8rem; color: var(--accent); font-weight: 600; margin-right: 8px }
.tt .ti { font-weight: 500 }
.tt .sub { display: block; font-size: .78rem; color: var(--muted) }
.chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end }
.chips .pair { white-space: nowrap; display: inline-flex; align-items: center; gap: 4px }
.chips .lab { font-size: .7rem; color: var(--muted); margin-right: 2px }
.tbody { border-top: 1px solid var(--line); padding: 16px; display: flex; flex-direction: column; gap: 18px }
.belief { border-left: 3px solid var(--accent); padding: 4px 0 4px 12px; color: var(--fg); font-size: .92rem }
.belief b { display: block; font-size: .75rem; color: var(--muted); font-weight: 600 }
.panes { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px }
.pane { border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; min-width: 0 }
.pane h4 { margin: 0; font-family: var(--f-head); font-size: .95rem; display: flex; justify-content: space-between; gap: 8px; align-items: center }
.turn { font-size: .86rem; display: flex; flex-direction: column; gap: 2px }
.turn b { font-size: .72rem; color: var(--muted); font-weight: 600 }
.turn.tutor b { color: var(--accent) }
.turn div { white-space: pre-wrap; overflow-wrap: anywhere }
.box { background: var(--bg); border-radius: 6px; padding: 10px 12px; font-size: .84rem; display: flex; flex-direction: column; gap: 4px }
.box b { font-size: .72rem; color: var(--muted) }
pre { margin: 0; font-family: var(--f-mono); font-size: .8rem; white-space: pre-wrap; overflow-wrap: anywhere }
.learner-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px }
dl.gloss { display: grid; grid-template-columns: max-content 1fr; gap: 8px 18px; margin: 0; font-size: .9rem }
dl.gloss dt { font-family: var(--f-mono); font-weight: 600; color: var(--accent) }
dl.gloss dd { margin: 0; color: var(--fg) }
footer { color: var(--muted); font-size: .8rem }
@media (max-width: 640px) {
  .trow { grid-template-columns: 1fr 80px } .trow .bar { grid-column: 1 / -1; grid-row: 2 }
  details.task > summary { grid-template-columns: 1fr } .chips { justify-content: flex-start }
  dl.gloss { grid-template-columns: 1fr } h1 { font-size: 1.6rem }
}
@media (prefers-reduced-motion: no-preference) { details.task > summary { transition: background .15s } }
details.task > summary:hover { background: var(--bg) }
"""

JS = """
(function(){
  var btns = document.querySelectorAll('.filters button');
  var rows = document.querySelectorAll('details.task');
  btns.forEach(function(b){ b.addEventListener('click', function(){
    btns.forEach(function(x){ x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
    var f = b.dataset.f;
    rows.forEach(function(r){
      r.hidden = !(f === 'all' || (f === 'unresolved' && r.dataset.unresolved === '1') || (f === 'knowledge' && r.dataset.k === '1') || (f === 'behavior' && r.dataset.k === '0'));
    });
  }); });
})();
"""


def _bar(m: dict) -> str:
    parts = []
    for s, key in (("resolved", "RR"), ("partial", "PR"), ("persisted", "KR"), ("other_wrong", "OR")):
        v = m.get(key) or 0
        if v > 0:
            label = pct(v) if v >= 0.09 else ""
            parts.append(f'<span class="s-{s}" style="width:{v * 100:.2f}%" title="{STATUS_KO[s]} {pct(v)}">{label}</span>')
    return f'<div class="bar" role="img" aria-label="해소 {pct(m.get("RR"))}, 부분 {pct(m.get("PR"))}, 유지 {pct(m.get("KR"))}, 다른 오답 {pct(m.get("OR"))}">{"".join(parts)}</div>'


def _resp(resp: dict, grade: dict | None) -> str:
    g = ""
    if grade:
        g = (f'<div><b>판정</b> {e(LABEL_KO.get(grade.get("label"), grade.get("label")))}'
             f'{" · 이유 충족" if grade.get("reason_ok") and grade.get("label") == "correct" else ""}'
             f' <span class="ci">{e(grade.get("by"))}</span></div>')
        if grade.get("rationale"):
            g += f'<div style="color:var(--muted)">{e(grade["rationale"])}</div>'
    return (f'<div class="box"><b>답</b><pre>{e(resp.get("answer"))}</pre>'
            f'<b>이유</b><div>{e(resp.get("reason"))}</div>{g}</div>')


def render_html(run_dir: Path, cards_path: str | None = None, title: str = "오개념 해소 벤치마크 시험 실행") -> str:
    run_dir = Path(run_dir)
    recs = [json.loads(l) for l in open(run_dir / "records.jsonl", encoding="utf-8") if l.strip()]
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8")) if (run_dir / "config.json").exists() else {}
    usage = json.loads((run_dir / "usage.json").read_text(encoding="utf-8")) if (run_dir / "usage.json").exists() else {}
    s = summarize(recs)
    _, cards = load_cards(cards_path)
    card = {c["id"]: c for c in cards}

    learners = {r["task_id"]: r for r in recs if r["kind"] == "learner" and r["rep"] == 0}
    tutors_present = [t for t in ("baseline", "socratic", "direct") if t in s["tutors"]] + \
        [t for t in s["tutors"] if t not in ("baseline", "socratic", "direct")]
    by_task: dict = {}
    for r in recs:
        if r["kind"] == "tutor" and r["rep"] == 0:
            by_task.setdefault(r["task_id"], {})[r["tutor"]] = r
    llm_tutors = [t for t in tutors_present if t != "baseline"]
    lm = s["learner"]
    models = sorted({config.get("learner"), config.get("tutor_model"), config.get("judge")} - {None})
    model_txt = ", ".join(m.split(":", 1)[-1] for m in models)

    # ---------- 머리 ----------
    H: list[str] = []
    calls = sum(v.get("calls", 0) for v in usage.values() if isinstance(v, dict))
    tin = sum(v.get("input_tokens", 0) for v in usage.values() if isinstance(v, dict))
    tout = sum(v.get("output_tokens", 0) for v in usage.values() if isinstance(v, dict))
    meta = [f"<span>모델 <b>{e(model_txt)}</b> (학습자·튜터·채점자)</span>",
            f"<span>과제 <b>{lm.get('n', 0)}개</b> · {e(config.get('filters', {}).get('languages', '전체'))}</span>",
            f"<span>튜터 <b>{e(', '.join(tutors_present))}</b></span>",
            f"<span>최대 튜터 발화 <b>{e(config.get('max_turns'))}회</b></span>"]
    if calls:
        meta.append(f"<span>호출 <b class=\"num\">{calls:,}</b>회 · 토큰 <b class=\"num\">{tin:,}</b> 입력 / <b class=\"num\">{tout:,}</b> 출력</span>")
    H.append(f'<header style="display:flex;flex-direction:column;gap:12px"><div class="eyebrow">1단계 오개념 카드 2판 기반 · 시험 실행</div>'
             f'<h1>{e(title)}</h1><div class="meta">{"".join(meta)}</div></header>')

    # ---------- 요약 ----------
    best = max(llm_tutors, key=lambda t: s["tutors"][t]["overall"]["RS"]) if llm_tutors else None
    base = s["tutors"].get("baseline", {}).get("overall")
    bullets = [f"가상 학습자는 과제 {lm.get('n')}개 중 {round((lm.get('MRR') or 0) * lm.get('n', 0))}개에서 카드의 오개념을 재현했다(오개념 재현율 {pct(lm.get('MRR'))})."]
    if base:
        bullets.append(f"튜터 없이 다시 생각만 하게 한 대조군은 해소 점수 {num(base['RS'], 3)}로, 학습자가 혼자서는 거의 고치지 않았다.")
    for t in llm_tutors:
        m = s["tutors"][t]["overall"]
        bullets.append(f"{t} 튜터: 해소 점수 {num(m['RS'], 3)}, 해소 {pct(m['RR'])}, 오개념 유지 {pct(m['KR'])}, 대조군 대비 +{num(m.get('NET'), 3)}.")
    if len(llm_tutors) >= 2:
        a, b = (s["tutors"][t]["overall"] for t in llm_tutors[:2])
        overlap = a["RS_ci"][0] is not None and b["RS_ci"][0] is not None and not (a["RS_ci"][1] < b["RS_ci"][0] or b["RS_ci"][1] < a["RS_ci"][0])
        if overlap:
            bullets.append("두 LLM 튜터의 신뢰구간이 겹친다. 이 표본 크기로는 어느 쪽이 낫다고 말할 수 없다.")
    H.append('<section><h2>요약</h2><div class="callout"><ul>' + "".join(f"<li>{e(x)}</li>" for x in bullets) + "</ul></div></section>")

    # ---------- 튜터 비교 ----------
    rows = []
    for t in tutors_present:
        m = s["tutors"][t]["overall"]
        rows.append(f'<div class="trow"><div class="tname">{e(t)}<small>{e(TUTOR_DESC.get(t, "사용자 튜터"))}</small></div>'
                    f'{_bar(m)}<div class="rs">{num(m["RS"], 2)}<small>해소 점수</small></div></div>')
    legend = "".join(f'<span><i class="s-{k}"></i>{STATUS_KO[k]}</span>' for k in STATUS_ORDER)
    trs = []
    for t in tutors_present:
        m = s["tutors"][t]["overall"]
        net = f'{m["NET"]:+.3f}{_ci(m.get("NET_ci"), lambda v: f"{v:+.2f}")}' if "NET" in m else "기준"
        trs.append(
            f'<tr><td><b>{e(t)}</b></td><td class="r num">{m["n"]}</td><td class="r num">{num(m["RS"], 3)}{_ci(m.get("RS_ci"))}</td>'
            f'<td class="r num">{net}</td><td class="r num">{pct(m["RR"])}</td><td class="r num">{pct(m["PR"])}</td>'
            f'<td class="r num">{pct(m["KR"])}</td><td class="r num">{pct(m["OR"])}</td>'
            f'<td class="r num">{pct(m["DA"]) if t != "baseline" else "–"}</td><td class="r num">{num(m["TURN"], 1)}</td></tr>')
    H.append(
        '<section><h2>튜터 비교</h2><p>유효 과제마다 튜터와 학습자가 대화한 뒤, 학습자가 처음 보는 전이 문항에 답했다. '
        '막대는 그 결과의 비율이고, 오른쪽 숫자는 해소 1 · 부분 0.5 · 미해소 0의 평균이다.</p>'
        f'<div class="tutors">{"".join(rows)}</div><div class="legend">{legend}</div>'
        '<div class="tablewrap"><table><thead><tr><th>튜터</th><th class="r">n</th><th class="r">해소 점수 (95% CI)</th>'
        '<th class="r">대조군 대비</th><th class="r">해소</th><th class="r">부분</th><th class="r">유지</th><th class="r">다른 오답</th>'
        '<th class="r">진단 정확도</th><th class="r">평균 발화</th></tr></thead><tbody>'
        + "".join(trs) + "</tbody></table></div></section>")

    # 유형별
    if llm_tutors:
        types = sorted({r["meta"]["type"] for r in recs if r["kind"] == "learner"},
                       key=lambda x: (x != "지식", x))
        th = "".join(f'<th class="r">{e(t)} 해소 점수</th>' for t in llm_tutors)
        trs = []
        for ty in types:
            n = sum(1 for r in learners.values() if r["meta"]["type"] == ty)
            cells = "".join(f'<td class="r num">{num(s["tutors"][t]["by"]["type"].get(ty, {}).get("RS"), 2)}</td>' for t in llm_tutors)
            trs.append(f"<tr><td>{e(ty)}</td><td class=\"r num\">{n}</td>{cells}</tr>")
        H.append('<section><h3>카드 유형별</h3><p>칸마다 과제가 1~4개뿐이라 경향만 보는 숫자다.</p>'
                 f'<div class="tablewrap"><table><thead><tr><th>유형</th><th class="r">과제</th>{th}</tr></thead><tbody>'
                 + "".join(trs) + "</tbody></table></div></section>")

    # ---------- 학습자 점검 ----------
    mets = [
        ("오개념 재현율 MRR", pct(lm.get("MRR")), "믿음을 넣은 학습자가 진단 문항에서 오개념 답을 낸 비율"),
        ("통제 정답률 CCR", pct(lm.get("CCR")), "믿음을 넣지 않은 학습자가 진단 문항을 맞힌 비율"),
        ("판별 지수 DI", num(lm.get("DI"), 2), "믿음을 넣어서 생긴 차이. 1에 가까울수록 좋다"),
        ("전이 일관성 TC", pct(lm.get("TC")), "튜터링 전 전이 문항에서도 같은 오개념 답을 낸 비율"),
        ("유효 과제", f'{lm.get("n_valid")}/{lm.get("n")}', "2단계(튜터 평가)에 쓴 과제 수"),
    ]
    tiles = "".join(f'<div class="metric"><div class="k">{e(k)}</div><div class="v">{e(v)}</div><div class="d">{e(d)}</div></div>'
                    for k, v, d in mets)
    ctrl_wrong = [r for r in learners.values() if "diag_control" in r and not r["diag_control"]["correct"]]
    note = ""
    if ctrl_wrong:
        items = "".join(
            f'<li><b class="num">{e(r["task_id"].split("/")[0])}</b> ({e(r["meta"]["type"])}) — {e(r["diag_control"]["grade"].get("rationale", ""))}</li>'
            for r in ctrl_wrong)
        note = (f'<div class="callout"><b>통제 학습자가 놓친 과제 {len(ctrl_wrong)}개</b>'
                '<p>믿음을 넣지 않았는데도 바람직한 행동을 보이지 않았다. 행동 카드는 \'print로 확인하기\', \'주석 달기\' 같은 과정을 요구하는데, '
                'LLM은 이런 과정을 저절로 보이지 않는다. 행동 카드의 통제 정답률은 따로 봐야 한다.</p>'
                f'<ul>{items}</ul></div>')
    H.append('<section><h2>가상 학습자 점검</h2><p>튜터 점수를 믿으려면, 먼저 가상 학습자가 카드의 오개념을 제대로 재현해야 한다.</p>'
             f'<div class="metrics">{tiles}</div>{note}</section>')

    # ---------- 과제별 ----------
    order = sorted(learners, key=lambda tid: (-sum(1 for t in llm_tutors if by_task.get(tid, {}).get(t, {}).get("status") != "resolved"), tid))
    items = []
    n_unres = 0
    for tid in order:
        lr = learners[tid]
        cid = tid.split("/")[0]
        c = card.get(cid, {})
        trs = by_task.get(tid, {})
        unresolved = any(trs.get(t, {}).get("status") not in (None, "resolved") for t in llm_tutors)
        n_unres += unresolved
        chips = []
        ok = lr["diag_belief"]["misconception"]
        chips.append(f'<span class="pair"><span class="lab">재현</span><span class="chip {"c-yes" if ok else "c-no"}">{"예" if ok else "아니오"}</span></span>')
        for t in tutors_present:
            st = trs.get(t, {}).get("status")
            if st:
                chips.append(f'<span class="pair"><span class="lab">{e(t)}</span><span class="chip c-{st}">{STATUS_SHORT[st]}</span></span>')
        sub = f'{e(lr["meta"]["type"])} · {e(lr["meta"]["area"])} · {e(lr["meta"]["level"])} · 원인: {e(lr["meta"]["cause"])}'
        summary = (f'<summary><div class="tt"><span class="id">{e(cid)}</span><span class="ti">{e(c.get("title", ""))}</span>'
                   f'<span class="sub">{sub}</span></div><div class="chips">{"".join(chips)}</div></summary>')
        body = [f'<div class="belief"><b>카드의 믿음(학습자에게 넣은 문장)</b>{e(c.get("belief", ""))}</div>']
        lg = ['<div class="learner-grid">']
        for part, name in (("diag_belief", "진단 · 믿음 넣은 학습자"), ("diag_control", "진단 · 통제 학습자"),
                           ("pre_transfer", "전이(튜터링 전) · 믿음 넣은 학습자")):
            if part in lr:
                lg.append(f'<div class="pane"><h4>{e(name)}</h4>{_resp(lr[part]["response"], lr[part]["grade"])}</div>')
        lg.append("</div>")
        body.append("".join(lg))
        panes = []
        for t in tutors_present:
            r = trs.get(t)
            if not r:
                continue
            turns = "".join(
                f'<div class="turn {e(x["speaker"])}"><b>{e(SPEAKER_KO.get(x["speaker"], x["speaker"]))}</b><div>{e(x["text"])}</div></div>'
                for x in r["dialogue"])
            diag = ""
            if t != "baseline":
                diag = (f'<div class="box"><b>튜터가 적은 학생의 오개념 · {e(DIAG_KO.get(r.get("diagnosis_match"), ""))}</b>'
                        f'<div>{e(r.get("diagnosis"))}</div></div>')
            pt = r["post_transfer"]
            panes.append(
                f'<div class="pane"><h4>{e(t)}<span class="chip c-{r["status"]}">{STATUS_KO[r["status"]]}</span></h4>'
                f'{turns}{diag}<div class="turn"><b>전이 문항 답(튜터링 뒤)</b></div>{_resp(pt["response"], pt["grade"])}</div>')
        body.append(f'<div class="panes">{"".join(panes)}</div>')
        items.append(f'<details class="task" data-unresolved="{1 if unresolved else 0}" data-k="{1 if lr["meta"]["type"] == "지식" else 0}">'
                     f'{summary}<div class="tbody">{"".join(body)}</div></details>')
    H.append('<section><h2>과제별 결과</h2><p>LLM 튜터가 해소하지 못한 과제가 위에 온다. 줄을 누르면 학습자 답, 튜터와의 대화, 채점 근거가 펼쳐진다.</p>'
             '<div class="filters" role="group" aria-label="과제 거르기">'
             '<button type="button" data-f="all" aria-pressed="true">전체</button>'
             f'<button type="button" data-f="unresolved" aria-pressed="false">해소 안 된 과제 ({n_unres})</button>'
             '<button type="button" data-f="knowledge" aria-pressed="false">지식 카드</button>'
             '<button type="button" data-f="behavior" aria-pressed="false">행동 카드</button></div>'
             f'<div class="tasks">{"".join(items)}</div></section>')

    # ---------- 해석 ----------
    caveats = [
        f"학습자·튜터·채점자가 모두 같은 모델({model_txt})이다. 자기가 만든 튜터 발화를 같은 모델이 학생으로 받아 주고 채점까지 하므로 점수가 후하게 나왔을 수 있다. 본 실험에서는 채점자를 다른 회사의 모델로 두는 편이 좋다.",
        f"과제가 {lm.get('n')}개뿐이고 과제마다 한 번씩만 돌렸다. 신뢰구간이 넓고, 유형별 숫자는 칸마다 1~4개라 경향만 보여 준다.",
        "가상 학습자가 실제 고1 학생처럼 고집하고 고치는지는 아직 확인하지 않았다. 사람 학생 자료와 맞춰 봐야 점수를 실제 효과로 읽을 수 있다.",
        "LLM 채점자가 맡은 문항(서술형·코드 작성·디버깅·설계)은 사람 채점 표본으로 일치도를 확인해야 한다.",
    ]
    H.append('<section><h2>읽을 때 주의할 점</h2><ul style="margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px;max-width:72ch">'
             + "".join(f"<li>{e(x)}</li>" for x in caveats) + "</ul></section>")

    gloss = [
        ("해소", "지식 카드는 전이 정답과 이유에 카드의 '해소 판정' 내용이 모두 들어간 경우. 행동 카드는 '관찰할 것'의 바람직한 행동을 보인 경우"),
        ("부분 해소", "전이 정답은 맞혔지만 이유가 부족한 경우(행동 카드는 부분적으로 바람직한 행동)"),
        ("유지", "전이 문항에서도 같은 오개념 답이나 습관 행동을 보인 경우"),
        ("해소 점수", "해소 1, 부분 해소 0.5, 미해소 0의 평균. 괄호의 범위는 부트스트랩 95% 신뢰구간"),
        ("대조군 대비", "같은 과제에서 이 튜터의 해소 점수에서 대조군(baseline)의 해소 점수를 뺀 값"),
        ("진단 정확도", "대화 뒤 튜터가 적은 학생의 오개념이 카드의 믿음과 같은지(일치 1, 부분 0.5, 불일치 0)"),
        ("규칙 / judge", "채점 방식. 출력 예측·개념 선택은 실제 실행 결과와 보기 번호로 먼저 기계 채점하고, 나머지는 LLM 채점자가 카드의 채점 기준으로 판정했다"),
    ]
    H.append('<section><h2>용어</h2><dl class="gloss">' + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in gloss) + "</dl></section>")
    H.append(f'<footer>이 보고서는 {e(run_dir.name)}의 기록 파일로 만들었다. 다시 만들기: python -m mbench report --run-dir {e(run_dir)} --html</footer>')

    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@500;600;700&family=Noto+Sans+KR:wght@400;500;600&display=swap">')
    return (f'<title>{e(title)}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            f'<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'{fonts}\n<style>{CSS}</style>\n<div class="wrap">{"".join(H)}</div>\n<script>{JS}</script>\n')


def write_html(run_dir: Path, cards_path: str | None = None) -> Path:
    out = Path(run_dir) / "report.html"
    out.write_text(render_html(Path(run_dir), cards_path), encoding="utf-8")
    return out

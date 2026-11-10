"""데이터 점검: 형식 규칙 확인과 코드 문항 재실행.

재실행은 카드의 run.stdout과 지금 환경의 출력을 비교한다. 카드는 Python 3.11.1과
Apple clang 17.0.0에서 실행됐으므로, 다른 판·다른 컴파일러에서는 정의되지 않은 동작(판단 문항),
주소·난수, 오류 메시지 문구 때문에 차이가 날 수 있다. 차이는 '확인할 목록'일 뿐 곧 오류는 아니다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .data import CIRCLED, Task, circled_choices, main_answer

C_PRELUDE = "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <limits.h>\n"


def schema_issues(tasks: list[Task]) -> list[str]:
    issues = []
    for t in tasks:
        for part in ("diagnostic", "transfer"):
            it = getattr(t, part)
            where = f"{t.task_id}:{part}"
            if not it.prompt:
                issues.append(f"{where} 문항 지시문 없음")
            if not it.answer:
                issues.append(f"{where} 정답 없음")
            if not it.misconception_answer:
                issues.append(f"{where} 오개념 답 없음")
            if t.is_knowledge and main_answer(it.answer) == main_answer(it.misconception_answer):
                issues.append(f"{where} 정답과 오개념 답이 같음")
            if not t.is_knowledge and not it.observable:
                issues.append(f"{where} 행동 카드인데 '관찰할 것' 없음")
            if it.format == "개념 선택":
                if not circled_choices(it.answer):
                    issues.append(f"{where} 개념 선택인데 정답 번호(①~) 없음")
                if not circled_choices(it.prompt) and not circled_choices(t.diagnostic.prompt + (it.code or "")):
                    issues.append(f"{where} 개념 선택인데 보기 번호 없음")
            if it.format == "출력 예측" and not it.code:
                issues.append(f"{where} 출력 예측인데 코드 없음")
        if not t.resolution:
            issues.append(f"{t.task_id} 해소 판정 기준 없음")
    return issues


def _run_python(code: str, stdin: str | None, files: dict | None, timeout: float) -> tuple[str, int]:
    with tempfile.TemporaryDirectory() as d:
        for name, content in (files or {}).items():
            (Path(d) / name).write_text(str(content), encoding="utf-8")
        (Path(d) / "main.py").write_text(code, encoding="utf-8")
        p = subprocess.run([sys.executable, "-I", "main.py"], cwd=d, input=stdin or "", capture_output=True,
                           text=True, timeout=timeout)
        return p.stdout, p.returncode


def _run_c(code: str, stdin: str | None, files: dict | None, timeout: float, cc: str) -> tuple[str, int] | None:
    src = code if "main(" in code else C_PRELUDE + "int main(void) {\n" + code + "\nreturn 0;\n}\n"
    if "main(" in code and "#include" not in code:
        src = C_PRELUDE + code
    with tempfile.TemporaryDirectory() as d:
        for name, content in (files or {}).items():
            (Path(d) / name).write_text(str(content), encoding="utf-8")
        (Path(d) / "main.c").write_text(src, encoding="utf-8")
        b = subprocess.run([cc, "-w", "main.c", "-o", "prog", "-lm"], cwd=d, capture_output=True, text=True,
                           timeout=60)
        if b.returncode != 0:
            return None
        p = subprocess.run(["./prog"], cwd=d, input=stdin or "", capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.returncode


def rerun(tasks: list[Task], timeout: float = 5.0, cc: str | None = None) -> dict:
    cc = cc or shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
    stats: Counter = Counter()
    diffs: list[str] = []
    for t in tasks:
        for part in ("diagnostic", "transfer"):
            it = getattr(t, part)
            if not it.code or not it.run or it.run.get("stdout") is None:
                continue
            key = f"{t.task_id}:{part}"
            try:
                if t.language == "Python":
                    res = _run_python(it.code, it.stdin, it.files, timeout)
                elif t.language == "C" and cc:
                    res = _run_c(it.code, it.stdin, it.files, timeout, cc)
                else:
                    stats["건너뜀"] += 1
                    continue
            except subprocess.TimeoutExpired:
                stats["시간 초과"] += 1
                diffs.append(f"{key} 시간 초과")
                continue
            if res is None:
                stats[f"{t.language} 컴파일 실패"] += 1
                diffs.append(f"{key} 컴파일 실패(조각 코드일 수 있음)")
                continue
            out, _ = res
            if out == it.run["stdout"]:
                stats[f"{t.language} 일치"] += 1
            elif out.strip() == it.run["stdout"].strip():
                stats[f"{t.language} 공백만 다름"] += 1
            else:
                stats[f"{t.language} 다름"] += 1
                diffs.append(f"{key} [{it.format}] 기대 {it.run['stdout'][:60]!r} / 실제 {out[:60]!r}")
    return {"stats": dict(stats), "diffs": diffs, "python": sys.version.split()[0], "cc": cc}

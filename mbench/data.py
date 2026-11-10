"""오개념 카드(2판 JSON)를 읽어 벤치마크 과제(카드 × 언어)로 바꾼다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_CARDS = Path(__file__).resolve().parent.parent / "data" / "cards_v2.json"

# 지식 카드는 정답/오개념 답으로, 나머지 유형은 '관찰할 것'의 행동으로 판정한다.
KNOWLEDGE_TYPE = "지식"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


@dataclass
class Item:
    """진단 또는 전이 문항 하나."""

    format: str
    prompt: str
    code: str | None
    stdin: str | None
    files: dict | None
    answer: str
    misconception_answer: str
    observable: str | None
    grading: str | None
    run: dict | None

    @classmethod
    def from_json(cls, d: dict) -> "Item":
        return cls(
            format=d.get("format", ""),
            prompt=d.get("prompt", ""),
            code=d.get("code"),
            stdin=d.get("stdin"),
            files=d.get("files") or None,
            answer=d.get("answer", ""),
            misconception_answer=d.get("misconception_answer", ""),
            observable=d.get("observable"),
            grading=d.get("grading"),
            run=d.get("run"),
        )


@dataclass
class Task:
    """벤치마크의 단위: 카드 하나를 한 언어로 묻는 과제."""

    card_id: str
    language: str  # Python | C | 공통
    title: str
    type: str
    area: str
    level: str
    cause: str
    strength: str
    belief: str
    typical_remark: str | None
    trigger: str
    resolution: str
    tutor_tags: list[str]
    standards: list[str]
    experiment: str
    symptom: str
    diagnostic: Item
    transfer: Item
    related: list[str] = field(default_factory=list)

    @property
    def task_id(self) -> str:
        return f"{self.card_id}/{self.language}"

    @property
    def is_knowledge(self) -> bool:
        return self.type == KNOWLEDGE_TYPE

    def meta(self) -> dict:
        """집계에 쓰는 분류 칸."""
        return {
            "card_id": self.card_id,
            "language": self.language,
            "type": self.type,
            "area": self.area,
            "level": self.level,
            "cause": self.cause,
            "strength": self.strength,
            "tutor_tags": self.tutor_tags,
            "experiment": self.experiment,
        }


def load_cards(path: str | Path | None = None) -> tuple[dict, list[dict]]:
    with open(path or DEFAULT_CARDS, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("meta", {}), d["cards"]


def build_tasks(cards: Iterable[dict]) -> list[Task]:
    tasks = []
    for c in cards:
        for lang, it in c["items"].items():
            tasks.append(
                Task(
                    card_id=c["id"],
                    language=lang,
                    title=c["title"],
                    type=c["type"],
                    area=c["area"],
                    level=c["level"],
                    cause=c["cause"],
                    strength=c["strength"],
                    belief=c["belief"],
                    typical_remark=c.get("typical_remark"),
                    trigger=c.get("trigger", ""),
                    resolution=c["resolution"],
                    tutor_tags=list(c.get("tutor_tags", [])),
                    standards=list(c.get("standards", [])),
                    experiment=c.get("experiment", ""),
                    symptom=it.get("symptom", ""),
                    diagnostic=Item.from_json(it["diagnostic"]),
                    transfer=Item.from_json(it["transfer"]),
                    related=list(c.get("related", [])),
                )
            )
    return tasks


def _split(v: str | None) -> list[str] | None:
    if not v:
        return None
    return [s.strip() for s in v.split(",") if s.strip()]


def filter_tasks(
    tasks: list[Task],
    *,
    languages: str | None = None,
    types: str | None = None,
    areas: str | None = None,
    levels: str | None = None,
    tags: str | None = None,
    strengths: str | None = None,
    ids: str | None = None,
    experiment: str | None = None,
    limit: int | None = None,
    sample_seed: int | None = None,
) -> list[Task]:
    """쉼표로 나눈 값으로 과제를 거른다. 같은 칸 안은 OR, 칸끼리는 AND."""
    langs, tys, ars, lvs, tgs, sts, idl = map(
        _split, (languages, types, areas, levels, tags, strengths, ids)
    )
    out = []
    for t in tasks:
        if langs and t.language not in langs:
            continue
        if tys and t.type not in tys:
            continue
        if ars and t.area not in ars:
            continue
        if lvs and t.level not in lvs:
            continue
        if sts and t.strength not in sts:
            continue
        if tgs and not set(tgs) & set(t.tutor_tags):
            continue
        if idl and t.card_id not in idl and t.task_id not in idl:
            continue
        if experiment is not None and t.experiment != experiment:
            continue
        out.append(t)
    if limit is not None and limit < len(out):
        if sample_seed is None:
            out = out[:limit]
        else:
            import random

            rng = random.Random(sample_seed)
            out = sorted(rng.sample(out, limit), key=lambda t: t.task_id)
    return out


# ---------- 답 정규화 (규칙 채점용) ----------

_TRAIL_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def main_answer(text: str) -> str:
    """'9 (두 값이 ...)'처럼 끝에 붙은 괄호 설명을 떼어 낸 대표 답."""
    s = (text or "").strip()
    while True:
        t = _TRAIL_PAREN.sub("", s).strip()
        if t == s or not t:
            return s
        s = t


def norm_output(text: str) -> str:
    """출력 비교용: 줄 끝 공백, 앞뒤 빈 줄, 감싼 코드 펜스·따옴표를 정리한다."""
    s = (text or "").replace("\r\n", "\n").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[^\n]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    s = "\n".join(line.rstrip() for line in s.split("\n")).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1]
    return s


HANGUL_LABELS = "가나다라마바사"


def choice_tokens(text: str) -> list[str]:
    """보기 번호를 뽑는다. ①②… 와 (가)(나)… 를 모두 받는다. 순서 유지, 중복 제거."""
    out: list[str] = []
    for m in re.finditer(r"[①-⑩]|\(([가-사])\)", text or ""):
        tok = m.group(1) or m.group(0)
        if tok not in out:
            out.append(tok)
    return out


_LEAD = re.compile(r"^\s*((?:[①-⑩]|\([가-사]\))(?:\s*(?:,|와|과|및|그리고)?\s*(?:[①-⑩]|\([가-사]\)))*)")


def leading_choices(text: str) -> list[str]:
    """답 맨 앞에 나열된 보기만 뽑는다. '④만. ②, ③은 …'에서 ④만 얻는다(뒤 설명 속 번호는 무시)."""
    m = _LEAD.match(text or "")
    return choice_tokens(m.group(1)) if m else []


def circled_choices(text: str) -> list[str]:
    return choice_tokens(text)


def learner_choices(text: str) -> list[str]:
    """학생 답에서 고른 보기들. '①', '1번', '1', '(가)', '가' 모두 받는다."""
    toks = leading_choices(text) or choice_tokens(text)
    if toks:
        return toks
    s = (text or "").strip()
    m = re.fullmatch(r"(\d{1,2})\s*(번|\)|\.)?", s)
    if m and 1 <= int(m.group(1)) <= len(CIRCLED):
        return [CIRCLED[int(m.group(1)) - 1]]
    m = re.fullmatch(r"([가-사])\s*(번|\)|\.)?", s)
    if m:
        return [m.group(1)]
    return []


def first_choice(text: str) -> str | None:
    c = learner_choices(text)
    return c[0] if c else None

"""LLM 백엔드.

- AnthropicBackend: Claude API(공식 `anthropic` SDK).
- MockBackend: API 없이 파이프라인을 끝까지 돌려 보는 결정적 모의 백엔드.
  카드의 정답·오개념 답을 그대로 돌려주므로 점수 자체에는 의미가 없다.

모든 호출은 `complete(system, messages, schema=None, meta=None)` 하나로 한다.
`meta`는 모의 백엔드만 쓰는 힌트(역할, 과제 정보)이며 실제 API에는 보내지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, i: int, o: int) -> None:
        with self._lock:
            self.input_tokens += i
            self.output_tokens += o
            self.calls += 1


class Backend:
    name = "base"

    def __init__(self) -> None:
        self.usage = Usage()

    def complete(
        self,
        system: str,
        messages: list[dict],
        schema: dict | None = None,
        meta: dict | None = None,
        max_tokens: int = 4000,
    ) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class AnthropicBackend(Backend):
    """Claude API 백엔드. 거절(refusal)에 대비해 서버 측 대체 모델(fallbacks)을 기본으로 켠다."""

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: str | None = "medium",
        use_fallbacks: bool = True,
        max_retries: int = 4,
    ) -> None:
        super().__init__()
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise SystemExit("anthropic 패키지가 필요합니다: pip install anthropic") from e
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=max_retries)
        self.model = model
        self.effort = effort
        self.use_fallbacks = use_fallbacks
        self.name = f"anthropic:{model}"

    def complete(self, system, messages, schema=None, meta=None, max_tokens=4000):
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        output_config: dict = {}
        if self.effort:
            output_config["effort"] = self.effort
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            kwargs["output_config"] = output_config

        if self.use_fallbacks:
            resp = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            resp = self.client.messages.create(**kwargs)

        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage.add(getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            raise RuntimeError("모델이 요청을 거절했습니다(stop_reason=refusal).")
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return text.strip()


class GeminiBackend(Backend):
    """Google Gemini 백엔드(`google-genai` SDK). 키는 GEMINI_API_KEY 또는 GOOGLE_API_KEY에서 읽는다."""

    def __init__(self, model: str = "gemini-2.5-pro", max_retries: int = 4) -> None:
        super().__init__()
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:  # pragma: no cover
            raise SystemExit("google-genai 패키지가 필요합니다: pip install google-genai") from e
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            raise SystemExit("GEMINI_API_KEY(또는 GOOGLE_API_KEY) 환경 변수가 없습니다.")
        self.client = genai.Client()
        self.types = types
        self.model = model
        self.max_retries = max_retries
        self.name = f"gemini:{model}"

    def complete(self, system, messages, schema=None, meta=None, max_tokens=4000):
        t = self.types
        contents = [
            t.Content(role="model" if m["role"] == "assistant" else "user", parts=[t.Part(text=str(m["content"]))])
            for m in messages
        ]
        # Gemini는 생각(thinking) 토큰도 출력 한도에 넣으므로 여유를 둔다.
        cfg: dict = {"system_instruction": system, "max_output_tokens": max(max_tokens * 4, 8192)}
        if schema:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = schema
        config = t.GenerateContentConfig(**cfg)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.models.generate_content(model=self.model, contents=contents, config=config)
                break
            except Exception as e:  # 429·5xx 등: 잠시 쉬고 다시
                last = e
                code = getattr(e, "code", None)
                if code is not None and code < 500 and code != 429:
                    raise
                time.sleep(min(60, 2 ** (attempt + 1)))
        else:
            raise RuntimeError(f"Gemini 호출 실패: {last}")
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            self.usage.add(getattr(um, "prompt_token_count", 0) or 0,
                           (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0))
        text = resp.text
        if not text:
            fr = resp.candidates[0].finish_reason if resp.candidates else None
            raise RuntimeError(f"Gemini가 빈 응답을 돌려줬습니다(finish_reason={fr}).")
        return text.strip()


class MockBackend(Backend):
    """API 없이 도는 모의 백엔드.

    - 학습자(믿음 있음): 오개념 대표 답을 낸다.
    - 학습자(통제): 정답을 낸다.
    - 튜터 대화 뒤 전이: 과제·튜터 이름·시드로 정한 확률(resolve_rate)로 정답을 낸다.
    - 튜터: 정해진 문장을 낸다. 'baseline' 튜터 뒤에는 해소되지 않는다.
    - 채점자: 규칙 채점이 실패한 경우에만 불리며, 문자열 유사도로 판정한다.
    """

    name = "mock"

    def __init__(self, resolve_rate: float = 0.6, seed: int = 0) -> None:
        super().__init__()
        self.resolve_rate = resolve_rate
        self.seed = seed

    def _coin(self, *parts) -> float:
        h = hashlib.sha256("|".join(map(str, (self.seed, *parts))).encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF

    def complete(self, system, messages, schema=None, meta=None, max_tokens=4000):
        meta = meta or {}
        role = meta.get("role")
        self.usage.add(sum(len(str(m.get("content", ""))) for m in messages) // 3, 40)
        from .data import main_answer

        if role == "learner_answer":
            item = meta["item"]
            if meta.get("belief_active"):
                resolved = False
                if meta.get("after_tutoring") and meta.get("tutor") != "baseline":
                    resolved = self._coin(meta["task_id"], meta.get("tutor"), meta.get("rep")) < self.resolve_rate
                if not resolved:
                    return json.dumps(
                        {"answer": main_answer(item["misconception_answer"]), "reason": "원래 생각대로 풀었어요."},
                        ensure_ascii=False,
                    )
            ans = item["answer"]
            if item.get("run") and item.get("format") == "출력 예측" and item["run"].get("stdout"):
                ans = item["run"]["stdout"]
            return json.dumps({"answer": main_answer(ans), "reason": meta.get("resolution", "")}, ensure_ascii=False)

        if role == "learner_chat":
            return "음… 잘 모르겠어요. 제 생각에는 원래대로 될 것 같은데요."
        if role == "tutor":
            if meta.get("tutor") == "baseline":
                return "다시 한번 천천히 생각해 볼까요?"
            return "코드를 한 줄씩 따라가며 변수 값을 표로 적어 볼까요? 각 줄이 끝날 때 값이 어떻게 되는지 써 보세요."
        if role == "tutor_diagnosis":
            return meta.get("belief", "")[:80] if meta.get("tutor") != "baseline" else "모르겠다"
        if role == "judge_item":
            import difflib

            resp = meta.get("response", "")
            item = meta["item"]
            a = difflib.SequenceMatcher(None, resp, main_answer(item["answer"])).ratio()
            b = difflib.SequenceMatcher(None, resp, main_answer(item["misconception_answer"])).ratio()
            if meta.get("knowledge", True):
                label = "correct" if a >= b and a > 0.5 else ("misconception" if b > 0.5 else "other")
            else:
                label = "desired" if a >= b and a > 0.5 else ("habit" if b > 0.5 else "other")
            return json.dumps(
                {"label": label, "reason_ok": label in ("correct", "desired"), "rationale": "mock similarity"},
                ensure_ascii=False,
            )
        if role == "judge_diagnosis":
            ok = meta.get("diagnosis", "") and meta.get("diagnosis") != "모르겠다"
            return json.dumps({"match": "full" if ok else "none", "rationale": "mock"}, ensure_ascii=False)
        return "{}" if schema else ""


def make_backend(spec: str, effort: str | None = "medium", seed: int = 0) -> Backend:
    """'mock', 'mock:0.4'(해소 확률), 'claude-opus-5-5', 'anthropic:claude-sonnet-5-5',
    'gemini:gemini-2.5-pro'(또는 'gemini-…'로 시작하는 이름) 등을 받는다."""
    if spec.startswith("gemini:") or spec.startswith("gemini-"):
        return GeminiBackend(model=spec.split(":", 1)[1] if spec.startswith("gemini:") else spec)
    if spec.startswith("mock"):
        rate = float(spec.split(":", 1)[1]) if ":" in spec else 0.6
        return MockBackend(resolve_rate=rate, seed=seed)
    model = spec.split(":", 1)[1] if spec.startswith("anthropic:") else spec
    fallbacks = os.environ.get("MBENCH_NO_FALLBACKS") is None
    return AnthropicBackend(model=model, effort=effort, use_fallbacks=fallbacks)


def call_json(backend: Backend, system: str, messages: list[dict], schema: dict, meta: dict | None = None,
              retries: int = 2, max_tokens: int = 4000) -> dict:
    """JSON 응답을 받아 파싱한다. 형식이 깨지면 몇 번 다시 묻는다."""
    last = None
    for attempt in range(retries + 1):
        text = backend.complete(system, messages, schema=schema, meta=meta, max_tokens=max_tokens)
        try:
            s = text.strip()
            if s.startswith("```"):
                s = s.strip("`")
                s = s[s.find("{"):]
            start, end = s.find("{"), s.rfind("}")
            return json.loads(s[start : end + 1])
        except (ValueError, json.JSONDecodeError) as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"JSON 응답을 파싱하지 못했습니다: {last}")

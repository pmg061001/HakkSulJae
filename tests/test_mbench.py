"""API 없이 도는 시험. 실행: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mbench.agents import BaselineTutor, Learner, Tutor, load_tutor  # noqa: E402
from mbench.data import build_tasks, filter_tasks, leading_choices, learner_choices, load_cards, main_answer, norm_output  # noqa: E402
from mbench.grading import Grader, resolution_status, rule_grade  # noqa: E402
from mbench.llm import MockBackend  # noqa: E402
from mbench.metrics import summarize  # noqa: E402
from mbench.runner import RecordStore, run_benchmark  # noqa: E402

META, CARDS = load_cards()
TASKS = build_tasks(CARDS)


class SpyTutor(Tutor):
    """튜터가 받는 정보를 기록한다(누설 시험용)."""

    name = "spy"
    seen: list = []

    def __init__(self, backend=None):
        pass

    def turn(self, ctx, dialogue):
        SpyTutor.seen.append((ctx.to_dict(), [dict(t) for t in dialogue]))
        return "한 줄씩 따라가 볼까요? [대화 끝]"

    def diagnose(self, ctx, dialogue):
        return "모르겠다"


class TestData(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(CARDS), 354)
        self.assertEqual(len(TASKS), 544)
        self.assertEqual(len(filter_tasks(TASKS, languages="Python")), 283)

    def test_filters(self):
        t = filter_tasks(TASKS, languages="Python", areas="VAR", types="지식")
        self.assertTrue(t and all(x.area == "VAR" and x.type == "지식" for x in t))
        self.assertEqual(len(filter_tasks(TASKS, limit=5, sample_seed=1)), 5)
        self.assertEqual([x.task_id for x in filter_tasks(TASKS, ids="VAR-01/C")], ["VAR-01/C"])

    def test_normalizers(self):
        self.assertEqual(main_answer("9 (두 값이 함께 남는다고 보는 학생은 4 5)"), "9")
        self.assertEqual(main_answer("(1, 2)"), "(1, 2)")
        self.assertEqual(norm_output("```\n5  \n```"), "5")
        self.assertEqual(leading_choices("④만. ②, ③과 ①은 틀렸다"), ["④"])
        self.assertEqual(leading_choices("(가), (나), (다) 모두"), ["가", "나", "다"])
        self.assertEqual(learner_choices("2번"), ["②"])
        self.assertEqual(learner_choices("나"), ["나"])


class TestGrading(unittest.TestCase):
    def test_rule_grader_agrees_with_cards(self):
        """카드의 정답을 넣으면 정답 또는 판정 보류, 오개념 답을 넣으면 오개념 또는 보류. 반대로 매기면 안 된다."""
        for t in TASKS:
            if not t.is_knowledge:
                continue
            for it in (t.diagnostic, t.transfer):
                a = rule_grade(it, {"answer": main_answer(it.answer)})
                m = rule_grade(it, {"answer": main_answer(it.misconception_answer)})
                self.assertIn(a, ("correct", None), t.task_id)
                self.assertIn(m, ("misconception", None), t.task_id)

    def test_output_prediction_uses_stdout(self):
        t = next(x for x in TASKS if x.task_id == "VAR-01/Python")
        self.assertEqual(rule_grade(t.diagnostic, {"answer": "5"}), "correct")
        self.assertEqual(rule_grade(t.diagnostic, {"answer": "9"}), "misconception")
        self.assertIsNone(rule_grade(t.diagnostic, {"answer": "4"}))

    def test_resolution_status(self):
        k = next(x for x in TASKS if x.is_knowledge)
        b = next(x for x in TASKS if not x.is_knowledge)
        self.assertEqual(resolution_status(k, {"label": "correct", "reason_ok": True}), "resolved")
        self.assertEqual(resolution_status(k, {"label": "correct", "reason_ok": False}), "partial")
        self.assertEqual(resolution_status(k, {"label": "misconception"}), "persisted")
        self.assertEqual(resolution_status(k, {"label": "other"}), "other_wrong")
        self.assertEqual(resolution_status(b, {"label": "habit"}), "persisted")
        self.assertEqual(resolution_status(b, {"label": "desired"}), "resolved")


class TestPipeline(unittest.TestCase):
    def _run(self, d, tutors, tasks):
        be = MockBackend(resolve_rate=0.5)
        return run_benchmark(tasks, Path(d), Learner(be), Grader(be), tutors, reps=2, max_turns=3, workers=4)

    def test_end_to_end_and_resume(self):
        tasks = filter_tasks(TASKS, languages="Python", limit=12, sample_seed=3)
        be = MockBackend(resolve_rate=0.5)
        with tempfile.TemporaryDirectory() as d:
            tutors = [BaselineTutor(), load_tutor("socratic", be)]
            store = self._run(d, tutors, tasks)
            n = len(store.all())
            s = summarize(store.all())
            self.assertEqual(s["learner"]["n"], 24)
            self.assertEqual(s["tutors"]["baseline"]["overall"]["RS"], 0.0)
            self.assertIn("NET", s["tutors"]["socratic"]["overall"])
            json.dumps(s, ensure_ascii=False)
            from mbench.report import render_markdown

            self.assertIn("튜터 효과", render_markdown(s))
            # 이어 하기: 같은 디렉터리로 다시 돌리면 새 기록이 없다
            store2 = self._run(d, tutors, tasks)
            self.assertEqual(len(store2.all()), n)
            self.assertEqual(len(RecordStore(Path(d)).all()), n)

    def test_tutor_sees_no_belief_or_transfer(self):
        tasks = filter_tasks(TASKS, languages="Python", types="지식", limit=8)
        SpyTutor.seen = []
        with tempfile.TemporaryDirectory() as d:
            self._run(d, [SpyTutor()], tasks)
        self.assertTrue(SpyTutor.seen)
        by_id = {t.task_id: t for t in tasks}
        for ctx, dialogue in SpyTutor.seen:
            t = by_id[ctx["task_id"]]
            blob = json.dumps([ctx, dialogue], ensure_ascii=False)
            self.assertNotIn(t.belief, blob)
            self.assertNotIn(t.resolution, blob)
            if t.transfer.code and t.transfer.code != t.diagnostic.code:
                self.assertNotIn(t.transfer.code, blob)

    def test_load_custom_tutor(self):
        tut = load_tutor("tests.test_mbench:SpyTutor", MockBackend())
        self.assertEqual(tut.name, "spy")


if __name__ == "__main__":
    unittest.main()

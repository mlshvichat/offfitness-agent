import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import agent
import editorial as e


GOOD = dict(approved=True, medical_concern=False, duplicate_topic=False,
            meaning_preserved=True, issues=[])


class Editorial(unittest.TestCase):
    def prepare(self, verdicts, edits=None, safety=None):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            report = Path(folder) / "report.json"
            with patch.object(e, "review", side_effect=verdicts), patch.object(e, "ask", side_effect=edits or []) as editor:
                try:
                    result = e.prepare(lambda: ("topic", "original"), [], Mock(), Mock(),
                                       safety or Mock(), report)
                except RuntimeError:
                    result = None
            return result, json.loads(report.read_text("utf-8")), editor.call_count

    def test_pass_without_rewrite(self):
        result, report, calls = self.prepare([GOOD])
        self.assertEqual(result, ("topic", "original"))
        self.assertEqual(report["status"], "approved")
        self.assertEqual(calls, 0)

    def test_edit_rechecked_and_safety_repeated(self):
        safety = Mock()
        result, report, calls = self.prepare(
            [dict(GOOD, approved=False, issues=["Штамп"]), GOOD],
            [{"post": "edited", "changes": ["Убрали штамп"]}], safety)
        self.assertEqual(result, ("topic", "edited"))
        self.assertEqual(safety.call_count, 2)
        self.assertEqual(len(report["reviews"]), 2)
        self.assertEqual(calls, 1)

    def test_at_most_three_edits_then_block(self):
        result, report, calls = self.prepare(
            [dict(GOOD, approved=False, issues=["Повтор"]) for _ in range(4)],
            [{"post": "revision", "changes": ["Правка"]} for _ in range(3)])
        self.assertIsNone(result)
        self.assertEqual(calls, 3)
        self.assertEqual(len(report["reviews"]), 4)
        self.assertEqual(report["status"], "blocked")

    def test_medical_duplicate_or_meaning_failure_never_rewritten(self):
        for bad in (dict(GOOD, medical_concern=True), dict(GOOD, duplicate_topic=True),
                    dict(GOOD, meaning_preserved=False)):
            result, report, calls = self.prepare([bad])
            self.assertIsNone(result)
            self.assertEqual(calls, 0)

    def test_safety_error_fails_closed_with_report(self):
        result, report, calls = self.prepare([], safety=Mock(side_effect=RuntimeError("secret")))
        self.assertIsNone(result)
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(calls, 0)

    def test_safe_http_diagnostics(self):
        _, report, _ = self.prepare([], safety=Mock(side_effect=RuntimeError("Remote API HTTP 429; response body withheld")))
        self.assertEqual(report["remote_http_status"], 429)

    def test_review_outage_and_bad_edit_fail_closed(self):
        result, report, _ = self.prepare([ValueError("bad JSON")])
        self.assertIsNone(result)
        result, report, _ = self.prepare([dict(GOOD, approved=False)], [{"post": 3}])
        self.assertIsNone(result)

    def test_verdict_schema_strict(self):
        for obj in ({}, dict(GOOD, approved="true"), dict(GOOD, issues="none"),
                    dict(GOOD, meaning_preserved=None)):
            with patch.object(e, "ask", return_value=obj):
                with self.assertRaises(ValueError):
                    e.review(Mock(), "topic", "post", [], "post")

    def test_recent_thirty_and_legacy_style(self):
        history = [{"topic": str(i), "post": "Title\n\nBody"} for i in range(35)]
        history.append({"topic": "reserved", "status": "reserved"})
        recent = e.memory(history)
        self.assertEqual(len(recent), 30)
        self.assertEqual(recent[0]["topic"], "5")
        self.assertEqual(recent[-1]["style"]["heading"], "Title")

    def test_local_signals_and_repeated_ending(self):
        text = "Важно отметить: это не сила, а привычка 😀😀😀\n\nПовторный финал."
        findings = e.local_findings(text, [{"post": "Другой заголовок\n\nПовторный финал."}])
        self.assertGreaterEqual(len(findings), 4)

    def test_model_cannot_override_local_findings(self):
        with patch.object(e, "ask", return_value=dict(GOOD)):
            verdict = e.review(Mock(), "topic", "😀😀😀", [], "😀😀😀")
        self.assertTrue(verdict["issues"])

    def test_no_live_date_exception(self):
        with patch.object(agent, "LIVE_APPROVED", False), patch.dict(os.environ, {"ACTION_MODE": "live", "LIVE_ENABLED": "true", "GITHUB_REF": "refs/heads/main"}), patch.object(agent, "ZoneInfo", return_value=dt.timezone.utc), patch.object(agent, "verify_live_destination") as target:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                agent.run()
            target.assert_not_called()

    def test_failed_editor_prevents_delivery(self):
        with patch.dict(os.environ, {"ACTION_MODE": "test", "GEMINI_API_KEY": "fake", "GITHUB_REF": "refs/heads/main"}), patch.object(agent, "ZoneInfo", return_value=dt.timezone.utc), patch.object(agent, "read_history", return_value=[]), patch.object(agent, "verify_test_destination", return_value="-200"), patch.object(e, "prepare", side_effect=RuntimeError("blocked")), patch.object(agent, "telegram_send") as send, patch.object(agent, "persist_history") as save:
            with self.assertRaises(RuntimeError):
                agent.run()
            send.assert_not_called()
            save.assert_not_called()

    def test_development_branch_cannot_publish_or_push_main(self):
        with patch.dict(os.environ, {"ACTION_MODE": "test", "GITHUB_REF": "refs/heads/feature"}), patch.object(agent, "ZoneInfo", return_value=dt.timezone.utc), patch.object(agent, "verify_test_destination") as target:
            with self.assertRaisesRegex(RuntimeError, "only from main"):
                agent.run()
            target.assert_not_called()


if __name__ == "__main__":
    unittest.main()

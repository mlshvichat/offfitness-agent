import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import reliable as r
import agent

NOW = dt.datetime(2026, 11, 3, 22, tzinfo=r.START.tzinfo)

def candidate():
    post = "A useful unique post " * 30
    return {"topic": "Unique", "post": post, "slot": 19, "sha256": r.digest(post),
            "approval": {"status": "approved", "reviews": [{
                "approved": True, "issues": [], "meaning_preserved": True,
                "duplicate_topic": False, "medical_concern": False}]}}

def fake_agent():
    a=Mock()
    a.__name__="agent"
    a.SLOTS={9:("motivation","m"),14:("training","t"),19:("science","s")}
    a.verify_live_destination.return_value="-100"
    a.telegram_send.return_value=99
    return a

class Reliability(unittest.TestCase):
    def test_backlog_survives_two_hour_window_and_next_day(self):
        a=fake_agent()
        slots=r.due_slots(a,NOW)
        self.assertEqual([s[0] for s in slots],["2026-11-03:science"])
        tomorrow=NOW+dt.timedelta(days=1)
        self.assertEqual(len(r.due_slots(a,tomorrow)),4)

    def test_never_publishes_before_due(self):
        self.assertEqual(r.due_slots(fake_agent(),r.START-dt.timedelta(seconds=1)),[])

    def test_approval_bound_to_exact_text(self):
        c=candidate()
        self.assertTrue(r.approval_valid(c))
        c["post"]+="changed"
        self.assertFalse(r.approval_valid(c))

    def test_every_rejection_blocks_cached_approval(self):
        for key,value in [("approved",False),("issues",["bad"]),("meaning_preserved",False),
                          ("duplicate_topic",True),("medical_concern",True)]:
            c=candidate()
            c["approval"]["reviews"][-1][key]=value
            self.assertFalse(r.approval_valid(c))

    def test_no_reserve_leaves_slot_due(self):
        a=fake_agent()
        self.assertFalse(r.deliver(a,{"ready":[]},[],Path("x"),"key",19,Mock()))
        a.telegram_send.assert_not_called()

    @patch.object(r,"public_posts",return_value=[])
    def test_remote_reservation_precedes_send(self,_):
        a=fake_agent(); history=[]; events=[]
        commit=Mock(side_effect=lambda *args:events.append(history[-1]["status"]))
        a.telegram_send.side_effect=lambda *args:events.append("send") or 99
        state={"ready":[candidate()]}
        r.deliver(a,state,history,Path("x"),"2026-11-03:science",19,commit)
        self.assertEqual(events,["reserved","send","sent"])
        self.assertEqual(state["ready"],[])

    @patch.object(r,"public_posts",return_value=[])
    def test_reservation_push_failure_prevents_send(self,_):
        a=fake_agent()
        with self.assertRaises(RuntimeError):
            r.deliver(a,{"ready":[candidate()]},[],Path("x"),"k",19,Mock(side_effect=RuntimeError()))
        a.telegram_send.assert_not_called()

    @patch.object(r,"public_posts",return_value=[])
    def test_timeout_never_repeats_send(self,_):
        a=fake_agent(); history=[]; state={"ready":[candidate()]}
        a.telegram_send.side_effect=RuntimeError("Remote API connection failed; request details withheld")
        with self.assertRaises(RuntimeError):
            r.deliver(a,state,history,Path("x"),"k",19,Mock())
        self.assertEqual(history[0]["status"],"reserved")
        with self.assertRaises(RuntimeError):
            r.deliver(a,state,history,Path("x"),"k",19,Mock())
        self.assertEqual(a.telegram_send.call_count,1)

    @patch.object(r,"public_posts",return_value=[])
    def test_definitive_429_requeues_without_ambiguous_state(self,_):
        a=fake_agent();history=[];state={"ready":[candidate()],"failures":[]}
        a.telegram_send.side_effect=RuntimeError("Remote API HTTP 429; response body withheld")
        with self.assertRaises(RuntimeError):
            r.deliver(a,state,history,Path("x"),"k",19,Mock())
        self.assertEqual(history,[])
        self.assertEqual(len(state["ready"]),1)

    def test_public_confirmation_reconciles_timeout_without_resend(self):
        a=fake_agent()
        history=[{"key":"k","status":"reserved","post":"same text","public_baseline":50}]
        with patch.object(r,"public_posts",return_value=[{"key":"import:offfitness/51","post":"same text"}]):
            self.assertTrue(r.deliver(a,{"ready":[]},history,Path("x"),"k",19,Mock()))
        self.assertEqual(history[0]["message_id"],51)
        a.telegram_send.assert_not_called()

    def test_old_matching_post_cannot_reconcile_new_reservation(self):
        a=fake_agent()
        history=[{"key":"k","status":"reserved","post":"same text","public_baseline":50}]
        with patch.object(r,"public_posts",return_value=[{"key":"import:offfitness/49","post":"same text"}]):
            with self.assertRaises(RuntimeError):
                r.deliver(a,{"ready":[]},history,Path("x"),"k",19,Mock())

    @patch.object(r,"public_posts",return_value=[])
    def test_duplicate_candidate_removed_without_send(self,_):
        a=fake_agent();a.validate.side_effect=ValueError()
        state={"ready":[candidate()]}
        self.assertFalse(r.deliver(a,state,[],Path("x"),"k",19,Mock()))
        self.assertEqual(state["ready"],[])
        a.telegram_send.assert_not_called()

    def test_model_fallback_and_persistent_quota_cooldown(self):
        a=fake_agent()
        a._api_json_once.side_effect=[RuntimeError("Remote API HTTP 429; response body withheld"),{"ok":True}]
        state={"cooldown":{}}
        self.assertEqual(r.model_api(a,state,"https://generativelanguage.googleapis.com/v1beta/models/x:generateContent",{}),{"ok":True})
        self.assertGreater(state["cooldown"][r.MODELS[0]],r.time.time())
        self.assertIn(r.MODELS[1],a._api_json_once.call_args.args[0])

    def test_telegram_never_uses_model_retry(self):
        a=fake_agent()
        a._api_json_once.side_effect=RuntimeError("timeout")
        with self.assertRaises(RuntimeError):
            r.model_api(a,{"cooldown":{}},"https://api.telegram.org/botfake/sendMessage",{})
        self.assertEqual(a._api_json_once.call_count,1)

    def test_corrupt_queue_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            p=Path(d)/"state.json"
            p.write_text('{"version": 10}',encoding="utf-8")
            with self.assertRaises(RuntimeError):
                r.read_state(p)

    def test_error_report_does_not_leak_credentials(self):
        state={"failures":[]}
        r.note(state,"prepare",RuntimeError("secret token URL"))
        self.assertNotIn("secret",json.dumps(state))

if __name__=="__main__": unittest.main()

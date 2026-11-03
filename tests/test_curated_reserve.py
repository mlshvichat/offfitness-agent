import datetime as dt
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import agent
import auto_agent
import curated_reserve as c
import reliable as r

class CuratedReserve(unittest.TestCase):
    def test_all_texts_pass_style_and_bounds_and_are_labelled_offline(self):
        for channel, a in [("fitness",agent),("auto",auto_agent)]:
            items=c.candidates(a,channel,[],[],19)
            self.assertEqual(len(items),2)
            for item in items:
                self.assertTrue(r.approval_valid(item))
                self.assertNotIn("reviews",item["approval"])
                self.assertEqual(a.editorial.local_findings(item["post"],[]),[])

    def test_modified_text_cannot_use_offline_approval(self):
        item=c.candidates(auto_agent,"auto",[],[],19)[0]
        item["post"]+="new offer"
        item["sha256"]=r.digest(item["post"])
        self.assertFalse(r.approval_valid(item))

    def test_published_or_queued_text_is_never_reused(self):
        items=c.candidates(auto_agent,"auto",[],[],19)
        self.assertEqual(c.candidates(auto_agent,"auto",items,[],19),[])
        self.assertEqual(c.candidates(auto_agent,"auto",[],items,19),[])

    def test_all_models_down_still_delivers_exact_offline_reviewed_text(self):
        a=Mock();a.__name__="auto_agent";a.LIVE_APPROVED=True
        a.SLOTS={19:("budget","budget")};a.read_history.return_value=[]
        a.editorial.local_findings.return_value=[]
        a.telegram_send.return_value=95
        now=dt.datetime(2026,11,3,22,tzinfo=r.START.tzinfo)
        class Clock(dt.datetime):
            @classmethod
            def now(cls,tz=None): return now
        state={"ready":[],"failures":[],"cooldown":{m:r.time.time()+3600 for m in r.MODELS}}
        with patch.dict(r.os.environ,{"LIVE_ENABLED":"true","GITHUB_REF":"refs/heads/main"}),patch.object(r.importlib,"import_module",return_value=a),patch.object(r,"read_state",return_value=state),patch.object(r,"save"),patch.object(r,"public_posts",return_value=[]),patch.object(r,"ZoneInfo",return_value=now.tzinfo),patch.object(r.dt,"datetime",Clock),patch.object(r,"prepare",side_effect=RuntimeError("models down")):
            r.run("auto")
        self.assertEqual(a.telegram_send.call_count,1)
        self.assertEqual(a.read_history.return_value[-1]["status"],"sent")
        self.assertEqual(state["remaining_due"],0)
        self.assertEqual(len(state["ready"]),1)

if __name__=="__main__": unittest.main()

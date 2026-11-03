import contextlib
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import agent

class Delivery(unittest.TestCase):
    def test_cron_mapping_and_late_window(self):
        for cron, hour in [('0 6 * * *',9),('0 11 * * *',14),('0 16 * * *',19)]:
            with patch.dict(os.environ, {'SCHEDULE_CRON':cron}):
                now=dt.datetime(2026,11,3,hour,15)
                self.assertEqual(agent.select_slot(now,'scheduled'),hour)
                with self.assertRaises(RuntimeError):
                    agent.select_slot(now+dt.timedelta(hours=3),'scheduled')

    def context(self, history, saver, sender):
        stack=contextlib.ExitStack()
        stack.enter_context(patch.object(agent,'LIVE_APPROVED',True))
        folder=stack.enter_context(tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent))
        stack.enter_context(patch.dict(os.environ, {'ACTION_MODE':'live','LIVE_ENABLED':'true','GEMINI_API_KEY':'fake','PREVIEW_HOUR':'9'}))
        stack.enter_context(patch.object(agent,'ZoneInfo',return_value=dt.timezone(dt.timedelta(hours=3))))
        stack.enter_context(patch.object(agent,'read_history',return_value=history))
        stack.enter_context(patch.object(agent,'verify_live_destination',return_value='-100'))
        stack.enter_context(patch.object(agent,'generate_post',return_value=('Unique topic','Text ' * 150)))
        stack.enter_context(patch.object(agent,'review_safety'))
        stack.enter_context(patch.object(agent,'PREVIEW_FILE',Path(folder)/'preview.txt'))
        stack.enter_context(patch.object(agent,'persist_history',saver))
        stack.enter_context(patch.object(agent,'telegram_send',sender))
        return stack

    def test_reservation_failure_prevents_send(self):
        sender=Mock()
        with self.context([],Mock(side_effect=RuntimeError('push failed')),sender):
            with self.assertRaises(RuntimeError): agent.run()
        sender.assert_not_called()

    def test_send_timeout_no_retry(self):
        history=[]
        sender=Mock(side_effect=RuntimeError('timeout'))
        saver=Mock()
        with self.context(history,saver,sender):
            with self.assertRaises(RuntimeError): agent.run()
        self.assertEqual(sender.call_count,1)
        self.assertEqual(saver.call_count,1)
        self.assertEqual(history[0]['status'],'reserved')

    def test_success_order_and_duplicate(self):
        events=[]
        history=[]
        saver=Mock(side_effect=lambda h: events.append(h[-1]['status']))
        sender=Mock(side_effect=lambda *args: events.append('send') or 42)
        with self.context(history,saver,sender):
            agent.run()
            agent.run()
        self.assertEqual(events,['reserved','send','sent'])
        self.assertEqual(sender.call_count,1)
        self.assertEqual(history[0]['message_id'],42)

    def test_unresolved_reservation_blocks_rerun(self):
        today=dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date().isoformat()
        sender=Mock()
        with self.context([{'key':today+':motivation','status':'reserved'}],Mock(),sender):
            with self.assertRaises(RuntimeError): agent.run()
        sender.assert_not_called()

    def test_exact_text_duplicate_different_topic(self):
        with self.assertRaises(ValueError):
            agent.validate('Different theme', 'Text ' * 150,[{'topic':'Old theme','post':'Text ' * 150}])

if __name__=='__main__': unittest.main()
import os
import unittest
from unittest.mock import patch
import auto_agent as agent

class Guards(unittest.TestCase):
    def responses(self, target_id=-200, target_type='channel', username='test', allowed=True):
        return [
            {'result': {'id': 1, 'username': 'mlshviauto'}},
            {'result': {'id': target_id, 'type': target_type, 'username': username}},
            {'result': {'id': -100, 'type': 'channel', 'username': 'automlshvi'}},
            {'result': {'status': 'administrator', 'can_post_messages': allowed}},
        ]

    def check_target(self, responses):
        with patch.dict(os.environ, {'AUTO_TELEGRAM_BOT_TOKEN': 'fake', 'TEST_CHAT_ID': '-200'}), patch.object(agent, 'api_json', side_effect=responses):
            return agent.verify_test_destination()

    def test_separate_channel(self):
        self.assertEqual(self.check_target(self.responses()), '-200')

    def test_production_numeric_id_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check_target(self.responses(target_id=-100))

    def test_production_username_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check_target(self.responses(username='AutoMlshvi'))

    def test_non_channel_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check_target(self.responses(target_type='private'))

    def test_no_post_permission(self):
        with self.assertRaises(RuntimeError):
            self.check_target(self.responses(allowed=False))

    def test_wrong_bot(self):
        replies = self.responses()
        replies[0]['result']['username'] = 'other_bot'
        with self.assertRaises(RuntimeError):
            self.check_target(replies)

    def test_safety_false_blocks(self):
        reply = {'candidates': [{'content': {'parts': [{'text': '{"safe":false}'}]}}]}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'fake'}), patch.object(agent, 'api_json', return_value=reply):
            with self.assertRaises(RuntimeError):
                agent.review_safety('topic', 'text')

    def test_duplicate_topic(self):
        with self.assertRaises(ValueError):
            agent.validate('Same topic!', 'x' * 600, [{'topic': 'same TOPIC'}])

if __name__ == '__main__':
    unittest.main()
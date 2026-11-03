import unittest
from auto_bootstrap import Posts
class Bootstrap(unittest.TestCase):
    def test_public_posts_and_nested_markup(self):
        p=Posts()
        p.feed('<div data-post="automlshvi/93"><div class="tgme_widget_message_text">Title<br><br>Body <b>bold</b></div></div>')
        self.assertEqual(p.posts[0]["topic"], "Title")
        self.assertIn("Body bold", p.posts[0]["post"])

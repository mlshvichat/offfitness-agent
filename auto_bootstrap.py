"""Import public channel posts for repetition checks, never as verified offers."""
import json
import urllib.request
from html.parser import HTMLParser

class Posts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.posts = []
        self.message = None
        self.depth = 0
        self.text = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-post", "").startswith("automlshvi/"):
            self.message = attrs["data-post"]
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "tgme_widget_message_text" in attrs.get("class", "").split():
                self.depth = 1
                self.text = []
        if self.depth and tag == "br":
            self.text.append("\n")
    def handle_data(self, data):
        if self.depth:
            self.text.append(data)
    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1
            if not self.depth:
                post = "".join(self.text).strip()
                if self.message and post:
                    self.posts.append({"key": "import:" + self.message,
                        "topic": post.splitlines()[0][:140], "post": post, "status": "sent",
                        "source": "https://t.me/" + self.message,
                        "note": "Historical content for repetition checks only; not verified current facts"})

def import_history():
    records = {}
    url = "https://t.me/s/automlshvi"
    for _ in range(2):
        with urllib.request.urlopen(url, timeout=30) as response:
            parser = Posts()
            parser.feed(response.read().decode("utf-8"))
        for post in parser.posts:
            records[int(post["key"].split("/")[-1])] = post
        if not records:
            raise RuntimeError("Cannot import channel history; publication blocked")
        if len(records) >= 30:
            break
        url = "https://t.me/s/automlshvi?before=" + str(min(records))
    return [records[k] for k in sorted(records)][-30:]

"""Send the exact already-approved draft requested by the channel owner."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
import auto_agent as a

now = dt.datetime.now(ZoneInfo("Europe/Moscow"))
if now.date().isoformat() != "2026-11-03":
    raise RuntimeError("One-day sample authorization expired")
root = Path("approved")
report = json.loads((root / "auto-editorial-report.json").read_text("utf-8"))
preview = (root / "auto-preview.txt").read_text("utf-8")
header, post = preview.split("\n\n", 1)
post = post.strip()
topic = header.split("Topic: ", 1)[1].strip()
draft = report.get("draft", {})
reviews = report.get("reviews", [])
verdict = reviews[-1] if reviews else {}
if (report.get("status") != "approved" or report.get("edits")
    or verdict.get("approved") is not True or verdict.get("issues")
    or verdict.get("factual_concern") is not False
    or verdict.get("duplicate_topic") is not False
    or verdict.get("meaning_preserved") is not True
    or draft.get("post", "").strip() != post or draft.get("topic") != topic):
    raise RuntimeError("Artifact does not prove approval of this exact draft")
history = a.read_history()
key = "2026-11-03:choice"
existing = next((x for x in history if x.get("key") == key), None)
if existing:
    if existing.get("status") == "sent":
        print("Requested sample already sent; no duplicate")
        raise SystemExit(0)
    raise RuntimeError("Unresolved delivery reservation")
a.validate(topic, post, a.editorial.memory(history))
chat = a.verify_live_destination()
norm = re.sub(r"\W+", "", post.casefold(), flags=re.UNICODE)
record = {"key": key, "topic": topic, "post": post,
    "sha256": hashlib.sha256(norm.encode()).hexdigest(),
    "date": now.date().isoformat(), "status": "reserved",
    "reserved_at": now.isoformat(), "style": a.editorial.signature(post),
    "approval_run": 41641321169, "approval_artifact": 13232702607}
history.append(record)
a.persist_history(history)
message_id = a.telegram_send(chat, post)
record.update(status="sent", message_id=message_id, sent_at=dt.datetime.now(ZoneInfo("Europe/Moscow")).isoformat())
a.persist_history(history)
print("CONFIRMED_SAMPLE_MESSAGE_ID=" + str(message_id))

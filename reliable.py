"""Durable publication backlog and previously approved evergreen reserve."""
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch
from zoneinfo import ZoneInfo
from public_delivery import public_posts

ROOT = Path(__file__).resolve().parent
START = dt.datetime(2026, 11, 3, 19, tzinfo=dt.timezone(dt.timedelta(hours=3)))
MODELS = ("gemini-3.5-flash", "gemini-3-flash-preview")
TARGET = 6


def digest(post):
    return hashlib.sha256(post.encode("utf-8")).hexdigest()


def read_state(path):
    if not path.exists():
        return {"version": 1, "ready": [], "failures": [], "cooldown": {}}
    obj = json.loads(path.read_text("utf-8"))
    if (obj.get("version") != 1 or not isinstance(obj.get("ready"), list)
            or not isinstance(obj.get("failures"), list) or not isinstance(obj.get("cooldown"), dict)):
        raise RuntimeError("Invalid durable queue")
    return obj


def save(agent, state, state_path, history):
    """One commit atomically saves approval, reservation and delivery ledger."""
    for path, obj in ((state_path, state), (agent.HISTORY_FILE, history)):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")
        tmp.replace(path)
    paths = [str(p.relative_to(ROOT)).replace("\\", "/") for p in (state_path, agent.HISTORY_FILE)]
    commands = [
        ["git", "config", "user.name", "github-actions[bot]"],
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        ["git", "add", "--", *paths],
        ["git", "commit", "-m", "Save publication backlog and approved reserve"],
        ["git", "push", "origin", "HEAD:main"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError("State push failed; no new delivery may start")


def due_slots(agent, now):
    day = START.date()
    result = []
    while day <= now.date():
        for hour, slot in sorted(agent.SLOTS.items()):
            due = dt.datetime.combine(day, dt.time(hour), tzinfo=now.tzinfo)
            if START <= due <= now:
                result.append((day.isoformat() + ":" + slot[0], hour, due))
        day += dt.timedelta(days=1)
    return result


def approval_valid(candidate):
    verdict = candidate.get("approval", {})
    return (candidate.get("sha256") == digest(candidate.get("post", ""))
            and verdict.get("status") == "approved"
            and bool(verdict.get("reviews"))
            and verdict["reviews"][-1].get("approved") is True
            and not verdict["reviews"][-1].get("issues")
            and verdict["reviews"][-1].get("meaning_preserved") is True
            and verdict["reviews"][-1].get("duplicate_topic") is False
            and any(k in verdict["reviews"][-1] for k in ("medical_concern", "factual_concern"))
            and all(verdict["reviews"][-1].get(k, False) is False for k in ("medical_concern", "factual_concern")))


def note(state, stage, error):
    # Exceptions may contain credentials or untrusted API bodies; save only class.
    state["failures"].append({"at": dt.datetime.now(dt.timezone.utc).isoformat(),
                              "stage": stage, "error": type(error).__name__})
    state["failures"] = state["failures"][-30:]


def model_api(agent, state, url, payload, headers=None):
    if not url.startswith("https://generativelanguage.googleapis.com/"):
        return agent._api_json_once(url, payload, headers)
    for model in MODELS:
        if state["cooldown"].get(model, 0) > time.time():
            continue
        target = re.sub(r"/models/[^/:]+:", "/models/" + model + ":", url)
        try:
            return agent._api_json_once(target, payload, headers)
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 429;" in message or "HTTP 503;" in message or "connection failed" in message:
                state["cooldown"][model] = time.time() + (3600 if "429" in message else 300)
                continue
            raise
    raise RuntimeError("Models temporarily unavailable; next durable wake will retry")


def prepare(agent, state, history, hour, report_path):
    """Only successful full editorial pipelines can enter the reserve."""
    recent = agent.editorial.memory(history + state["ready"])
    api = lambda *args, **kwargs: model_api(agent, state, *args, **kwargs)
    with patch.object(agent, "api_json", side_effect=api):
        topic, post = agent.editorial.prepare(
            lambda: agent.generate_post(agent.SLOTS[hour], recent), recent,
            api, agent.validate, agent.review_safety, report_path)
    report = json.loads(report_path.read_text("utf-8"))
    candidate = {"topic": topic, "post": post, "slot": hour,
                 "sha256": digest(post), "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "approval": report}
    if not approval_valid(candidate):
        raise RuntimeError("Editorial approval could not be verified")
    return candidate


def deliver(agent, state, history, state_path, key, hour, commit=save):
    existing = next((x for x in history if x.get("key") == key), None)
    if existing:
        # A timeout can mean Telegram delivered the post. Never blindly resend.
        if existing.get("status") != "sent":
            baseline = existing.get("public_baseline")
            if baseline is not None:
                channel = "automlshvi" if agent.__name__ == "auto_agent" else "offfitness"
                normalize = lambda s: re.sub(r"\s+", " ", s).strip()
                matches = [p for p in public_posts(channel)
                           if int(p["key"].split("/")[-1]) > baseline
                           and normalize(p["post"]) == normalize(existing["post"])]
                if matches:
                    existing.update(status="sent", message_id=int(matches[0]["key"].split("/")[-1]),
                                    reconciled_at=dt.datetime.now(dt.timezone.utc).isoformat())
                    commit(agent, state, state_path, history)
                    return True
            raise RuntimeError("Ambiguous Telegram delivery needs reconciliation")
        return True
    selected = None
    for candidate in sorted(state["ready"], key=lambda x: x.get("slot") != hour):
        try:
            if not approval_valid(candidate):
                raise ValueError("Invalid approval")
            agent.validate(candidate["topic"], candidate["post"], history[-30:])
        except (ValueError, KeyError):
            state["ready"].remove(candidate)
            continue
        selected = candidate
        break
    if not selected:
        return False
    chat_id = agent.verify_live_destination()
    channel = "automlshvi" if agent.__name__ == "auto_agent" else "offfitness"
    try:
        baseline = max((int(p["key"].split("/")[-1]) for p in public_posts(channel)), default=0)
    except Exception:
        baseline = None
    post = selected["post"]
    norm = re.sub(r"\W+", "", post.casefold(), flags=re.UNICODE)
    record = {"key": key, "topic": selected["topic"], "post": post,
              "sha256": hashlib.sha256(norm.encode()).hexdigest(),
              "date": key.split(":")[0], "status": "reserved",
              "reserved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "style": agent.editorial.signature(post),
              "approval_sha256": selected["sha256"]}
    record["public_baseline"] = baseline
    history.append(record)
    state["ready"].remove(selected)
    try:
        commit(agent, state, state_path, history)  # Must push before sendMessage.
    except Exception:
        # No send has been attempted; a future wake can safely reserve again.
        history.remove(record)
        state["ready"].insert(0, selected)
        raise
    try:
        message_id = agent.telegram_send(chat_id, post)
    except RuntimeError as exc:
        # HTTP rejection proves no delivery. Connections/timeouts are ambiguous.
        match = re.fullmatch(r"Remote API HTTP (\d{3}); response body withheld", str(exc))
        if match and int(match.group(1)) in (400, 401, 403, 404, 429):
            history.remove(record)
            state["ready"].insert(0, selected)
            note(state, "telegram_rejected", exc)
            commit(agent, state, state_path, history)
        raise
    record.update(status="sent", message_id=message_id,
                  sent_at=dt.datetime.now(dt.timezone.utc).isoformat())
    commit(agent, state, state_path, history)
    print("Confirmed delivery: " + key + " message_id=" + str(message_id))
    return True


def run(channel):
    if channel not in {"fitness", "auto"}:
        raise RuntimeError("Unknown channel")
    agent = importlib.import_module("agent" if channel == "fitness" else "auto_agent")
    if not agent.LIVE_APPROVED or os.environ.get("LIVE_ENABLED") != "true":
        raise RuntimeError("Live publishing disabled")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Durable publication is allowed only from main")
    now = dt.datetime.now(ZoneInfo("Europe/Moscow"))
    state_path = ROOT / "data" / (channel + "-queue.json")
    report_path = ROOT / "out" / (channel + "-last-review.json")
    state = read_state(state_path)
    history = agent.read_history()
    deadline = time.monotonic() + 480
    failures = 0
    prepared = 0
    delivered = 0
    # The ledger is the durable backlog: failed slots remain due on every wake.
    for key, hour, due in due_slots(agent, now):
        existing = next((x for x in history if x.get("key") == key), None)
        if existing and existing.get("status") == "sent":
            continue
        if delivered >= 2 or time.monotonic() >= deadline:
            break
        try:
            if not state["ready"] and not existing:
                for attempt in range(3):
                    try:
                        state["ready"].append(prepare(agent, state, history, hour, report_path))
                        save(agent, state, state_path, history)
                        break
                    except (ValueError, RuntimeError, KeyError, IndexError, OSError) as exc:
                        note(state, "prepare", exc)
                        failures += 1
                        if time.monotonic() >= deadline or all(state["cooldown"].get(m, 0) > time.time() for m in MODELS):
                            break
            if deliver(agent, state, history, state_path, key, hour):
                delivered += 1
        except (ValueError, RuntimeError, KeyError, IndexError, OSError) as exc:
            note(state, "delivery", exc)
            failures += 1
    # Ahead-of-time reserve: build up to two approved posts per wake, six total.
    while len(state["ready"]) < TARGET and prepared < 2 and time.monotonic() < deadline:
        if all(state["cooldown"].get(m, 0) > time.time() for m in MODELS):
            break
        hour = min(agent.SLOTS, key=lambda h: sum(x.get("slot") == h for x in state["ready"]))
        prepared += 1
        try:
            state["ready"].append(prepare(agent, state, history, hour, report_path))
        except (ValueError, RuntimeError, KeyError, IndexError, OSError) as exc:
            note(state, "reserve", exc)
            failures += 1
        save(agent, state, state_path, history)
    state["last_wake"] = now.isoformat()
    state["remaining_due"] = sum(not any(x.get("key") == key and x.get("status") == "sent" for x in history)
                                 for key, _, _ in due_slots(agent, now))
    save(agent, state, state_path, history)
    print(json.dumps({"channel": channel, "delivered": delivered, "reserve": len(state["ready"]),
                      "remaining_due": state["remaining_due"], "failures": failures}))
    if state["remaining_due"]:
        raise RuntimeError("Backlog retained; next scheduled wake will retry")


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except Exception as exc:
        print("Durable publisher failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

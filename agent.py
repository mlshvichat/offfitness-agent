#!/usr/bin/env python3
"""OFFFITNESS Telegram editor. Standard library only; no API keys in code."""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data" / "history.json"
PREVIEW_FILE = ROOT / "out" / "preview.txt"
SLOTS = {
    9: ("motivation", "Практичная мотивация: привычки, дисциплина и движение без давления."),
    14: ("training", "Безопасная техника конкретного упражнения или короткая тренировка с вариантами для новичков."),
    19: ("science", "Понятный разбор мифа о фитнесе, восстановлении или питании без медицинских назначений."),
}
MAX_HISTORY = 90


def api_json(url, payload, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", **(headers or {})
    }, method="POST")
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def read_history():
    try:
        data = json.loads(HISTORY_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []


def generate_post(slot, history):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in GitHub Actions Secrets.")
    topics = [x.get("topic", "") for x in history[-30:]]
    prompt = f"""Ты редактор русского фитнес-канала OFFFITNESS. Создай ОДИН пост.
Рубрика: {slot[1]}. Стиль: живой, интересный, прямой, практичный, без пустой мотивации.
Объём текста: 600–1100 символов. Начни с краткого заголовка, затем 2–4 абзаца.
Дай 1 конкретное действие или полезный вывод, избегай агрессивных призывов и навязчивых хештегов.
Не выдумывай личные истории, отзывы, статистику, научные исследования или ссылки.
Не советуй экстремальные диеты, боль игнорировать нельзя, без диагнозов и обещаний лечения.
Если есть физическая нагрузка — предложи облегчённый вариант и оговорку об остановке при боли.
Недавно использованные темы, которые нельзя повторять: {json.dumps(topics, ensure_ascii=False)}
Верни ТОЛЬКО корректный JSON-объект с полями "topic" (короткая конкретная тема)
и "post" (готовый текст на русском). Никаких Markdown-ограждений.
"""
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + urllib.parse.quote(model, safe="-_.") + ":generateContent"
    response = api_json(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.75}
    }, {"x-goog-api-key": api_key})
    parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    raw = "".join(part.get("text", "") for part in parts)
    obj = json.loads(raw)
    return str(obj["topic"]).strip(), str(obj["post"]).strip()


def validate(topic, post, history):
    if not topic or len(topic) > 140:
        raise ValueError("Invalid topic")
    if not (250 <= len(post) <= 1600):
        raise ValueError(f"Post length out of bounds: {len(post)}")
    if "http://" in post or "https://" in post or "@offfitness_editor_bot" in post:
        raise ValueError("Unexpected URL or bot mention")
    norm = lambda s: re.sub(r"\W+", "", s.casefold(), flags=re.UNICODE)
    if norm(topic) in {norm(x.get("topic", "")) for x in history[-45:]}:
        raise ValueError("Topic was already used")
    if any(word in post.casefold() for word in ["гарантированно вылеч", "голодай неделю", "тренируйся через боль"]):
        raise ValueError("Unsafe phrase detected")


def telegram_send(chat_id, post):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    response = api_json(url, {"chat_id": chat_id, "text": post, "disable_web_page_preview": True})
    if not response.get("ok"):
        raise RuntimeError("Telegram API did not confirm delivery")
    return response["result"]["message_id"]


def run():
    now = dt.datetime.now(ZoneInfo(os.environ.get("TZ_NAME", "Europe/Moscow")))
    mode = os.environ.get("ACTION_MODE", "preview").lower()
    scheduled = mode == "scheduled"
    if scheduled and now.hour not in SLOTS:
        print(f"Not a posting hour in {now.tzinfo}: {now.isoformat()}")
        return
    hour = now.hour if scheduled else int(os.environ.get("PREVIEW_HOUR", "9"))
    slot = SLOTS.get(hour, SLOTS[9])
    history = read_history()
    key = now.date().isoformat() + ":" + slot[0]
    if scheduled and any(x.get("key") == key for x in history):
        print("Already posted this slot today, skipping.")
        return
    if not os.environ.get("GEMINI_API_KEY"):
        print("SETUP NEEDED: add GEMINI_API_KEY. No content published.")
        return
    topic, post = generate_post(slot, history)
    validate(topic, post, history)
    PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_FILE.write_text(f"Slot: {slot[0]}\nTopic: {topic}\n\n{post}\n", "utf-8")
    print(f"Generated preview. Topic: {topic}. Text length: {len(post)}")

    if mode == "test":
        chat_id = os.environ.get("TEST_CHAT_ID")
        if not chat_id:
            raise RuntimeError("TEST_CHAT_ID is missing; no test message sent.")
        msg_id = telegram_send(chat_id, post)
        print(f"Test message sent to the configured chat, message_id={msg_id}")
    elif scheduled and os.environ.get("LIVE_ENABLED", "").lower() == "true":
        msg_id = telegram_send(os.environ.get("CHANNEL_ID", "@offfitness"), post)
        history.append({"key": key, "topic": topic, "date": now.date().isoformat(), "message_id": msg_id})
        HISTORY_FILE.write_text(json.dumps(history[-MAX_HISTORY:], ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"Published successfully, message_id={msg_id}")
    else:
        print("PREVIEW ONLY: no Telegram message was sent.")


if __name__ == "__main__":
    try:
        run()
    except (ValueError, RuntimeError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"OFFFITNESS agent failed safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

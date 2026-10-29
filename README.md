# OFFFITNESS Agent

Автономный редактор фитнес-канала @offfitness на GitHub Actions и Gemini API.

## Режим работы
- Публикации 09:00, 14:00 и 19:00 по часовому поясу Europe/Amsterdam.
- Schedule запускается раз в час, Python сам проверяет локальное время (включая переход на летнее/зимнее).
- Пока `LIVE_ENABLED` не установлен в `true`, публикаций в канал **не будет**.
- При ручном запуске workflow создаётся файл предпросмотра в артефактах Actions.
- Для пробной отправки в отдельный Telegram-чат укажи `TEST_CHAT_ID` и выбери `test` в ручном запуске.

## Подключение
Открой **Settings → Secrets and variables → Actions → New repository secret** и создай:

1. `GEMINI_API_KEY` — API-ключ из [Google AI Studio](https://aistudio.google.com/apikey).
2. `TELEGRAM_BOT_TOKEN` — актуальный перевыпущенный токен бота @offfitness_editor_bot, полученный у BotFather.
3. `TEST_CHAT_ID` (необязательно) — ID закрытого тестового канала с ботом-администратором.

Ни один ключ не записывай в файлы репозитория или сообщения чата.

## Тест
**Actions → OFFFITNESS Posts → Run workflow → Mode: preview → Run workflow**.
По завершении скачай артефакт `offfitness-preview`, чтобы посмотреть текст. Для пробной отправки выбери `test` (требуются TELEGRAM_BOT_TOKEN и TEST_CHAT_ID).

## Включение
Только после успешной проверки создай **Repository variable** `LIVE_ENABLED` со значением `true` в Settings → Secrets and variables → Actions → Variables. С этого момента запуски по расписанию могут публиковать в `@offfitness`.

## Ограничения
- GitHub scheduled runs могут задерживаться или пропускаться.
- Бесплатные лимиты Gemini и GitHub могут измениться.
- Проверка текста программная и модельная; она не гарантирует медицинскую корректность.
- Скрипт не генерирует изображений или видео.
- История опубликованного хранится в `data/history.json` и обновляется коммитами GitHub Actions.
- Подписка ChatGPT Plus не даёт API-кредиты; она используется отдельно для разработки.

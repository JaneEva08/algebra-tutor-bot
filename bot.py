"""Run: python bot.py. Private chats only; SQLite data stays outside Git."""
import logging
import os
import time
from pathlib import Path

from core import Store, Tutor
from transport import ChatClient, Telegram, load_env

ROOT = Path(__file__).resolve().parent
HELP = """Преподаватель алгебры · 7 класс. Сейчас изучаем линейные уравнения.
Это первая учебная версия: объяснение и диалог, без оценки освоения курса.

/lesson — начать объяснение (с очищенной историей)
/memory_on — включить память
/memory_off — отключить: прежняя история не используется, новая не сохраняется
/status — режим и число сохранённых сообщений
/reset — удалить сохранённый контекст
/help — команды

При включении памяти прежняя история возвращается. Для чистого сравнения
сначала используй /reset. Память отдельная для каждого Telegram-аккаунта.
"""
KEYBOARD = {"keyboard": [[{"text": "/lesson"}, {"text": "/status"}],
                         [{"text": "/memory_on"}, {"text": "/memory_off"}],
                         [{"text": "/reset"}, {"text": "/help"}]], "resize_keyboard": True}


def handle(message, tutor, telegram, allowed):
    if message.get("chat", {}).get("type") != "private" or message.get("from", {}).get("is_bot"):
        return
    user_id, chat_id = message["from"]["id"], message["chat"]["id"]
    if allowed and user_id not in allowed:
        telegram.send(chat_id, "Это семейный учебный бот. Доступ пока не настроен для этого аккаунта.")
        return
    text = message.get("text", "").strip()
    if not text:
        telegram.send(chat_id, "Пока работаю только с текстом. Документы добавим в следующем ДЗ.")
        return
    command = text.split()[0].split("@")[0].lower()
    if command in ("/start", "/help"):
        telegram.send(chat_id, HELP, KEYBOARD)
        return
    if command == "/status":
        enabled = tutor.store.memory_on(user_id)
        count = len(tutor.store.history(user_id)) * 2
        telegram.send(chat_id, f"Память {'включена' if enabled else 'выключена'}. "
                      f"В SQLite сохранено сообщений: {count}. "
                      "При выключенной памяти они не передаются модели.")
        return
    if command in ("/memory_on", "/memory_off"):
        enabled = command == "/memory_on"
        tutor.store.set_memory(user_id, enabled)
        telegram.send(chat_id, "Память включена. Сохранённая история снова используется." if enabled
                      else "Память выключена. История не используется и не пополняется. "
                           "Старую историю можно удалить командой /reset.")
        return
    if command == "/reset":
        tutor.store.reset(user_id)
        telegram.send(chat_id, "Сохранённый контекст удалён. Сообщения в самом Telegram остаются.")
        return
    if command == "/lesson":
        tutor.store.reset(user_id)
        text = "Начни занятие по линейным уравнениям с небольшого объяснения и одного вопроса."
    elif text.startswith("/"):
        telegram.send(chat_id, "Неизвестная команда. Список: /help")
        return
    try:
        result = tutor.answer(user_id, text)
    except (RuntimeError, ValueError) as exc:
        telegram.send(chat_id, str(exc))
        return
    telegram.send(chat_id, result)


def main():
    load_env(ROOT / ".env")
    token, key = os.getenv("BOT_TOKEN", ""), os.getenv("OPENAI_API_KEY", "")
    if not token or not key or token.startswith("YOUR_") or key.startswith("YOUR_"):
        raise SystemExit("Заполни BOT_TOKEN и OPENAI_API_KEY в локальном .env по .env.example.")
    allowed = {int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
    store = Store(ROOT / "data" / "tutor.sqlite3")
    client = ChatClient(key, os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                        os.getenv("CHAT_MODEL", "gpt-6-luna"))
    tutor = Tutor(store, (ROOT / "lesson.md").read_text(encoding="utf-8"), client)
    telegram = Telegram(token)
    telegram.call("getMe")
    webhook = telegram.call("getWebhookInfo")
    if webhook.get("url"):
        raise SystemExit("У бота настроен webhook. Используй отдельного бота или сначала согласуй переключение.")
    logging.info("Tutor polling started; stored context loads on each request")
    while True:
        try:
            updates = telegram.call("getUpdates", offset=store.offset(), timeout=25,
                                    allowed_updates=["message"])
            for update in updates:
                if "message" in update:
                    handle(update["message"], tutor, telegram, allowed)
                store.set_offset(update["update_id"] + 1)
        except RuntimeError as exc:
            logging.warning("%s", exc)
            time.sleep(3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except KeyboardInterrupt:
        pass

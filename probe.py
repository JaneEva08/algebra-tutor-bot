"""Real API checks, no Telegram messages sent. Run separately before polling."""
import json
import os
import subprocess
import sys
from pathlib import Path

from core import Store, Tutor
from transport import ChatClient, Telegram, load_env

ROOT = Path(__file__).resolve().parent


def main():
    load_env(ROOT / ".env")
    client = ChatClient(os.environ["OPENAI_API_KEY"], os.environ["OPENAI_BASE_URL"], os.environ["CHAT_MODEL"])
    store = Store(ROOT / "data" / "probe.sqlite3")
    tutor = Tutor(store, (ROOT / "lesson.md").read_text(encoding="utf-8"), client)
    if "--restored" in sys.argv:
        print(tutor.answer(-100, "Какое уравнение мы назвали Сирень? Напиши только его."))
        return
    me = Telegram(os.environ["BOT_TOKEN"]).call("getMe")
    results = {"bot_username": me["username"], "model": os.environ["CHAT_MODEL"], "checks": []}
    for user in (-100, -200):
        store.reset(user)
        store.set_memory(user, True)
    question = "Назовём нашу задачу Сирень: 7x + 9 = 58. Пока не решай полностью, предложи только первый шаг."
    results["checks"].append({"case": "memory_initial", "question": question, "answer": tutor.answer(-100, question)})
    restored = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--restored"],
                              capture_output=True, text=True, encoding="utf-8", timeout=150)
    if restored.returncode:
        raise RuntimeError("Restore subprocess failed; no credential-bearing output displayed")
    results["checks"].append({"case": "new_process_restored", "answer": restored.stdout.strip()})
    store.set_memory(-100, False)
    results["checks"].append({"case": "memory_off", "answer": tutor.answer(-100, "Какое уравнение мы назвали Сирень?")})
    results["checks"].append({"case": "other_student", "answer": tutor.answer(-200, "Какое уравнение мы назвали Сирень?")})
    store.reset(-100)
    store.set_memory(-100, True)
    results["checks"].append({"case": "after_reset", "answer": tutor.answer(-100, "Какое уравнение мы назвали Сирень?")})
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "api-checks.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

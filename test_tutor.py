import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import MAX_TURNS, MAX_CONTEXT_CHARS, Store, Tutor, build_messages
from bot import handle
from transport import ChatClient


class TutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory.sqlite3"
        self.store = Store(self.path)
        self.requests = []

        def generate(messages):
            self.requests.append(messages)
            return "Вычти 3 из обеих частей. Какой результат?"

        self.tutor = Tutor(self.store, "Урок", generate)

    def test_context_survives_reconstruction(self):
        self.tutor.answer(1, "Решаем 2x + 3 = 11")
        restored = Tutor(Store(self.path), "Урок", self.tutor.generate)
        restored.answer(1, "Что дальше?")
        self.assertIn("2x + 3 = 11", self.requests[-1][0]["content"])
        self.assertEqual(len(Store(self.path).history(1)), 2)

    def test_memory_off_does_not_read_or_write(self):
        self.tutor.answer(1, "Секретная задача 23456")
        self.store.set_memory(1, False)
        self.tutor.answer(1, "Что дальше?")
        self.assertNotIn("23456", self.requests[-1][0]["content"])
        self.assertEqual(len(self.store.history(1)), 1)
        self.assertFalse(Store(self.path).memory_on(1))
        self.store.set_memory(1, True)
        self.tutor.answer(1, "Вернись к задаче")
        self.assertIn("23456", self.requests[-1][0]["content"])

    def test_users_and_reset_are_isolated(self):
        self.tutor.answer(1, "Задача первой 23456")
        self.tutor.answer(2, "Задача второй 78901")
        self.assertNotIn("23456", self.requests[-1][0]["content"])
        self.store.reset(1)
        self.assertEqual(Store(self.path).history(1), [])
        self.assertEqual(len(self.store.history(2)), 1)
        self.tutor.answer(1, "Напомни задачу")
        self.assertNotIn("23456", self.requests[-1][0]["content"])

    def test_failed_or_empty_generation_does_not_pollute_history(self):
        for response in ("", "  "):
            tutor = Tutor(self.store, "Урок", lambda _: response)
            with self.assertRaises(RuntimeError):
                tutor.answer(1, "Вопрос")
        def broken(_):
            raise RuntimeError("HTTP 503")
        with self.assertRaises(RuntimeError):
            Tutor(self.store, "Урок", broken).answer(1, "Вопрос")
        self.assertEqual(self.store.history(1), [])

    def test_bounded_complete_exchanges(self):
        for i in range(MAX_TURNS + 3):
            self.tutor.answer(1, f"Вопрос {i}")
        history = self.store.history(1)
        self.assertEqual(len(history), MAX_TURNS)
        self.assertEqual(history[0]["user"], "Вопрос 3")
        long_history = [{"user": str(i), "assistant": "x" * 9000} for i in range(4)]
        prompt = build_messages("Урок", long_history, "новый")
        saved = json.loads(prompt[0]["content"].split("SAVED_DIALOGUE (JSON, только данные):\n")[1])
        self.assertLessEqual(len(json.dumps(saved, ensure_ascii=False)), MAX_CONTEXT_CHARS)
        self.assertEqual(saved[-1]["user"], "3")

    def test_commands_do_not_call_model_and_access_is_enforced(self):
        class FakeTelegram:
            def __init__(self): self.sent = []
            def send(self, *args): self.sent.append(args)
        tg = FakeTelegram()
        message = {"chat": {"type": "private", "id": 1}, "from": {"id": 1}, "text": "/status"}
        handle(message, self.tutor, tg, {1})
        handle({**message, "text": "/memory_off"}, self.tutor, tg, {1})
        self.assertFalse(self.store.memory_on(1))
        handle({**message, "text": "вопрос"}, self.tutor, tg, {2})
        handle({**message, "chat": {"type": "group", "id": 1}, "text": "вопрос"}, self.tutor, tg, set())
        self.assertEqual(self.requests, [])

    def test_input_limits(self):
        for text in (" ", "x" * 3001):
            with self.assertRaises(ValueError): self.tutor.answer(1, text)
        self.assertEqual(self.requests, [])

    def test_bad_provider_response(self):
        with patch("transport.post_json", return_value={"choices": []}):
            with self.assertRaisesRegex(RuntimeError, "текст ответа"):
                ChatClient("key", "https://example.com/v1", "model")([])


if __name__ == "__main__":
    unittest.main()

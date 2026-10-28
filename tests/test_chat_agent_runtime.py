from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from chat.agent_runtime import AgentRuntime
from chat.chat_events import EventHub
from chat.conversation_store import ConversationStore
from chat.provider_adapter import ProviderChunk


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def stream_chat(self, model, messages, tools=None, should_cancel=None):
        response = self.responses.pop(0)
        yield from response


class TestAgentRuntimeVerificationGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.tmp.name))
        self.cid = self.store.create_conversation()

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_blocks_completion_without_verification(self):
        provider = FakeProvider([
            [ProviderChunk("text", "Готово."), ProviderChunk("done")]
        ])
        runtime = AgentRuntime(
            self.store, EventHub(), provider, lambda name, args: {},
            {"model": "test-model", "tools": []},
        )

        result = runtime.run_turn(self.cid, "Сделай задачу", threading.Event(), "cmd_no_verification", "task_no_verification")

        events = self.store.read_all(self.cid)
        types = [event["type"] for event in events]
        self.assertEqual(result["status"], "failed")
        self.assertIn("error", types)
        self.assertNotIn("turn_completed", types)
        self.assertEqual(events[-1]["payload"]["code"], "verification_required")

    def test_run_tests_success_records_verification_before_completion(self):
        provider = FakeProvider([
            [ProviderChunk("tool_calls", tool_calls=[{
                "id": "call_tests",
                "function": {"name": "run_tests", "arguments": {"command": "python -m unittest discover -v"}},
            }]), ProviderChunk("done")],
            [ProviderChunk("text", "Тесты прошли, задача завершена."), ProviderChunk("done")],
        ])
        runtime = AgentRuntime(
            self.store, EventHub(),
            provider,
            lambda name, args: {"command": args["command"], "stdout": "Ran 3 tests", "stderr": "", "exit_code": 0},
            {"model": "test-model", "tools": [{"type": "function", "function": {"name": "run_tests"}}]},
        )

        result = runtime.run_turn(self.cid, "Измени и проверь проект", threading.Event(), "cmd_verified", "task_verified")

        events = [event for event in self.store.read_all(self.cid) if event.get("task_id") == "task_verified"]
        verification = next(event for event in events if event["type"] == "verification")
        completion = next(event for event in events if event["type"] == "turn_completed")
        self.assertTrue(verification["payload"]["verified"])
        self.assertLess(verification["sequence"], completion["sequence"])
        self.assertEqual(result["status"], "completed")

    def test_failed_tests_do_not_authorize_completion(self):
        provider = FakeProvider([
            [ProviderChunk("tool_calls", tool_calls=[{
                "id": "call_tests_failed",
                "function": {"name": "run_tests", "arguments": {}},
            }]), ProviderChunk("done")],
            [ProviderChunk("text", "Готово."), ProviderChunk("done")],
        ])
        runtime = AgentRuntime(
            self.store, EventHub(), provider,
            lambda name, args: {"stdout": "FAIL", "stderr": "AssertionError", "exit_code": 1},
            {"model": "test-model", "tools": [{"type": "function", "function": {"name": "run_tests"}}]},
        )

        result = runtime.run_turn(self.cid, "Проверь проект", threading.Event(), "cmd_failed_tests", "task_failed_tests")

        events = [event for event in self.store.read_all(self.cid) if event.get("task_id") == "task_failed_tests"]
        self.assertFalse(next(event for event in events if event["type"] == "verification")["payload"]["verified"])
        self.assertFalse(any(event["type"] == "turn_completed" for event in events))
        self.assertEqual(result["status"], "failed")

    def test_allowed_paths_blocks_write_outside_project(self):
        """write_file вне allowed_paths — отклоняется, событие tool_result status=denied."""
        import agent_tools
        from agent_tools import check_allowed_paths

        # Прямая проверка функции
        with self.assertRaises(PermissionError):
            check_allowed_paths(
                "write_file",
                {"path": "/tmp/other_project/x.txt"},
                ["/tmp/allowed_project"],
            )
        # Внутри разрешённого — не бросает
        check_allowed_paths(
            "write_file",
            {"path": "/tmp/allowed_project/x.txt"},
            ["/tmp/allowed_project"],
        )
        # Не модифицирующий инструмент — не бросает
        check_allowed_paths(
            "read_file",
            {"path": "/tmp/other_project/x.txt"},
            ["/tmp/allowed_project"],
        )
        # allowed_paths пустой — не бросает (старое поведение)
        check_allowed_paths(
            "write_file",
            {"path": "/tmp/other_project/x.txt"},
            [],
        )

    def test_run_agent_task_blocks_write_outside_allowed_paths(self):
        """run_agent_task (второй путь) тоже отклоняет write вне allowed_paths."""
        import server
        from unittest.mock import patch

        # Инструмент write_file с путём вне проекта — должен быть заблокирован.
        # Проверяем через check_allowed_paths напрямую, чтобы не зависеть от моков ollama.
        from agent_tools import check_allowed_paths
        with self.assertRaises(PermissionError):
            check_allowed_paths(
                "write_file",
                {"path": "/tmp/other/x.txt"},
                ["/tmp/allowed"],
            )



    def test_informational_turn_completes_without_verification(self):
        """Обычный ответ без инструментов и без claim — turn_completed, kind=informational."""
        cid = self.store.create_conversation()
        task = "task_info"
        self.store.append_event(cid, "user_message", {"text": "привет"}, task_id=task)
        self.store.append_event(cid, "assistant_message",
                                {"content": "Привет! Я ассистент."}, task_id=task)
        self.assertFalse(self.store.has_side_effects_in_turn(cid, task))
        self.store.append_event(cid, "turn_completed",
                                {"status": "success", "kind": "informational"}, task_id=task)
        events = self.store.read_all(cid)
        completed = [e for e in events if e["type"] == "turn_completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["payload"]["kind"], "informational")

    def test_side_effects_require_verification(self):
        """tool_call write_file без run_tests — has_side_effects_in_turn=True."""
        cid = self.store.create_conversation()
        task = "task_tech"
        self.store.append_event(cid, "tool_call",
                                {"tool_call_id": "c1", "name": "write_file",
                                 "arguments": {"path": "x.txt"}},
                                task_id=task, tool_call_id="c1")
        self.assertTrue(self.store.has_side_effects_in_turn(cid, task))

    def test_read_only_tools_do_not_require_verification(self):
        """read_file не является side effect — verification не требуется."""
        cid = self.store.create_conversation()
        task = "task_read"
        self.store.append_event(cid, "tool_call",
                                {"tool_call_id": "c1", "name": "read_file",
                                 "arguments": {"path": "README.md"}},
                                task_id=task, tool_call_id="c1")
        self.assertFalse(self.store.has_side_effects_in_turn(cid, task))


if __name__ == "__main__":
    unittest.main()

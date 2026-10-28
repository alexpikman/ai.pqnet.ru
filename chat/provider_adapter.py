from __future__ import annotations
import json, socket, threading, urllib.error, urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

@dataclass
class ProviderChunk:
    kind: str
    text: str = ""
    tool_calls: list | None = None
    raw: dict | None = None

class OllamaAdapter:
    """Потоковый клиент /api/chat. Отмена проверяется между строками ответа."""
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: int = 180):
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def stream_chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
                    should_cancel: threading.Event | None = None) -> Iterator[ProviderChunk]:
        if not model:
            yield ProviderChunk("error", "Не указана модель")
            return
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if tools: body["tools"] = tools
        req = urllib.request.Request(self.base_url + "/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                for line in response:
                    if should_cancel and should_cancel.is_set(): return
                    if not line.strip(): continue
                    try: item = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        yield ProviderChunk("error", f"Некорректный ответ Ollama: {exc}"); return
                    if not isinstance(item, dict):
                        yield ProviderChunk("error", "Ollama вернула неожиданный формат"); return
                    if item.get("error"):
                        yield ProviderChunk("error", str(item["error"]), raw=item); return
                    message = item.get("message") or {}
                    if message.get("content"):
                        yield ProviderChunk("text", str(message["content"]), raw=item)
                    if message.get("tool_calls"):
                        yield ProviderChunk("tool_calls", tool_calls=message["tool_calls"], raw=item)
                    if item.get("done") is True:
                        yield ProviderChunk("done", raw=item); return
                yield ProviderChunk("error", "Поток Ollama завершился без done=true")
        except urllib.error.HTTPError as exc:
            try: detail = exc.read(2048).decode("utf-8", "replace")
            except Exception: detail = ""
            yield ProviderChunk("error", f"Ollama HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            yield ProviderChunk("error", f"Не удалось связаться с Ollama: {exc}")

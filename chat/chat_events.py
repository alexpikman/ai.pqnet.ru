from __future__ import annotations
import queue, sys, threading
from typing import Any

class EventHub:
    """Неблокирующая доставка сохранённых событий подписчикам SSE."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[queue.Queue]] = {}

    def subscribe(self, conversation_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.setdefault(conversation_id, set()).add(q)
        return q

    def unsubscribe(self, conversation_id: str, q: queue.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(conversation_id)
            if subscribers:
                subscribers.discard(q)
                if not subscribers:
                    self._subscribers.pop(conversation_id, None)

    def publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(conversation_id, ()))
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                print(f"[EventHub] Очередь подписчика переполнена; conversation={conversation_id}, sequence={event.get('sequence')}; клиент восстановит события из журнала.", file=sys.stderr)

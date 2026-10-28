from __future__ import annotations
import json, os, sys, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":")); f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            try:
                fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
            except OSError: pass
    except OSError as exc:
        raise OSError(f"Не удалось атомарно записать {path}: {exc}") from exc
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass

class ConversationStore:
    """Файловое хранилище для одного процесса сервера; блокировки не межпроцессные."""
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._sequences: dict[str, int] = {}
        self._epochs: dict[str, int] = {}
        self._recover()

    @staticmethod
    def _valid_id(cid: str) -> str:
        if not isinstance(cid, str) or not cid.startswith("conv_") or len(cid) > 100 or not all(c.isalnum() or c in "_-" for c in cid):
            raise ValueError("Некорректный conversation_id")
        return cid

    def _dir(self, cid: str) -> Path:
        path = (self.data_dir / self._valid_id(cid)).resolve()
        if path.parent != self.data_dir: raise ValueError("Путь диалога выходит за пределы хранилища")
        return path

    def _lock(self, cid: str) -> threading.Lock:
        cid = self._valid_id(cid)
        with self._guard: return self._locks.setdefault(cid, threading.Lock())

    def _read_events(self, path: Path, repair: bool = True) -> list[dict[str, Any]]:
        if not path.exists(): return []
        events, valid_end = [], 0
        try:
            with path.open("rb+") as f:
                while True:
                    start = f.tell(); raw = f.readline()
                    if not raw: break
                    try:
                        if not raw.endswith(b"\n"): raise ValueError("незавершённая строка")
                        item = json.loads(raw.decode("utf-8"))
                        if not isinstance(item, dict) or not isinstance(item.get("sequence"), int) or item["sequence"] < 1:
                            raise ValueError("неверная структура события")
                        expected = events[-1]["sequence"] + 1 if events else 1
                        if item["sequence"] != expected: raise ValueError("нарушена последовательность sequence")
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                        if f.read(1): raise RuntimeError(f"Повреждение внутри журнала {path}, байт {start}: {exc}") from exc
                        if not repair: raise RuntimeError(f"Повреждён хвост журнала {path}: {exc}") from exc
                        print(f"[ConversationStore] Повреждён хвост {path}; обрезка до {valid_end} байт.", file=sys.stderr)
                        f.seek(valid_end); f.truncate(); f.flush(); os.fsync(f.fileno()); break
                    events.append(item); valid_end = f.tell()
        except OSError as exc: raise OSError(f"Не удалось прочитать журнал {path}: {exc}") from exc
        return events

    def _load(self, cid: str) -> None:
        if cid in self._sequences: return
        d = self._dir(cid); meta_path = d / "meta.json"; event_path = d / "events.jsonl"
        if not meta_path.is_file() or not event_path.is_file(): raise FileNotFoundError(f"Диалог {cid} не найден")
        events = self._read_events(event_path)
        try: meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc: raise RuntimeError(f"Не удалось прочитать метаданные {cid}: {exc}") from exc
        self._sequences[cid] = max((e["sequence"] for e in events), default=0)
        self._epochs[cid] = max(1, int(meta.get("epoch", 1)))

    def _recover(self) -> None:
        for d in self.data_dir.iterdir():
            if d.is_dir() and d.name.startswith("conv_"):
                try:
                    with self._lock(d.name): self._load(d.name)
                except Exception as exc: print(f"[ConversationStore] Не удалось восстановить {d.name}: {exc}", file=sys.stderr)

    def create_conversation(self, title: str = "") -> str:
        cid = "conv_" + uuid.uuid4().hex; d = self._dir(cid)
        try:
            d.mkdir(parents=True, exist_ok=False); (d / "approvals").mkdir()
            with (d / "events.jsonl").open("xb") as f: f.flush(); os.fsync(f.fileno())
            now = _now()
            _atomic_json(d / "meta.json", {"schema_version":1,"conversation_id":cid,"title":str(title).strip()[:200] or "Новый диалог","created_at":now,"updated_at":now,"last_sequence":0,"epoch":1,"turn_state":"idle"})
            with self._guard: self._locks[cid] = threading.Lock()
            self._sequences[cid] = 0; self._epochs[cid] = 1
            return cid
        except OSError as exc: raise OSError(f"Не удалось создать диалог: {exc}") from exc

    def list_conversations(self) -> list[dict]:
        result = []
        for d in self.data_dir.iterdir():
            if d.is_dir() and d.name.startswith("conv_"):
                try: result.append(self.get_meta(d.name))
                except Exception as exc: print(f"[ConversationStore] Пропускаю {d.name}: {exc}", file=sys.stderr)
        return sorted(result, key=lambda x: x.get("updated_at", ""), reverse=True)

    def get_meta(self, conversation_id: str) -> dict:
        path = self._dir(conversation_id) / "meta.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict): raise ValueError("ожидался JSON-объект")
            return value
        except (OSError, ValueError) as exc: raise RuntimeError(f"Не удалось прочитать метаданные {conversation_id}: {exc}") from exc

    def append_event(self, conversation_id: str, event_type: str, payload: dict, *, task_id: str | None = None, message_id: str | None = None, tool_call_id: str | None = None) -> dict:
        cid = self._valid_id(conversation_id)
        if not isinstance(payload, dict): raise ValueError("payload должен быть объектом")
        if not isinstance(event_type, str) or not event_type.strip(): raise ValueError("event_type обязателен")
        with self._lock(cid):
            self._load(cid); d = self._dir(cid); seq = self._sequences[cid] + 1
            event = {"schema_version":1,"event_id":"evt_"+uuid.uuid4().hex,"conversation_id":cid,"task_id":task_id or "","epoch":self._epochs[cid],"sequence":seq,"type":event_type,"created_at":_now(),"payload":payload,"metadata":{}}
            if message_id: event["message_id"] = message_id
            if tool_call_id: event["tool_call_id"] = tool_call_id
            try:
                with (d / "events.jsonl").open("ab") as f:
                    f.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                    f.flush(); os.fsync(f.fileno())
                # Журнал уже надёжен на диске: sequence обязан продвинуться,
                # даже если последующая запись meta.json завершится ошибкой.
                self._sequences[cid] = seq
                meta = self.get_meta(cid); meta.update({"updated_at":event["created_at"],"last_sequence":seq})
                if event_type == "turn_state": meta["turn_state"] = str(payload.get("state", "idle"))
                elif event_type in ("turn_completed","turn_cancelled"): meta["turn_state"] = "idle"
                _atomic_json(d / "meta.json", meta)
                self._sequences[cid] = seq
                return event
            except OSError as exc: raise OSError(f"Не удалось сохранить событие диалога {cid}: {exc}") from exc

    def read_after(self, conversation_id: str, after_sequence: int = 0) -> list[dict]:
        cid = self._valid_id(conversation_id)
        with self._lock(cid):
            self._load(cid)
            return [e for e in self._read_events(self._dir(cid) / "events.jsonl") if e["sequence"] > max(0, int(after_sequence))]

    def read_all(self, conversation_id: str) -> list[dict]: return self.read_after(conversation_id, 0)

    SIDE_EFFECT_TOOLS = frozenset({
        "write_file", "delete_file", "move_file",
        "create_directory", "delete_directory",
        "run_command", "ssh_execute",
    })

    def has_side_effects_in_turn(self, conversation_id: str, task_id: str) -> bool:
        """True, если в текущем ходе был хотя бы один tool_call с побочными эффектами.

        Сканирует журнал в обратном порядке до границы хода.
        Учитывает tool_call, а не tool_result: если агент запросил
        модифицирующий инструмент, это сигнал, что он намерен менять
        состояние, и завершать без verification нельзя.
        """
        events = self.read_all(conversation_id)
        for event in reversed(events):
            if event.get("task_id") != task_id:
                continue
            if event["type"] in ("turn_completed", "turn_cancelled"):
                break
            if event["type"] == "tool_call":
                if event["payload"].get("name") in self.SIDE_EFFECT_TOOLS:
                    return True
        return False

    def has_recent_verification(self, conversation_id: str, task_id: str) -> bool:
        """Return whether the current task has a latest, still-active successful verification."""
        for event in reversed(self.read_all(conversation_id)):
            if event.get("task_id") != task_id:
                continue
            event_type = event.get("type")
            if event_type == "verification":
                payload = event.get("payload")
                return bool(payload.get("verified")) if isinstance(payload, dict) else False
            if event_type in ("turn_completed", "turn_cancelled", "error"):
                break
        return False

    def create_approval(self, conversation_id: str, task_id: str, tool_call_id: str, tool_name: str, arguments: dict, description: str) -> str:
        cid = self._valid_id(conversation_id); approval_id = "approval_" + uuid.uuid4().hex
        item = {"approval_id":approval_id,"conversation_id":cid,"task_id":task_id,"tool_call_id":tool_call_id,"tool_name":str(tool_name)[:160],"arguments":arguments,"description":str(description)[:1000],"status":"pending","created_at":_now(),"resolved_at":None}
        path = self._dir(cid) / "approvals" / (approval_id + ".json")
        with self._lock(cid):
            self._load(cid)
            try: _atomic_json(path, item)
            except OSError as exc: raise OSError(f"Не удалось создать подтверждение {approval_id}: {exc}") from exc
        return approval_id

    def get_approval(self, conversation_id: str, approval_id: str) -> dict | None:
        cid = self._valid_id(conversation_id)
        if not isinstance(approval_id, str) or not approval_id.startswith("approval_") or not all(c.isalnum() or c in "_-" for c in approval_id): raise ValueError("Некорректный approval_id")
        path = self._dir(cid) / "approvals" / (approval_id + ".json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except FileNotFoundError: return None
        except (OSError, ValueError) as exc: raise RuntimeError(f"Не удалось прочитать подтверждение {approval_id}: {exc}") from exc

    def resolve_approval(self, conversation_id: str, approval_id: str, decision: str) -> dict | None:
        if decision not in ("approved", "rejected"): raise ValueError('decision должен быть "approved" или "rejected"')
        cid = self._valid_id(conversation_id)
        with self._lock(cid):
            item = self.get_approval(cid, approval_id)
            if item is None: return None
            if item.get("resolved_at"):
                if item.get("status") != decision: raise ValueError("Подтверждение уже разрешено противоположным решением")
                return item
            item["status"] = decision; item["resolved_at"] = _now()
            _atomic_json(self._dir(cid) / "approvals" / (approval_id + ".json"), item)
            return item

    def list_pending_approvals(self, conversation_id: str) -> list[dict]:
        cid = self._valid_id(conversation_id); folder = self._dir(cid) / "approvals"
        with self._lock(cid):
            self._load(cid); result = []
            for path in folder.glob("approval_*.json"):
                item = self.get_approval(cid, path.stem)
                if item and item.get("status") == "pending": result.append(item)
            return sorted(result, key=lambda x: x.get("created_at", ""))

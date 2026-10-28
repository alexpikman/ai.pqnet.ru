# Архитектура
> Приложение состоит из Python HTTP-сервера, файлового слоя данных и статического frontend.
> Чат отделён на ConversationStore, EventHub, AgentRuntime и OllamaAdapter.
> История событий хранится в JSONL; EventHub только доставляет уже записанные события подписчикам.
> Браузер получает события через EventSource (SSE), а команды отправляет HTTP POST.
> Серверный entry point и реальные маршруты определены в `server.py`, а не в этой схеме.

## Слои

```text
Browser
  ├─ frontend/app.js (основной интерфейс / страницы / настройки)
  └─ frontend/chat.js
       ├─ ChatTransport ── EventSource GET /api/chat/events
       ├─ ChatTransport ── HTTP POST команды
       └─ ChatRenderer ── DOM-события и карточки
                         │
                 server.py / ThreadingHTTPServer
                    ├─ REST API и статические файлы
                    ├─ ConversationStore ── JSONL на диске
                    ├─ EventHub ── очереди подписчиков
                    └─ AgentRuntime ── OllamaAdapter ── Ollama HTTP API
                                          └─ agent_tools.py
```

## Путь события
1. Runtime вызывает `ConversationStore.append_event`.
2. Store назначает метаданные события и записывает его в журнал.
3. Runtime передаёт возвращённое событие в `EventHub.publish`.
4. HTTP-обработчик SSE отправляет событие подписчикам.
5. `ChatTransport` проверяет conversation_id, epoch и sequence; `ChatRenderer` обновляет UI.

**Инвариант:** запись журнала предшествует публикации в EventHub. SSE не является хранилищем истины; при разрыве клиент может запросить историю после известного sequence.

## Границы
- `ConversationStore` использует блокировки внутри процесса; это не межпроцессная блокировка.
- Команды и дедупликация command_id в AgentRuntime хранятся в памяти процесса.
- Транспорт чата — SSE для событий и HTTP POST для команд, не WebSocket.
- Потоковый чат в `server.py` сейчас допускает формат Ollama; другие форматы, даже если доступны в общем каталоге моделей, не автоматически поддерживаются этим runtime.

# Событийный чат PQlocalAgentOSv3 — этап 1

Реализация для Python 3.12+ без новых pip-зависимостей. Старый `POST /api/chat` сохранён; добавлены отдельные маршруты событийного чата.

## Что включено

- `chat/conversation_store.py`: JSONL-журнал, монотонный `sequence`, атомарный `meta.json`, восстановление повреждённого хвоста и дисковые approval-записи.
- `chat/chat_events.py`: неблокирующий EventHub с очередями по 256 событий.
- `chat/provider_adapter.py`: потоковый клиент Ollama `POST /api/chat`.
- `chat/agent_runtime.py`: цикл агента, дельты ответа, вызовы инструментов через существующий `agent_tools.execute_tool`, отмена и ограничение шагов.
- `frontend/chat-transport.js` + `frontend/chat-renderer.js`: SSE, повторное подключение, восстановление пропусков из журнала и безопасный рендеринг.
- Интеграция маршрутов и интерфейса в `server.py`, `frontend/chat.js`, `frontend/styles/bundle.css`.

## Маршруты

- `GET /api/chat/conversations`
- `POST /api/chat/conversations` с `{ "title": "..." }`
- `GET /api/chat/history?conversation_id=conv_...&after=0`
- `GET /api/chat/events?conversation_id=conv_...&after=0` (SSE)
- `POST /api/chat/send` с `{ "conversation_id", "command_id", "agent_id", "project_id", "text" }`
- `POST /api/chat/approve` с `{ "conversation_id", "approval_id", "command_id", "decision" }`
- `POST /api/chat/cancel` с `{ "conversation_id", "command_id" }`
- `POST /api/chat/import` — однократный перенос старой локальной истории при первом подключении чата.

Все API-маршруты сохраняют существующую проверку локального Host и текущую авторизацию. Инструменты не исполняются напрямую: runtime вызывает только `agent_tools.execute_tool` с настройками разрешений агента и глобальными файловыми разрешениями.

## Проверка

Из корня репозитория:

```bat
python -m compileall -q server.py agent_tools.py chat tests
python -m unittest tests.test_conversation_store -v
```

Данные хранятся в `data/conversations/<conversation_id>/events.jsonl`, метаданные — в `meta.json`, подтверждения — в `approvals/`.

## Известные ограничения этапа 1

1. `command_id` и активные задачи отслеживаются в памяти процесса; дедупликация команд не переживает перезапуск сервера.
2. Подтверждение сохраняется на диск, но после решения инструмент **не возобновляется и не выполняется автоматически**. UI явно сообщает, что действие не было исполнено; нужен отдельный resume-механизм.
3. Отмена проверяется между строками Ollama; уже заблокированный `urllib`-read не прерывается мгновенно.
4. Только Ollama подключена к потоковому адаптеру. Другие провайдеры и GGUF требуют отдельного адаптера.
5. EventHub работает в одном процессе. Для нескольких серверных процессов потребуется межпроцессный брокер или другое хранилище.
6. Snapshot/компактизация журнала и WebSocket отложены; используется SSE.
7. Результат команды ограничен в памяти сервера, а не в долговременном реестре. Сами события и approvals хранятся на диске.
8. Локальный запуск приложения и браузерный smoke-test должны выполняться в среде проекта; успешная компиляция/тесты не гарантируют доступность Ollama или корректность настроек конкретного агента.

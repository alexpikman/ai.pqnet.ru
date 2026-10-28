# Frontend chat
> Сборка интерфейса чата: [frontend/chat.js](../../../frontend/chat.js).
> Рендерер событий: [frontend/chat-renderer.js](../../../frontend/chat-renderer.js).
> Транспорт: [frontend/chat-transport.js](../../../frontend/chat-transport.js).
> Клиент использует EventSource/SSE для событий и fetch POST для команд.
> Рендерер создаёт DOM-узлы и отображает сообщения, tool calls, approvals, статусы и ошибки.

## Компоненты
- `chat.js`: строит рабочую область, выбирает агента, управляет диалогами, запускает транспорт и связывает UI.
- `chat-transport.js`: открывает `/api/chat/events`, проверяет conversation_id, sequence и epoch; повторяет соединение с увеличением задержки.
- `chat-renderer.js`: применяет события, избегает вставки текста модели через `innerHTML`, обрабатывает подтверждения инструментов.

## Протокол
- SSE: `GET /api/chat/events?conversation_id=…&after=…`.
- Команды отправляются HTTP POST, а не WebSocket.
- Клиент игнорирует дубли sequence, обнаруживает разрывы и инициирует восстановление.
- События подтверждения отображаются карточками, решение передаётся через transport.

## Тесты
Основные backend tests: [tests/test_chat_agent_runtime.py](../../../tests/test_chat_agent_runtime.py) и [tests/test_server.py](../../../tests/test_server.py). В перечисленном каталоге нет отдельного автоматизированного JS/browser test suite.

## TODO / known issues
- UI не доказывает корректность серверных гарантий; тестируй обе стороны протокола.
- При изменении типа события обновляй renderer, transport (если меняется envelope) и тесты.

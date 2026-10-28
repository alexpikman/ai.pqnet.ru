# AI Context — точка входа
> Для AI-ассистента: эта папка описывает архитектуру и реальные контракты PQlocalAgentOSv3; проверяй код перед изменениями.
> Начинай с обзора и архитектуры, затем открывай модульный документ по задаче.
> Документация отражает снимок кода на момент коммита и не заменяет чтение реализации.
> Не считай планы или README доказательством работающей функции.
> Не изменяй код вне задачи и не заявляй о запуске тестов без фактического запуска.

## Как использовать
Перед началом работы передай ИИ ссылку на этот файл и на соответствующий файл из `modules/`. Для межмодульных изменений добавь `01-architecture.md`, `02-tech-stack.md` и `tests/test-map.md`.

## Карта
- [00-project-overview.md](00-project-overview.md) — назначение, аудитория, границы.
- [01-architecture.md](01-architecture.md) — слои и потоки данных.
- [02-tech-stack.md](02-tech-stack.md) — стек, подтверждённый исходниками.
- [03-glossary.md](03-glossary.md) — терминология и состояния.
- [modules/conversation-store.md](modules/conversation-store.md) — долговременный журнал.
- [modules/agent-runtime.md](modules/agent-runtime.md) — выполнение хода агента.
- [modules/agent-tools.md](modules/agent-tools.md) — инструменты и границы доступа.
- [modules/provider-adapter.md](modules/provider-adapter.md) — потоковый клиент модели.
- [modules/chat-events.md](modules/chat-events.md) — EventHub и SSE.
- [modules/server-api.md](modules/server-api.md) — HTTP API и сервер.
- [modules/frontend-chat.md](modules/frontend-chat.md) — UI, рендерер, транспорт.
- [modules/frontend-app.md](modules/frontend-app.md) — основное приложение и конструктор.
- [tests/test-map.md](tests/test-map.md) — существующие тестовые файлы и зоны покрытия.
- [protocols/new-module.md](protocols/new-module.md) — добавление модуля.
- [protocols/new-tool.md](protocols/new-tool.md) — добавление инструмента.
- [protocols/new-event.md](protocols/new-event.md) — добавление события.

## Правила для ассистента
1. Сначала изучи текущую реализацию и тесты, затем предложи минимальный diff.
2. Различай основной UI-каталог провайдеров и потоковый чат: текущий chat runtime создаётся только для Ollama.
3. Не обещай полную изоляцию или абсолютную безопасность: сервер локально привязан к loopback, но инструменты, разрешения и конфигурация требуют проверки.
4. Сохраняй совместимость схемы событий и контрактов API; добавляй регрессионные тесты.
5. Документируй неизвестное как неизвестное, не превращай TODO в реализованную функцию.

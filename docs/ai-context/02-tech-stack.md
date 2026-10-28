# Технологический стек по исходникам
> Backend entry point начинается с `http.server`: используется стандартный HTTP-сервер Python.
> Модули чата импортируют стандартные `json`, `threading`, `queue`, `urllib` и `pathlib`.
> Frontend написан на Vanilla JavaScript и CSS; дизайн-тема строится на CSS custom properties.
> Поток событий использует `EventSource` и SSE, а команды — HTTP POST.
> Для потокового чата подтверждён адаптер Ollama; каталог провайдеров в сервере — отдельная возможность.

## Подтверждённое
- **Python:** исходники используют синтаксис современных версий Python; README заявляет Python 3.10+, запускной контекст проекта — Windows. Не заявлять жёстко Python 3.12 как единственную поддерживаемую версию без проверки CI/runtime.
- **HTTP:** `http.server.ThreadingHTTPServer` и `SimpleHTTPRequestHandler` в `server.py`.
- **Хранилище событий:** JSONL-файлы, атомарная запись служебных JSON и `os.replace` в `chat/conversation_store.py`.
- **Чат:** `chat/agent_runtime.py`, `chat/conversation_store.py`, `chat/chat_events.py`, `chat/provider_adapter.py`.
- **Транспорт:** `EventSource` / SSE для серверных событий; HTTP POST для команд.
- **Frontend:** Vanilla JS, обычные HTML/CSS, без React в указанных точках входа; CSS custom properties в `frontend/styles/01-tokens.css`.
- **Локальная модель:** `OllamaAdapter` вызывает `/api/chat` через `urllib.request`.
- **Опциональные файловые модели:** `server.py` пытается импортировать `llama_cpp` и `huggingface_hub` в блоках try/except; эти библиотеки не являются стандартной библиотекой.

## Что не подтверждено / не следует утверждать
- **FastAPI:** не используется как HTTP entry point в `server.py`.
- **WebSocket:** не является транспортом чата; используется SSE.
- **Tailwind CSS:** не подтверждён; CSS собран вручную, тема основана на переменных.
- **React:** в перечисленных frontend entry points используется Vanilla JS.
- **«Ноль внешних зависимостей во всём приложении»:** слишком сильное утверждение — есть опциональные импорты llama-cpp-python и huggingface_hub, а интеграции обращаются к сетевым API.
- **«Все данные никогда не покидают машину»:** некорректно как безусловная гарантия. Облачные интеграции и GitHub/API могут отправлять данные наружу, если пользователь их настраивает.
- **«Все провайдеры поддерживаются в чате»:** неверно; потоковый chat runtime в `server.py` проверяет `provider.get('format') == 'ollama'`.

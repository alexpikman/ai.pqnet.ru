# Provider Adapter
> Реализация: [chat/provider_adapter.py](../../../chat/provider_adapter.py).
> В модуле определены `ProviderChunk` и `OllamaAdapter`.
> Адаптер вызывает Ollama `/api/chat` через `urllib.request` и читает построчный JSON.
> Поток нормализуется в типы text, tool_calls, done и error.
> Наличие других провайдеров в каталоге приложения не означает поддержку их потоков этим chat runtime.

## Назначение
Преобразует потоковый HTTP-ответ Ollama в единый поток событийных фрагментов, понятный AgentRuntime.

## Контракт
- `ProviderChunk(kind, text="", tool_calls=None, raw=None)`
- `OllamaAdapter(base_url="http://127.0.0.1:11434", timeout=180)`
- `stream_chat(model, messages, tools=None, should_cancel=None) -> Iterator[ProviderChunk]`

## Инварианты
- Запрос идёт на `/api/chat` с `stream: true`.
- Непустое содержимое выдаётся как `text`, вызовы инструментов — как `tool_calls`.
- При `done: true` выдаётся `done`; неожиданный/ошибочный ответ превращается в `error`.
- `should_cancel` проверяется между строками ответа.
- Сетевые ошибки не следует интерпретировать как успешное завершение.

## Зависимости
Стандартные `json`, `socket`, `threading`, `urllib`, `dataclasses`, `typing`.

## Тесты
Специализированного отдельного `test_provider_adapter.py` в текущем каталоге tests не обнаружено; проверяй покрытие через runtime tests и добавляй изолированные тесты адаптера при изменении протокола.

## TODO / known issues
- Это адаптер Ollama, не общий OpenAI-compatible/Anthropic adapter.
- Убедись, что ошибки HTTP/timeout/cancel корректно преобразуются в события runtime.

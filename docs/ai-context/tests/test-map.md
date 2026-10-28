# Карта тестов
> Тесты Python находятся в каталоге `tests/` и запускаются через unittest.
> Карта описывает видимые тестовые файлы; конкретные assertions нужно проверять в исходниках.
> Список не означает, что каждая функция проекта покрыта.
> Тесты на backend не подтверждают автоматически визуальную корректность браузерного UI.
> На момент создания документа в каталоге перечислены пять основных файлов test_*.py.

| Тест | Что покрывает по назначению | Файл реализации |
|---|---|---|
| [test_agent_runtime.py](../../../tests/test_agent_runtime.py) | Runtime/логика агентов вне событийного chat runtime; точные assertions — в файле | [agent runtime / legacy paths](../../../) |
| [test_agent_tools.py](../../../tests/test_agent_tools.py) | Инструменты, ограничения файлового доступа и разрешения | [agent_tools.py](../../../agent_tools.py) |
| [test_chat_agent_runtime.py](../../../tests/test_chat_agent_runtime.py) | Событийный runtime, последовательность событий, tool flow, состояния завершения/verification по тестам | [chat/agent_runtime.py](../../../chat/agent_runtime.py) |
| [test_conversation_store.py](../../../tests/test_conversation_store.py) | Журнал событий, восстановление и валидность диалогов | [chat/conversation_store.py](../../../chat/conversation_store.py) |
| [test_server.py](../../../tests/test_server.py) | HTTP API и серверные маршруты/функции | [server.py](../../../server.py) |

## Запуск
```powershell
python -m unittest discover -s tests -v
```

Не фиксируй число тест-кейсов как постоянное: оно меняется при добавлении тестов. Чтобы подтвердить количество, запускай команду и считай фактические результаты. В репозитории не обнаружен отдельный JS/browser suite в `tests/`.

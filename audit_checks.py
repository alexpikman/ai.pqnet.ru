"""Read-only project audit checks for PQlocalAgentOSv3.

The module uses only the Python standard library. Checks return structured results
and never repair, delete, or rewrite project data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MODULES = ROOT / "modules"
REPORT_PATH = DATA / "audit_last_report.json"

AGENT_PERMISSION_KEYS = {
    "file_loading", "file_saving", "file_moving", "file_deletion",
    "directory_creation", "directory_deletion", "directory_moving",
    "github_access", "terminal_access", "web_access", "ssh_access",
}
MODULE_TOP_LEVEL_KEYS = {
    "id", "name", "version", "description", "author", "license",
    "repository", "api_version", "entrypoint", "runtime", "inputs",
    "outputs", "capabilities", "permissions", "dependencies", "pages",
}
RUNTIME_KINDS = {"input", "template", "ollama", "transform", "output"}
RUNTIME_KEYS = {"kind", "template", "system_prompt", "model", "max_tokens", "operation"}
PORT_KEYS = {"name", "type", "required", "description"}
TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".html", ".css", ".scss", ".xml", ".svg", ".sql", ".sh",
    ".bat", ".ps1", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".ini",
    ".cfg", ".env", ".txt", ".md", ".log",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".idea",
    ".pytest_cache", "dist", "build",
}
CHECKS: list[dict[str, Any]] = []


def _load_json(path: Path) -> tuple[Any, str | None]:
    """Read JSON without changing the source file."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _result(
    check_id: str,
    category: str,
    status: str,
    message: str,
    details: Any = None,
    severity: str | None = None,
) -> dict[str, Any]:
    if severity is None:
        severity = "info" if status in {"pass", "skip"} else "warning"
    return {
        "id": check_id,
        "category": category,
        "severity": severity,
        "status": status,
        "message": message,
        "details": details if details is not None else [],
    }


def _register(check_id: str, category: str, title: str, enabled: bool = True):
    def decorate(function: Callable[[Path], dict[str, Any]]):
        CHECKS.append({
            "id": check_id,
            "category": category,
            "title": title,
            "enabled": enabled,
            "function": function,
        })
        return function
    return decorate


def _read_registry(root: Path, filename: str, fallback: Any = None) -> tuple[Any, str | None]:
    path = root / "data" / filename
    if not path.exists():
        return fallback, None
    value, error = _load_json(path)
    if error:
        return None, f"{path.relative_to(root)}: {error}"
    return value, None


def _as_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _permission_errors(agent: dict[str, Any]) -> list[str]:
    permissions = agent.get("permissions")
    if not isinstance(permissions, dict):
        return ['поле "permissions" отсутствует или не является объектом']
    unknown = sorted(set(permissions) - AGENT_PERMISSION_KEYS)
    missing = sorted(AGENT_PERMISSION_KEYS - set(permissions))
    invalid = sorted(key for key, value in permissions.items()
                     if key in AGENT_PERMISSION_KEYS and not isinstance(value, bool))
    issues = []
    if unknown:
        issues.append("неизвестные разрешения: " + ", ".join(unknown))
    if missing:
        issues.append("не заданы разрешения: " + ", ".join(missing))
    if invalid:
        issues.append("значения должны быть boolean: " + ", ".join(invalid))
    return issues


def _ssh_connection_ids(root: Path) -> tuple[set[str], str | None]:
    value, error = _read_registry(root, "ssh_connections.json", [])
    if error:
        return set(), error
    if isinstance(value, dict):
        value = value.get("connections", [])
    if not isinstance(value, list):
        return set(), "data/ssh_connections.json: ожидался список подключений"
    return {
        str(item.get("id", "")).strip()
        for item in value
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }, None


def _project_agent_links(agent: dict[str, Any]) -> set[str]:
    result = set()
    project_id = str(agent.get("project_id", "")).strip()
    if project_id:
        result.add(project_id)
    project_ids = agent.get("project_ids")
    if isinstance(project_ids, list):
        result.update(str(value).strip() for value in project_ids if str(value).strip())
    return result


@_register("agents.permissions.schema", "Правила и разрешения агентов",
           "Структура разрешений агентов")
def check_agent_permissions(root: Path) -> dict[str, Any]:
    agents, error = _read_registry(root, "agents.json", [])
    if error:
        return _result("agents.permissions.schema", "Правила и разрешения агентов",
                       "fail", "Не удалось прочитать реестр агентов.", [error], "error")
    if not isinstance(agents, list):
        return _result("agents.permissions.schema", "Правила и разрешения агентов",
                       "fail", "Реестр агентов должен быть списком.", [], "error")
    issues = []
    for agent in _as_records(agents):
        name = str(agent.get("name") or agent.get("id") or "(без имени)")
        for issue in _permission_errors(agent):
            issues.append({"agent": name, "issue": issue})
    return _result(
        "agents.permissions.schema", "Правила и разрешения агентов",
        "fail" if issues else "pass",
        f"Найдены ошибки разрешений у {len(issues)} элементов." if issues
        else "Структура разрешений агентов корректна.",
        issues, "error" if issues else "info",
    )


@_register("agents.tools.references", "Правила и разрешения агентов",
           "Ссылки агентов на инструменты")
def check_agent_tool_references(root: Path) -> dict[str, Any]:
    try:
        from agent_tools import TOOL_DEFINITIONS
        available = {item.get("function", {}).get("name")
                     for item in TOOL_DEFINITIONS if isinstance(item, dict)}
    except Exception as exc:
        return _result("agents.tools.references", "Правила и разрешения агентов",
                       "fail", "Не удалось загрузить реестр инструментов.",
                       [f"{type(exc).__name__}: {exc}"], "error")
    agents, error = _read_registry(root, "agents.json", [])
    if error or not isinstance(agents, list):
        return _result("agents.tools.references", "Правила и разрешения агентов",
                       "fail", "Не удалось проверить ссылки на инструменты.",
                       [error or "Реестр агентов должен быть списком."], "error")
    issues = []
    for agent in _as_records(agents):
        declared = []
        for field in ("tools", "tool_ids", "enabled_tools"):
            value = agent.get(field)
            if isinstance(value, list):
                declared.extend(str(item) for item in value)
        unknown = sorted(set(declared) - available)
        if unknown:
            issues.append({
                "agent": str(agent.get("name") or agent.get("id") or "(без имени)"),
                "unknown_tools": unknown,
            })
    return _result(
        "agents.tools.references", "Правила и разрешения агентов",
        "fail" if issues else "pass",
        "Найдены ссылки на неизвестные инструменты." if issues
        else "Висячих ссылок на инструменты не обнаружено.",
        issues, "error" if issues else "info",
    )


@_register("agents.permissions.environment", "Правила и разрешения агентов",
           "Соответствие SSH/GitHub-разрешений окружению")
def check_agent_environment_permissions(root: Path) -> dict[str, Any]:
    agents, agent_error = _read_registry(root, "agents.json", [])
    projects, project_error = _read_registry(root, "projects.json", [])
    if agent_error or project_error or not isinstance(agents, list) or not isinstance(projects, list):
        return _result("agents.permissions.environment", "Правила и разрешения агентов",
                       "fail", "Не удалось сопоставить разрешения и окружения проектов.",
                       [x for x in (agent_error, project_error) if x] or
                       ["Реестры агентов и проектов должны быть списками."], "error")
    project_by_id = {
        str(item.get("id")): item for item in _as_records(projects) if item.get("id")
    }
    issues = []
    linked_agents = 0
    for agent in _as_records(agents):
        linked_ids = _project_agent_links(agent)
        if not linked_ids:
            continue
        linked_agents += 1
        permissions = agent.get("permissions")
        if not isinstance(permissions, dict):
            continue
        for project_id in sorted(linked_ids):
            project = project_by_id.get(project_id)
            if not project:
                continue
            env_type = str(project.get("env_type", "local")).strip().lower()
            for permission, required_env in (("github_access", "github"), ("ssh_access", "ssh")):
                if permissions.get(permission) is True and env_type != required_env:
                    issues.append({
                        "agent": str(agent.get("name") or agent.get("id") or "(без имени)"),
                        "project": str(project.get("name") or project_id),
                        "environment": env_type,
                        "permission": permission,
                        "expected_environment": required_env,
                    })
    if not linked_agents:
        return _result("agents.permissions.environment", "Правила и разрешения агентов",
                       "skip", "Проверка пропущена: у агентов нет явной привязки к проектам.",
                       {"reason": "Без project_id/project_ids нельзя достоверно сопоставить разрешения и окружение."})
    return _result(
        "agents.permissions.environment", "Правила и разрешения агентов",
        "fail" if issues else "pass",
        "Обнаружены разрешения, не соответствующие окружению проекта." if issues
        else "SSH/GitHub-разрешения согласованы с окружениями связанных проектов.",
        issues, "warning" if issues else "info",
    )


@_register("projects.environment", "Проекты и окружения",
           "Тип окружения и обязательные параметры проекта")
def check_project_environment(root: Path) -> dict[str, Any]:
    projects, error = _read_registry(root, "projects.json", [])
    if error or not isinstance(projects, list):
        return _result("projects.environment", "Проекты и окружения", "fail",
                       "Не удалось проверить окружения проектов.",
                       [error or "Реестр проектов должен быть списком."], "error")
    ssh_ids, ssh_error = _ssh_connection_ids(root)
    issues = []
    for project in _as_records(projects):
        project_id = str(project.get("id") or "(без id)")
        name = str(project.get("name") or project_id)
        env_type = str(project.get("env_type", "")).strip().lower()
        if env_type not in {"local", "github", "ssh"}:
            issues.append({"project": name, "issue": "Недопустимый env_type", "value": env_type})
        elif env_type == "ssh":
            connection_id = str(project.get("ssh_connection_id", "")).strip()
            if ssh_error:
                issues.append({"project": name, "issue": ssh_error})
            elif not connection_id or connection_id not in ssh_ids:
                issues.append({"project": name, "issue": "SSH-подключение не задано или не найдено",
                               "ssh_connection_id": connection_id})
        elif env_type == "github" and not str(project.get("repo_name", "")).strip():
            issues.append({"project": name, "issue": "Для GitHub-окружения не задан repo_name"})
    return _result(
        "projects.environment", "Проекты и окружения",
        "fail" if issues else "pass",
        "Найдены некорректные настройки окружений." if issues
        else "Типы окружений и обязательные параметры проектов корректны.",
        issues, "error" if issues else "info",
    )


@_register("projects.deletion.conflicts", "Проекты и окружения",
           "Проекты, помеченные на удаление и связанные с задачами")
def check_project_deletion_conflicts(root: Path) -> dict[str, Any]:
    projects, project_error = _read_registry(root, "projects.json", [])
    tasks, task_error = _read_registry(root, "tasks.json", [])
    if project_error or task_error or not isinstance(projects, list) or not isinstance(tasks, list):
        return _result("projects.deletion.conflicts", "Проекты и окружения", "fail",
                       "Не удалось проверить конфликты удаления проектов.",
                       [x for x in (project_error, task_error) if x] or
                       ["Реестры проектов и задач должны быть списками."], "error")
    tasks_by_project: dict[str, list[str]] = {}
    for task in _as_records(tasks):
        project_id = str(task.get("project_id", "")).strip()
        if project_id:
            tasks_by_project.setdefault(project_id, []).append(
                str(task.get("title") or task.get("id") or "(без названия)")
            )
    issues = []
    deletion_fields = ("delete_pending", "deletion_requested", "marked_for_deletion")
    project_records = _as_records(projects)
    if not any(field in project for project in project_records for field in deletion_fields):
        return _result(
            "projects.deletion.conflicts", "Проекты и окружения", "skip",
            "Проверка пропущена: в текущей схеме проектов нет явного флага удаления. API блокирует удаление проекта с задачами через HTTP 409.",
            {"reason": "Не добавляем несуществующее поле удаления и не меняем данные проекта."},
        )
    for project in project_records:
        project_id = str(project.get("id", "")).strip()
        marked = any(project.get(field) is True for field in deletion_fields)
        linked_tasks = tasks_by_project.get(project_id, [])
        if marked and linked_tasks:
            issues.append({
                "project": str(project.get("name") or project_id),
                "tasks": linked_tasks[:20],
                "issue": "Проект помечен на удаление, но содержит связанные задачи (удаление должно вернуть HTTP 409).",
            })
    return _result(
        "projects.deletion.conflicts", "Проекты и окружения",
        "fail" if issues else "pass",
        "Найдены конфликты удаления проектов." if issues
        else "Проектов с явным флагом удаления и связанными задачами не обнаружено.",
        issues, "warning" if issues else "info",
    )


def _validate_port(port: Any, where: str, issues: list[str]) -> None:
    if not isinstance(port, dict):
        issues.append(f"{where}: порт должен быть объектом")
        return
    missing = {"name", "type"} - set(port)
    if missing:
        issues.append(f"{where}: отсутствуют поля {', '.join(sorted(missing))}")
    unknown = set(port) - PORT_KEYS
    if unknown:
        issues.append(f"{where}: неизвестные поля {', '.join(sorted(unknown))}")
    if "name" in port and not isinstance(port["name"], str):
        issues.append(f"{where}.name: ожидалась строка")
    if "type" in port and not isinstance(port["type"], str):
        issues.append(f"{where}.type: ожидалась строка")
    if "required" in port and not isinstance(port["required"], bool):
        issues.append(f"{where}.required: ожидался boolean")
    if "description" in port and not isinstance(port["description"], str):
        issues.append(f"{where}.description: ожидалась строка")


def _validate_manifest(manifest: Any, label: str) -> list[str]:
    issues: list[str] = []
    if not isinstance(manifest, dict):
        return [f"{label}: корень module.json должен быть объектом"]
    required = {"id", "name", "version", "description", "api_version"}
    missing = required - set(manifest)
    unknown = set(manifest) - MODULE_TOP_LEVEL_KEYS
    if missing:
        issues.append(f"{label}: отсутствуют обязательные поля {', '.join(sorted(missing))}")
    if unknown:
        issues.append(f"{label}: неизвестные поля {', '.join(sorted(unknown))}")
    if "id" in manifest and (not isinstance(manifest["id"], str) or
                             not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", manifest["id"])):
        issues.append(f"{label}.id: не соответствует формату")
    if "name" in manifest and (not isinstance(manifest["name"], str) or
                               not 1 <= len(manifest["name"]) <= 120):
        issues.append(f"{label}.name: ожидалась строка длиной 1–120")
    if "version" in manifest and (not isinstance(manifest["version"], str) or
                                  not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+", manifest["version"])):
        issues.append(f"{label}.version: ожидалась семантическая версия")
    for key, limit in (("description", 1000), ("author", 160), ("license", 80),
                       ("api_version", None), ("entrypoint", None)):
        if key not in manifest:
            continue
        value = manifest[key]
        if not isinstance(value, str) or (limit is not None and len(value) > limit):
            issues.append(f"{label}.{key}: некорректный тип или длина")
    if "repository" in manifest:
        repository = manifest["repository"]
        if not isinstance(repository, str) or not urlparse(repository).scheme or not urlparse(repository).netloc:
            issues.append(f"{label}.repository: ожидался URI")
    for key in ("inputs", "outputs", "capabilities", "permissions", "dependencies", "pages"):
        if key in manifest and not isinstance(manifest[key], list):
            issues.append(f"{label}.{key}: ожидался список")
    for key in ("inputs", "outputs"):
        if isinstance(manifest.get(key), list):
            for index, port in enumerate(manifest[key]):
                _validate_port(port, f"{label}.{key}[{index}]", issues)
    for key in ("capabilities", "permissions", "dependencies"):
        if isinstance(manifest.get(key), list) and any(not isinstance(value, str) for value in manifest[key]):
            issues.append(f"{label}.{key}: элементы должны быть строками")
    if isinstance(manifest.get("pages"), list):
        for index, page in enumerate(manifest["pages"]):
            if not isinstance(page, dict):
                issues.append(f"{label}.pages[{index}]: элемент должен быть объектом")
    if "runtime" in manifest:
        runtime = manifest["runtime"]
        if not isinstance(runtime, dict):
            issues.append(f"{label}.runtime: ожидался объект")
        else:
            missing_runtime = {"kind"} - set(runtime)
            unknown_runtime = set(runtime) - RUNTIME_KEYS
            if missing_runtime:
                issues.append(f"{label}.runtime: отсутствует kind")
            if unknown_runtime:
                issues.append(f"{label}.runtime: неизвестные поля {', '.join(sorted(unknown_runtime))}")
            if runtime.get("kind") not in RUNTIME_KINDS:
                issues.append(f"{label}.runtime.kind: неизвестный тип")
            for key, limit in (("template", 12000), ("system_prompt", 4000), ("model", 160)):
                if key in runtime and (not isinstance(runtime[key], str) or len(runtime[key]) > limit):
                    issues.append(f"{label}.runtime.{key}: некорректный тип или длина")
            if "max_tokens" in runtime and (not isinstance(runtime["max_tokens"], int) or
                                             isinstance(runtime["max_tokens"], bool) or
                                             not 64 <= runtime["max_tokens"] <= 4096):
                issues.append(f"{label}.runtime.max_tokens: значение должно быть от 64 до 4096")
            if "operation" in runtime and runtime["operation"] not in {
                "uppercase", "lowercase", "strip", "json_parse", "json_pretty"
            }:
                issues.append(f"{label}.runtime.operation: неизвестная операция")
    return issues


@_register("modules.manifest.schema", "Схемы модулей",
           "Соответствие module.json контракту")
def check_module_manifests(root: Path) -> dict[str, Any]:
    module_root = root / "modules"
    if not module_root.is_dir():
        return _result("modules.manifest.schema", "Схемы модулей", "skip",
                       "Папка modules/ отсутствует; проверять манифесты нечего.")
    files = sorted(module_root.glob("*/module.json"))
    issues = []
    for path in files:
        manifest, error = _load_json(path)
        relative = str(path.relative_to(root))
        if error:
            issues.append({"file": relative, "issues": [error]})
            continue
        validation = _validate_manifest(manifest, relative)
        if validation:
            issues.append({"file": relative, "issues": validation})
    return _result(
        "modules.manifest.schema", "Схемы модулей",
        "fail" if issues else "pass",
        "Найдены манифесты, не соответствующие контракту." if issues
        else f"Проверено манифестов: {len(files)}; ошибок схемы нет.",
        issues, "error" if issues else "info",
    )


@_register("modules.graph.integrity", "Схемы модулей",
           "Циклы графа и совместимость портов")
def check_module_graph(root: Path) -> dict[str, Any]:
    registry, error = _read_registry(root, "modules.json", {"modules": [], "connections": []})
    if error or not isinstance(registry, dict):
        return _result("modules.graph.integrity", "Схемы модулей", "fail",
                       "Не удалось прочитать граф модулей.",
                       [error or "data/modules.json должен быть объектом."], "error")
    modules = _as_records(registry.get("modules", []))
    connections = registry.get("connections", [])
    if not isinstance(connections, list):
        return _result("modules.graph.integrity", "Схемы модулей", "fail",
                       "Список связей модулей должен быть массивом.", [], "error")
    module_ids = [str(item.get("id")) for item in modules if item.get("id")]
    duplicate_ids = sorted({module_id for module_id in module_ids if module_ids.count(module_id) > 1})
    by_id = {str(item.get("id")): item for item in modules if item.get("id")}
    adjacency = {module_id: [] for module_id in by_id}
    issues = ["Повторяющиеся id модулей: " + ", ".join(duplicate_ids)] if duplicate_ids else []
    for index, connection in enumerate(connections):
        label = f"connections[{index}]"
        if not isinstance(connection, dict):
            issues.append(f"{label}: связь должна быть объектом")
            continue
        source_id, target_id = str(connection.get("from", "")), str(connection.get("to", ""))
        if source_id not in by_id or target_id not in by_id:
            issues.append(f"{label}: ссылка на незарегистрированный модуль")
            continue
        if source_id == target_id:
            issues.append(f"{label}: модуль не может быть соединён сам с собой")
            continue
        source = by_id[source_id]
        target = by_id[target_id]
        source_manifest = source.get("manifest")
        target_manifest = target.get("manifest")
        if not isinstance(source_manifest, dict):
            source_manifest, _ = _load_json(root / "modules" / source_id / "module.json")
        if not isinstance(target_manifest, dict):
            target_manifest, _ = _load_json(root / "modules" / target_id / "module.json")
        source_manifest = source_manifest if isinstance(source_manifest, dict) else {}
        target_manifest = target_manifest if isinstance(target_manifest, dict) else {}
        source_ports = source_manifest.get("outputs", [])
        target_ports = target_manifest.get("inputs", [])
        source_ports = source_ports if isinstance(source_ports, list) else []
        target_ports = target_ports if isinstance(target_ports, list) else []
        from_port = str(connection.get("from_port") or (source_ports[0].get("name", "output") if source_ports and isinstance(source_ports[0], dict) else "output"))
        to_port = str(connection.get("to_port") or (target_ports[0].get("name", "input") if target_ports and isinstance(target_ports[0], dict) else "input"))
        source_port = next((port for port in source_ports if isinstance(port, dict) and port.get("name") == from_port), None)
        target_port = next((port for port in target_ports if isinstance(port, dict) and port.get("name") == to_port), None)
        if source_ports and not source_port:
            issues.append(f"{label}: выходной порт {from_port!r} не найден")
        if target_ports and not target_port:
            issues.append(f"{label}: входной порт {to_port!r} не найден")
        if source_port and target_port:
            source_type = source_port.get("type", "text")
            target_type = target_port.get("type", "text")
            if source_type != target_type and "any" not in {source_type, target_type}:
                issues.append(f"{label}: несовместимые типы портов {source_type!r} → {target_type!r}")
        adjacency[source_id].append(target_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for target in adjacency.get(node, []):
            if visit(target):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in adjacency if node not in visited):
        issues.append("Граф содержит цикл.")
    return _result(
        "modules.graph.integrity", "Схемы модулей",
        "fail" if issues else "pass",
        "Обнаружены ошибки графа модулей." if issues
        else f"Проверено связей: {len(connections)}; циклов и несовместимых портов не обнаружено.",
        issues, "error" if issues else "info",
    )


@_register("data.json.integrity", "Данные",
           "Читаемость JSON-файлов в data/")
def check_data_json(root: Path) -> dict[str, Any]:
    data_root = root / "data"
    if not data_root.is_dir():
        return _result("data.json.integrity", "Данные", "fail",
                       "Папка data/ отсутствует.", [], "error")
    files = sorted(data_root.rglob("*.json"))
    issues = []
    for path in files:
        _, error = _load_json(path)
        if error:
            issues.append({"file": str(path.relative_to(root)), "error": error})
    return _result(
        "data.json.integrity", "Данные",
        "fail" if issues else "pass",
        "Найдены повреждённые или нечитаемые JSON-файлы." if issues
        else f"Проверено JSON-файлов: {len(files)}; все читаются.",
        issues, "error" if issues else "info",
    )


@_register("data.orphan.references", "Данные",
           "Осиротевшие задачи и чаты")
def check_orphan_records(root: Path) -> dict[str, Any]:
    projects, project_error = _read_registry(root, "projects.json", [])
    tasks, task_error = _read_registry(root, "tasks.json", [])
    agents, agent_error = _read_registry(root, "agents.json", [])
    errors = [value for value in (project_error, task_error, agent_error) if value]
    if errors or not all(isinstance(value, list) for value in (projects, tasks, agents)):
        return _result("data.orphan.references", "Данные", "fail",
                       "Не удалось проверить ссылки между задачами, проектами и агентами.",
                       errors or ["Реестры должны быть списками."], "error")
    project_ids = {str(item.get("id")) for item in _as_records(projects) if item.get("id")}
    agent_ids = {str(item.get("id")) for item in _as_records(agents) if item.get("id")}
    issues = []
    for task in _as_records(tasks):
        project_id = str(task.get("project_id", "")).strip()
        if project_id and project_id not in project_ids:
            issues.append({
                "type": "task_without_project",
                "task": str(task.get("title") or task.get("id") or "(без названия)"),
                "project_id": project_id,
            })
    memory_root = root / "data" / "memory"
    if memory_root.is_dir():
        for path in sorted(memory_root.glob("*.json")):
            memory, error = _load_json(path)
            if error or not isinstance(memory, dict):
                continue
            chats = memory.get("chats", [])
            if not isinstance(chats, list):
                continue
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                agent_id = str(chat.get("agent_id", "")).strip()
                if not agent_id or agent_id not in agent_ids:
                    issues.append({
                        "type": "chat_without_agent",
                        "chat": str(chat.get("title") or chat.get("id") or "(без названия)"),
                        "file": str(path.relative_to(root)),
                        "agent_id": agent_id,
                    })
    return _result(
        "data.orphan.references", "Данные",
        "fail" if issues else "pass",
        "Найдены задачи или чаты без корректной связанной записи." if issues
        else "Осиротевших задач и чатов не обнаружено.",
        issues, "warning" if issues else "info",
    )


@_register("config.auth.default_password", "Конфигурация",
           "Отсутствие стандартного пароля при включённой авторизации")
def check_default_password(root: Path) -> dict[str, Any]:
    enabled = os.environ.get("PQ_AUTH_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return _result("config.auth.default_password", "Конфигурация", "skip",
                       "Проверка пропущена: PQ_AUTH_ENABLED не включён.")
    auth_path = root / "data" / "auth.json"
    auth, error = _load_json(auth_path)
    if error or not isinstance(auth, dict):
        return _result("config.auth.default_password", "Конфигурация", "fail",
                       "Не удалось проверить конфигурацию авторизации.",
                       [error or "data/auth.json должен быть объектом."], "error")
    if auth.get("must_change_password") is True:
        return _result("config.auth.default_password", "Конфигурация", "fail",
                       "Для учётной записи всё ещё требуется сменить стандартный пароль.",
                       {"username": auth.get("username", "")}, "error")
    try:
        salt = bytes.fromhex(str(auth.get("salt", "")))
        iterations = int(auth.get("iterations", 0))
        stored_hash = str(auth.get("password_hash", ""))
        if not salt or not 1 <= iterations <= 2_000_000 or not stored_hash:
            return _result("config.auth.default_password", "Конфигурация", "fail",
                           "Конфигурация авторизации содержит некорректные параметры.",
                           {"reason": "Проверьте salt, password_hash и iterations."}, "error")
        candidate = hashlib.pbkdf2_hmac("sha256", b"IamRootUser", salt, iterations).hex()
        is_default = hmac.compare_digest(candidate, stored_hash)
    except (ValueError, TypeError):
        is_default = False
    if is_default:
        return _result("config.auth.default_password", "Конфигурация", "fail",
                       "Используется стандартный пароль IamRootUser.", [], "error")
    return _result("config.auth.default_password", "Конфигурация", "pass",
                   "Стандартный пароль не обнаружен.")


@_register("config.github_token.leaks", "Конфигурация",
           "Отсутствие открытого GITHUB_TOKEN в файлах проекта")
def check_github_token_leaks(root: Path) -> dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    token_pattern = re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})")
    issues = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in TEXT_SUFFIXES or path == REPORT_PATH:
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found = bool(token and len(token) >= 20 and token in content) or bool(token_pattern.search(content))
            if found:
                issues.append(str(path.relative_to(root)))
    return _result(
        "config.github_token.leaks", "Конфигурация",
        "fail" if issues else "pass",
        "В файлах проекта обнаружены возможные открытые GitHub-токены." if issues
        else "Открытые GitHub-токены в проверенных текстовых файлах не обнаружены.",
        issues, "error" if issues else "info",
    )


def run_audit(root: str | Path | None = None) -> dict[str, Any]:
    """Run enabled checks and return a stable, JSON-serializable report."""
    project_root = Path(root).resolve() if root is not None else ROOT
    started = time.time()
    checks = []
    for definition in CHECKS:
        check_id = definition["id"]
        category = definition["category"]
        if not definition["enabled"]:
            checks.append(_result(check_id, category, "skip", "Проверка отключена в реестре."))
            continue
        try:
            result = definition["function"](project_root)
            if not isinstance(result, dict) or result.get("id") != check_id:
                raise ValueError("Проверка вернула результат с неверным контрактом.")
            checks.append(result)
        except Exception as exc:
            checks.append(_result(
                check_id, category, "fail",
                "Проверка завершилась внутренней ошибкой.",
                {"error_type": type(exc).__name__, "error": str(exc)[:300]},
                "error",
            ))
    counts = {
        "total": len(checks),
        "pass": sum(item["status"] == "pass" for item in checks),
        "fail": sum(item["status"] == "fail" for item in checks),
        "skip": sum(item["status"] == "skip" for item in checks),
        "errors": sum(item["severity"] == "error" and item["status"] == "fail" for item in checks),
        "warnings": sum(item["severity"] == "warning" and item["status"] == "fail" for item in checks),
    }
    finished = time.time()
    return {
        "version": 1,
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_ms": round((finished - started) * 1000),
        "summary": counts,
        "checks": checks,
    }


def check_registry() -> list[dict[str, str]]:
    """Expose metadata for UI or tests without exposing function objects."""
    return [
        {"id": item["id"], "category": item["category"], "title": item["title"],
         "enabled": bool(item["enabled"])}
        for item in CHECKS
    ]

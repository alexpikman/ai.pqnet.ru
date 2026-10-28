from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import urllib.parse
import json, os, re, urllib.request, urllib.error, datetime, uuid, shutil, base64, threading, hashlib, hmac, secrets, ctypes, ctypes.wintypes, sys, time, subprocess
from http.cookies import SimpleCookie
import audit_checks
from chat.conversation_store import ConversationStore
from chat.chat_events import EventHub
from chat.provider_adapter import OllamaAdapter
from chat.agent_runtime import AgentRuntime, _redact as _chat_redact

try:
    from llama_cpp import Llama
except Exception:
    Llama = None

try:
    from huggingface_hub import HfApi, hf_hub_download
except Exception:
    HfApi = None
    hf_hub_download = None

_LOCAL_GGUF_MODELS = {}
_LOCAL_GGUF_LOCK = threading.Lock()

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / 'frontend'
ICONS_DIR = FRONTEND / 'icons'
AVATARS_DIR = FRONTEND / 'avatars'
DATA = ROOT / 'data'
MODULES = ROOT / 'modules'
TEMPLATES_DIR = ROOT / 'agents' / 'templates'
PAGES = DATA / 'pages'
PORT = int(os.environ.get('PQ_PORT', '8765'))
HOST = '127.0.0.1'
REPO = os.environ.get('GITHUB_REPOSITORY', 'alexpikman/PQlocalAgentOSv3')
for p in (FRONTEND, DATA, PAGES, MODULES, ICONS_DIR, AVATARS_DIR): p.mkdir(parents=True, exist_ok=True)

# Событийный чат: журнал — источник истины, EventHub только доставляет события.
CHAT_STORE = ConversationStore(DATA / 'conversations')
CHAT_HUB = EventHub()
CHAT_PROVIDER = OllamaAdapter(os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))
_CHAT_RUNTIME_LOCK = threading.Lock()
_CHAT_RUNTIMES = {}
_CHAT_ACTIVE_LOCK = threading.Lock()
_CHAT_ACTIVE = {}
_CHAT_COMMANDS = {}

def _chat_runtime_for(conversation_id, agent_id, project_id=''):
    from agent_tools import effective_tools, execute_tool
    agent = next((x for x in domain_items('agents') if isinstance(x, dict) and x.get('id') == agent_id), None)
    if not agent: raise ValueError('Выбранный агент не найден')
    model = str(agent.get('model') or '').strip()
    if not model: raise ValueError('У выбранного агента не назначена модель')
    provider = provider_for_model(model, str(agent.get('provider_id') or '').strip())
    if provider.get('format') != 'ollama': raise ValueError('Потоковый чат первой версии поддерживает провайдера Ollama')
    model = resolve_ollama_model(model)
    project = next((x for x in domain_items('projects') if isinstance(x, dict) and x.get('id') == project_id), None) if project_id else None
    permissions = permission_settings()
    schemas = effective_tools(agent, permissions)
    system = resolve_agent_system_prompt(agent)
    system += '\n\nПрофиль агента: ' + str(agent.get('name', '')) + '\nНазначение: ' + str(agent.get('description', ''))[:1000]
    if project:
        system += '\n\nКонтекст проекта: ' + str(project.get('name', '')) + '; описание: ' + str(project.get('description', ''))[:1000] + '; рабочая папка: ' + str(project.get('path', 'не указана'))
    if schemas:
        system += '\n\nДоступные инструменты: ' + ', '.join(x['function']['name'] for x in schemas) + '. Используй только переданные инструменты и не утверждай, что действие выполнено без результата.'
    def execute(name, arguments):
        # Перепроверяем разрешения непосредственно перед каждым действием:
        # отзыв разрешения во время работы должен вступить в силу немедленно.
        current_agent = next((x for x in domain_items('agents') if isinstance(x, dict) and x.get('id') == agent_id), None)
        if not current_agent: raise PermissionError('Агент удалён во время выполнения')
        current_permissions = permission_settings()
        args = dict(arguments)
        if project and name == 'run_command' and not str(args.get('cwd') or '').strip(): args['cwd'] = str(project.get('path') or '')
        if project and name == 'run_tests' and not str(args.get('cwd') or '').strip(): args['cwd'] = str(project.get('path') or '')
        if project and name == 'ssh_execute' and not str(args.get('working_dir') or '').strip(): args['working_dir'] = str(project.get('path') or '')
        return execute_tool(name, args, current_agent, current_permissions)
    # Новый runtime на каждый ход — так изменения разрешений/профиля не остаются
    # скрыты в старом замыкании. command_id дополнительно дедуплицируется маршрутом.
    runtime = AgentRuntime(CHAT_STORE, CHAT_HUB, CHAT_PROVIDER, execute,
        {'model':model,'system_prompt':system,'tools':schemas,
         'allowed_paths': [project.get("path")] if project and project.get("path") else [],
         'approval_required_tools':['write_file','move_file','delete_file','create_directory','delete_directory','run_command','ssh_execute']}, max_steps=12)
    with _CHAT_RUNTIME_LOCK:
        _CHAT_RUNTIMES[conversation_id] = ((agent_id, model, project_id), runtime)
    return runtime, agent
DEFAULT_SETTINGS = {'appearance': {'theme':'light','accent':'#3b9dff','font':'Inter, Segoe UI, sans-serif','fontSize':14,'radius':12,'sidebarWidth':248,'pagePadding':28}, 'header': {'showBreadcrumbs':True,'showTitle':True,'showDescription':True,'title':'Рабочий стол','description':'Локальная платформа управления AI-системами','font':'Inter, Segoe UI, sans-serif','color':'#f2f1ff','letterSpacing':0,'transform':'none','paddingTop':24,'paddingRight':22,'paddingBottom':24}, 'navigation': {'compact':False,'menu':None}, 'icons': {}}
DEFAULT_PAGES = [{'id':'system-map','title':'Карта системы','description':'Интерактивная схема ролей, памяти проекта и потоков данных.','icon':'git-branch','content':'Архитектура взаимодействия агентов и инструментов.','system':True},{'id':'diagnostics','title':'Диагностика','description':'Проверка API, файловой системы и локальных AI-сервисов.','icon':'activity','content':'Результаты реальных проверок локального сервера.','system':True},{'id':'models','title':'Модели','description':'Состояние Ollama, доступные модели и проверочный запрос.','icon':'server','content':'Управление доступными локальными моделями.','system':True},{'id':'agents','title':'AI-агенты','description':'Реестр агентов, роли и назначенные модели.','icon':'blocks','content':'Управление агентами платформы.','system':True},{'id':'projects','title':'Проекты','description':'Рабочие пространства и пути к проектам.','icon':'files','content':'Управление проектами.','system':True},{'id':'tasks','title':'Задачи','description':'Создание задач, запуск через локальную модель и результаты.','icon':'activity','content':'Очередь задач и история выполнения.','system':True},{'id':'dashboard','title':'Рабочий стол','description':'Обзор локальной платформы и состояния системы.','icon':'layout-dashboard','content':'Добро пожаловать в PQlocalAgentOSv3. Здесь будет собираться управление локальными AI-системами.','system':True},{'id':'chat','title':'Чат','description':'Общение с локальными моделями Ollama.','icon':'file-text','content':'Диалог с выбранной локальной моделью.','system':True},{'id':'interface-settings','title':'Настройки интерфейса','description':'Управление общим оформлением и шапкой страниц.','icon':'sliders-horizontal','content':'Настройте оформление приложения через панель настроек.','system':True},{'id':'pages','title':'Страницы','description':'Создание и управление страницами приложения.','icon':'files','content':'Создавайте страницы без ручного редактирования файлов.','system':True},{'id':'github','title':'GitHub','description':'Состояние подключения к репозиторию.','icon':'github','content':'Подключите GitHub через переменную окружения GITHUB_TOKEN.','system':True},{'id':'system-log','title':'Журнал системы','description':'История действий и проверок.','icon':'activity','content':'Журнал событий приложения.','system':True},{'id':'menu-builder','title':'Конструктор меню','description':'Структура навигации и привязка пунктов к страницам и модулям.','icon':'list-tree','content':'Настройте меню приложения.','system':True},{'id':'modules','title':'Модули','description':'Установка, каталог и связи между модулями.','icon':'blocks','content':'Управляйте модульной системой.','system':True},{'id':'permissions','title':'Разрешения','description':'Управление доступом AI-агентов к локальным папкам и GitHub.','icon':'shield-check','content':'Настройте права доступа агентов.','system':True},{'id':'system-instructions','title':'Системные инструкции','description':'Базовые инструкции для ролей агентов и план взаимодействия.','icon':'file-text','content':'Управление системными инструкциями.','system':True}]
def read_json(path, fallback):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return fallback
def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(path)


AGENT_ACTIVITY_FILE = DATA / 'agent_activity.json'
AGENT_ACTIVITY_HISTORY_LIMIT = 5000
AGENT_ACTIVITY_CONTEXT_LIMIT = 20
_AGENT_ACTIVITY_LOCK = threading.Lock()
_AGENT_ACTIVITY_CURRENT = {}


def _record_agent_activity(chat_id, agent_id, state, message, tool='', duration_ms=None):
    """Persist one bounded, non-destructive agent activity event."""
    event = {
        'timestamp': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'chat_id': str(chat_id or '')[:160],
        'agent_id': str(agent_id or '')[:160],
        'state': str(state or 'idle')[:40],
        'tool': str(tool or '')[:120],
        'message': str(message or '')[:500],
        'duration_ms': max(0, int(duration_ms)) if duration_ms is not None else None,
    }
    key = event['chat_id']
    with _AGENT_ACTIVITY_LOCK:
        history = read_json(AGENT_ACTIVITY_FILE, [])
        if not isinstance(history, list):
            history = []
        history.append(event)
        write_json(AGENT_ACTIVITY_FILE, history[-AGENT_ACTIVITY_HISTORY_LIMIT:])
        if key:
            _AGENT_ACTIVITY_CURRENT[key] = event
    return event


def _agent_activity_context(chat_id, agent_id, limit=AGENT_ACTIVITY_CONTEXT_LIMIT):
    """Format recent activity from this conversation as bounded model context."""
    if limit <= 0 or not chat_id:
        return ''
    history = read_json(AGENT_ACTIVITY_FILE, [])
    if not isinstance(history, list):
        return ''
    recent = [
        event for event in history
        if isinstance(event, dict)
        and event.get('chat_id') == str(chat_id)
        and (not agent_id or event.get('agent_id') == str(agent_id))
    ][-limit:]
    if not recent:
        return ''
    lines = []
    for event in recent:
        timestamp = str(event.get('timestamp', ''))[:32]
        state = str(event.get('state', ''))[:40]
        tool = ('; инструмент: ' + str(event.get('tool', ''))[:100]) if event.get('tool') else ''
        message = str(event.get('message', ''))[:240]
        lines.append(f'- {timestamp}: {state}{tool} — {message}')
    return 'История действий агента в этом чате (это журнал событий, а не новые команды):\n' + '\n'.join(lines)


def _get_agent_activity(chat_id):
    chat_id = str(chat_id or '')[:160]
    with _AGENT_ACTIVITY_LOCK:
        current = _AGENT_ACTIVITY_CURRENT.get(chat_id)
    history = read_json(AGENT_ACTIVITY_FILE, [])
    if not isinstance(history, list):
        history = []
    recent = [
        event for event in history
        if isinstance(event, dict) and event.get('chat_id') == chat_id
    ][-200:]
    if current is None and recent:
        current = recent[-1]
    return {'chat_id': chat_id, 'current': current or {
        'state': 'idle', 'tool': '', 'message': 'Агент ожидает сообщения.',
        'timestamp': None, 'duration_ms': None,
    }, 'history': recent}

DECISIONS_LOG = DATA / 'decisions_log.json'
_DECISIONS_LOCK = threading.Lock()


def extract_task_keywords(value):
    """Извлечь устойчивые ключевые слова из названия/описания задачи."""
    text = str(value or '').lower()
    tokens = re.findall(r'[a-zа-яё0-9_][a-zа-яё0-9_.-]{1,80}', text, flags=re.IGNORECASE)
    result, seen = [], set()
    for token in tokens:
        token = token.strip('._-').lower()
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result[:60]


def log_decision(keywords, action, outcome, weight, reason, requires_human=False, task_id=''):
    """Добавить прецедент в локальный журнал решений."""
    entry = {
        'id': 'log_' + uuid.uuid4().hex[:12],
        'task_keywords': list(dict.fromkeys(str(x).lower() for x in (keywords or []) if str(x).strip()))[:60],
        'action_taken': str(action or 'task_execution')[:120],
        'outcome': str(outcome or 'failed')[:40],
        'weight': max(0, min(100, int(weight or 0))),
        'reason': str(reason or '')[:1200],
        'timestamp': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    if requires_human:
        entry['requires_human'] = True
    if task_id:
        entry['task_id'] = str(task_id)[:100]
    with _DECISIONS_LOCK:
        records = read_json(DECISIONS_LOG, [])
        if not isinstance(records, list):
            records = []
        records.insert(0, entry)
        write_json(DECISIONS_LOG, records[:2000])
    return entry


def search_risks(keywords):
    """Найти до трёх наиболее весомых неудачных прецедентов."""
    query = {str(word).strip().lower() for word in (keywords or []) if str(word).strip()}
    if not query:
        return []
    with _DECISIONS_LOCK:
        records = read_json(DECISIONS_LOG, [])
    if not isinstance(records, list):
        return []
    matches = []
    for record in records:
        if not isinstance(record, dict) or str(record.get('outcome', '')).lower() != 'failed':
            continue
        prior = {str(word).strip().lower() for word in record.get('task_keywords', []) if str(word).strip()}
        overlap = query & prior
        if overlap:
            item = dict(record)
            item['matched_keywords'] = sorted(overlap)
            matches.append(item)
    matches.sort(key=lambda item: (int(item.get('weight', 0) or 0), str(item.get('timestamp', ''))), reverse=True)
    return matches[:3]


def _record_task_outcome(task, status):
    """Записать результат задачи с учётом найденных ранее рисков."""
    keywords = extract_task_keywords(str(task.get('title', '')) + ' ' + str(task.get('description', '')))
    risks = task.get('risk_history') if isinstance(task.get('risk_history'), list) else search_risks(keywords)
    active = [risk for risk in risks if isinstance(risk, dict) and int(risk.get('weight', 0) or 0) > 5]
    task_id = str(task.get('id', ''))
    if status == 'completed':
        if active:
            log_decision(keywords, 'task_completion', 'passed', 5,
                         'Задача завершена несмотря на ранее найденный риск: ' + str(active[0].get('reason', ''))[:500],
                         task_id=task_id)
        return
    if status != 'failed':
        return
    if active:
        prior = active[0]
        previous_weight = int(prior.get('weight', 0) or 0)
        weight = 50 if previous_weight >= 25 else min(50, max(10, previous_weight * 2))
        log_decision(keywords, str(prior.get('action_taken') or 'task_execution'), 'failed', weight,
                     'Повторный сбой при ранее известном риске. Предыдущая причина: ' + str(prior.get('reason', ''))[:700]
                     + '. Ошибка задачи: ' + str(task.get('error', ''))[:300],
                     requires_human=(previous_weight >= 25 or weight >= 25), task_id=task_id)
    else:
        log_decision(keywords, 'task_execution', 'failed', 10,
                     'Новая ошибка выполнения задачи: ' + str(task.get('error', ''))[:900],
                     task_id=task_id)

MEMORY_DIR = DATA / 'memory'
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_FACTS_LIMIT = 15
MEMORY_TASKS_LIMIT = 50


def _empty_project_memory(project_id):
    return {
        'project_id': project_id, 'updated_at': '', 'summary': '',
        'constraints': [], 'facts': [], 'open_questions': [], 'next_steps': [], 'chats': [],
        'task_ids': [], 'agent_ids': [],
    }


def _project_memory_path(project_id):
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(project_id))[:80]
    return MEMORY_DIR / (safe_id + '.json')


def read_project_memory(project_id: str) -> dict:
    if not project_id:
        return _empty_project_memory('')
    path = _project_memory_path(project_id)
    data = read_json(path, None)
    if not isinstance(data, dict):
        return _empty_project_memory(project_id)
    defaults = _empty_project_memory(project_id)
    for key, default in defaults.items():
        if key not in data or (isinstance(default, list) and not isinstance(data[key], list)):
            data[key] = default.copy() if isinstance(default, list) else default
    return data


def write_project_memory(project_id: str, memory: dict):
    if not project_id:
        return
    memory['project_id'] = project_id
    memory['updated_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    if isinstance(memory.get('facts'), list):
        memory['facts'] = memory['facts'][-MEMORY_FACTS_LIMIT:]
    if isinstance(memory.get('task_ids'), list):
        memory['task_ids'] = memory['task_ids'][-MEMORY_TASKS_LIMIT:]
    if isinstance(memory.get('agent_ids'), list):
        memory['agent_ids'] = list(dict.fromkeys(memory['agent_ids']))[-50:]
    write_json(_project_memory_path(project_id), memory)


def _append_project_memory_fact(memory: dict, fact: dict):
    """Append a project fact unless the same text/source is already in recent memory."""
    facts = memory.get('facts')
    if not isinstance(facts, list):
        facts = []
        memory['facts'] = facts
    for existing in reversed(facts[-MEMORY_FACTS_LIMIT:]):
        if (isinstance(existing, dict)
                and existing.get('text') == fact.get('text')
                and existing.get('source') == fact.get('source')):
            return
    facts.append(fact)


def update_project_memory_after_task(task: dict, team_result: list, agent: dict | None):
    project_id = str(task.get('project_id', '')).strip()
    if not project_id:
        return
    memory = read_project_memory(project_id)
    task_id = str(task.get('id', '')).strip()
    status = str(task.get('status', '')).lower()
    title = str(task.get('title', '')).strip()
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')

    if task_id and task_id not in memory['task_ids']:
        memory['task_ids'].append(task_id)
    if agent and agent.get('id') and agent['id'] not in memory['agent_ids']:
        memory['agent_ids'].append(agent['id'])
    for stage in (team_result or []):
        role = str(stage.get('role', '')).strip().upper()
        if role == 'MANAGER':
            continue
        for candidate in domain_items('agents'):
            if str(candidate.get('role', '')).upper() == role and candidate.get('id') and candidate['id'] not in memory['agent_ids']:
                memory['agent_ids'].append(candidate['id'])
                break

    if status == 'completed':
        last = team_result[-1] if team_result else {}
        snippet = str(last.get('response', '') or task.get('result', ''))[:200].replace('\n', ' ').strip()
        memory['summary'] = (title + ' — ' + snippet).strip(' —')[:400]
        stages = team_result[-3:] if team_result else []
        if not stages and str(task.get('result', '')).strip():
            stages = [{'role': (agent or {}).get('role', 'AGENT'), 'response': task.get('result', '')}]
        for stage in stages:
            role = str(stage.get('role', '')).strip()
            resp = str(stage.get('response', '')).strip()
            if role and resp:
                fact_text = (role + ': ' + resp[:150]).replace('\n', ' ').strip()
                _append_project_memory_fact(memory, {'text': fact_text, 'source': task_id, 'at': now})
    elif status == 'failed':
        err = str(task.get('error', ''))[:200].replace('\n', ' ')
        memory['summary'] = (title + ' — ОШИБКА: ' + err).strip(' —')[:400]
        _append_project_memory_fact(memory, {'text': 'Задача "' + title + '" завершилась ошибкой: ' + err, 'source': task_id, 'at': now})
    write_project_memory(project_id, memory)


def _system_instruction_history_path():
    return DATA / 'system_instructions_history.json'


def _append_system_instruction_history(item):
    if not isinstance(item, dict) or not isinstance(item.get('system_prompt'), str):
        return
    history = read_json(_system_instruction_history_path(), [])
    if not isinstance(history, list):
        history = []
    history.insert(0, {
        'id': item.get('id', ''),
        'role': item.get('role', ''),
        'system_prompt': item.get('system_prompt', ''),
        'at': item.get('updated_at') or item.get('created_at') or datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    })
    write_json(_system_instruction_history_path(), history[:50])

AUTH_FILE = DATA/'auth.json'
AUTH_ENABLED = os.environ.get('PQ_AUTH_ENABLED', '0').strip().lower() in ('1', 'true', 'yes', 'on')
AUTH_ITERATIONS = 310000
AUTH_SESSIONS = {}
AUTH_SESSIONS_LOCK = threading.Lock()

def _password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, AUTH_ITERATIONS).hex()

def _ensure_auth_config():
    if AUTH_FILE.exists():
        current = read_json(AUTH_FILE, None)
        if not isinstance(current, dict) or not all(k in current for k in ('username', 'salt', 'password_hash', 'iterations')):
            raise RuntimeError('Файл data/auth.json повреждён или имеет неверный формат; восстановите его из резервной копии.')
        return
    salt = secrets.token_bytes(16)
    write_json(AUTH_FILE, {
        'username': 'root',
        'salt': salt.hex(),
        'password_hash': _password_hash('IamRootUser', salt),
        'iterations': AUTH_ITERATIONS,
        'must_change_password': True
    })

_ensure_auth_config()

def settings():
    p=DATA/'settings.json'
    if not p.exists(): write_json(p, DEFAULT_SETTINGS)
    return read_json(p, DEFAULT_SETTINGS)
def pages():
    p=PAGES/'index.json'
    current=read_json(p, DEFAULT_PAGES)
    known={item.get('id') for item in current if isinstance(item,dict)}
    changed=False
    for item in DEFAULT_PAGES:
        if item.get('system') and item.get('id') not in known:
            current.append(item.copy()); known.add(item.get('id')); changed=True
    if changed or not p.exists(): write_json(p, current)
    return current
PROVIDER_FILE = DATA/'providers.json'
CLOUD_PROVIDER_CATALOG = [
 {'id':'openai','name':'OpenAI','kind':'cloud','base_url':'https://api.openai.com/v1','format':'openai','access_format':'OpenAI-compatible REST API','builtin':True},
 {'id':'anthropic','name':'Anthropic','kind':'cloud','base_url':'https://api.anthropic.com/v1','format':'anthropic','access_format':'Anthropic Messages API','builtin':True},
 {'id':'google-gemini','name':'Google Gemini','kind':'cloud','base_url':'https://generativelanguage.googleapis.com/v1beta','format':'gemini','access_format':'Google Gemini API','builtin':True},
 {'id':'openrouter','name':'OpenRouter','kind':'cloud','base_url':'https://openrouter.ai/api/v1','format':'openai','access_format':'OpenAI-compatible API','builtin':True},
 {'id':'groq','name':'Groq','kind':'cloud','base_url':'https://api.groq.com/openai/v1','format':'openai','access_format':'OpenAI-compatible API','builtin':True}
]
def provider_items():
    defaults=[{'id':'ollama','name':'Ollama','kind':'local','base_url':OLLAMA_URL,'format':'ollama','builtin':True},{'id':'lm-studio','name':'LM Studio','kind':'local','base_url':'http://127.0.0.1:1234/v1','format':'openai','builtin':True}]
    saved=read_json(PROVIDER_FILE,[]); saved=saved if isinstance(saved,list) else []
    by_id={x.get('id'):x for x in saved if isinstance(x,dict)}
    items=[{**p,**by_id.get(p['id'],{}),'builtin':True} for p in defaults+CLOUD_PROVIDER_CATALOG]
    for p in saved:
        if isinstance(p,dict) and p.get('id') not in {x['id'] for x in items}: items.append(p)
    return items
def get_local_gguf(model_path, n_ctx=4096, n_gpu_layers=-1):
    """Load and cache a local GGUF model; serialize inference access."""
    if Llama is None:
        raise RuntimeError("Библиотека llama-cpp-python не установлена. Выполните: pip install llama-cpp-python")
    path = Path(str(model_path or '')).expanduser()
    if not path.is_file() or path.suffix.lower() != '.gguf':
        raise ValueError("Укажите существующий локальный файл модели с расширением .gguf")
    resolved = str(path.resolve())
    ctx = max(512, min(int(n_ctx or 4096), 131072))
    gpu_layers = max(-1, min(200, int(n_gpu_layers if n_gpu_layers is not None else -1)))
    cache_key = (resolved, ctx, gpu_layers)
    with _LOCAL_GGUF_LOCK:
        model = _LOCAL_GGUF_MODELS.get(cache_key)
        if model is None:
            model = Llama(model_path=resolved, n_ctx=ctx, n_gpu_layers=gpu_layers, verbose=False)
            _LOCAL_GGUF_MODELS[cache_key] = model
        return model


def provider_models(p):
    if str(p.get('kind') or '') == 'file' or str(p.get('format') or '') == 'gguf':
        path = Path(str(p.get('base_url') or '')).expanduser()
        if path.is_file() and path.suffix.lower() == '.gguf':
            return [{'name': path.name, 'size': path.stat().st_size, 'parameter_size': 'GGUF'}]
        return []
    base=str(p.get('base_url','')).rstrip('/'); fmt=p.get('format','openai'); headers={'User-Agent':'PQlocalAgentOSv3'}
    key=str(p.get('api_key','')).strip()
    if key: headers['Authorization']='Bearer '+key
    if fmt=='ollama':
        req=urllib.request.Request(base+'/api/tags',headers=headers)
        with urllib.request.urlopen(req,timeout=1.5) as r: raw=json.loads(r.read())
        return [{'name':x.get('name',''),'size':x.get('size',0),'parameter_size':(x.get('details') or {}).get('parameter_size','—')} for x in raw.get('models',[]) if x.get('name')]
    if fmt=='anthropic':
        if not key: return []
        headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
        req=urllib.request.Request(base+'/models',headers=headers)
        with urllib.request.urlopen(req,timeout=3) as r: raw=json.loads(r.read())
        return [{'name':x.get('id','')} for x in raw.get('data',[]) if x.get('id')]
    if fmt=='gemini':
        if not key: return []
        req=urllib.request.Request(base+'/models?key='+urllib.parse.quote(key),headers=headers)
        with urllib.request.urlopen(req,timeout=3) as r: raw=json.loads(r.read())
        return [{'name':x.get('name','').removeprefix('models/')} for x in raw.get('models',[]) if x.get('name') and 'generateContent' in x.get('supportedGenerationMethods',[])]
    req=urllib.request.Request(base+'/models',headers=headers)
    with urllib.request.urlopen(req,timeout=1.5) as r: raw=json.loads(r.read())
    return [{'name':x.get('id','')} for x in raw.get('data',[]) if x.get('id')]
def public_provider(p):
    return {k:v for k,v in p.items() if k!='api_key'} | {'api_key_set':bool(p.get('api_key'))}
def agent_ssh_context(agent):
    permissions = agent.get('permissions') if isinstance(agent, dict) and isinstance(agent.get('permissions'), dict) else {}
    if not permissions.get('ssh_access'):
        return ''
    stored = read_json(DATA/'ssh_connections.json', [])
    entries = stored.get('connections', []) if isinstance(stored, dict) else stored
    if not isinstance(entries, list):
        return '\n\nSSH-подключения недоступны: реестр имеет неверный формат.'
    visible = [
        {'connection_id': str(item.get('id','')), 'host': str(item.get('host','')), 'port': int(item.get('port',22) or 22), 'username': str(item.get('username',''))}
        for item in entries if isinstance(item, dict) and item.get('id') and item.get('host')
    ][:100]
    if not visible:
        return '\n\nSSH-разрешение включено, но подключений нет. Пользователь должен сохранить подключения кнопкой «Сохранить на сервер» на странице SSH.'
    return '\n\nДОСТУПНЫЕ SSH-ПОДКЛЮЧЕНИЯ (используй connection_id точно как указан):\n' + json.dumps(visible, ensure_ascii=False)


def grant_project_folder_to_agents(raw_path):
    """Automatically add the selected local project folder to agent file-access roots."""
    folder = Path(str(raw_path or '').strip()).expanduser().resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('Путь к рабочей папке должен указывать на существующую папку.')
    current = permission_settings()
    roots = [str(x) for x in current.get('roots', []) if str(x).strip()]
    normalized = str(folder)
    if not any(os.path.normcase(os.path.abspath(x)) == os.path.normcase(normalized) for x in roots):
        roots.append(normalized)
    current['roots'] = roots
    current['local_files'] = True
    write_json(DATA/'permissions.json', current)
    # Project folder access is automatic: enable read/write file tools for agents.
    agents_path = DOMAIN_FILES['agents']
    agents = read_json(agents_path, [])
    if isinstance(agents, list):
        changed = False
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            permissions = agent.get('permissions') if isinstance(agent.get('permissions'), dict) else DEFAULT_AGENT_PERMISSIONS.copy()
            for permission in ('file_loading', 'file_saving'):
                if not permissions.get(permission):
                    permissions[permission] = True
                    changed = True
            agent['permissions'] = permissions
        if changed:
            write_json(agents_path, agents)
    log_event('permissions.project_folder.granted', normalized)
    return normalized


def permission_settings():
    current=read_json(DATA/'permissions.json', {'local_files':False,'roots':[]})
    if not isinstance(current,dict): current={'local_files':False,'roots':[]}
    current['local_files']=bool(current.get('local_files',False))
    current['roots']=current.get('roots',[]) if isinstance(current.get('roots',[]),list) else []
    return current
def log_event(action, detail=''):
    path=DATA/'events.json'; events=read_json(path, [])
    events.insert(0, {'time':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'action':action,'detail':str(detail)[:300]})
    write_json(path, events[:500])
OLLAMA_URL = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
DOMAIN_FILES = {'agents': DATA/'agents.json', 'projects': DATA/'projects.json', 'tasks': DATA/'tasks.json'}
AGENT_ROLES = ['MANAGER','DISPATCHER','ARCHITECT','ANALYST','CODER','DESIGNER','COPYWRITER','TESTER','DEVOPS']
AGENT_ROLES_FILE = DATA / 'agent_roles.json'
AGENT_ROLE_DISPLAY_NAMES = {'MANAGER':'Менеджер','DISPATCHER':'Диспетчер','ARCHITECT':'Архитектор','ANALYST':'Аналитик','DESIGNER':'Дизайнер','COPYWRITER':'Копирайтер','CODER':'Разработчик','TESTER':'Тестировщик','DEVOPS':'DevOps-инженер'}
AGENT_PERMISSION_KEYS = {'file_loading','file_saving','file_moving','file_deletion','directory_creation','directory_deletion','directory_moving','github_access','terminal_access','web_access','ssh_access'}
DEFAULT_AGENT_PERMISSIONS = {key:False for key in AGENT_PERMISSION_KEYS}


def _normalize_agent_permissions(value):
    """Validate the permissions container and retain only supported permission keys."""
    if not isinstance(value, dict):
        raise ValueError('Некорректные разрешения агента: поле "permissions" должно быть объектом.')
    return {**DEFAULT_AGENT_PERMISSIONS, **{key: bool(enabled) for key, enabled in value.items() if key in AGENT_PERMISSION_KEYS}}
AGENT_ROLE_PROMPTS = {
    'MANAGER':'Ты менеджер проекта и руководитель Агент №1. Анализируй цель и результаты диспетчера и профильных агентов, определяй приоритеты, утверждай план и принимай итоговое решение. Не теряй пункты памяти проекта.',
    'DISPATCHER':'Ты диспетчер системы. Единственная точка маршрутизации запросов, задач, артефактов и памяти проекта. Собери полный контекст памяти (сводка, ограничения, вопросы, следующие шаги, факты), определи нужные роли, передай менеджеру структурированный отчёт. Не подменяй решения менеджера и не выдумывай результаты.',
    'ARCHITECT':'Ты системный архитектор. Проектируй модульную структуру, контракты, потоки данных, ограничения и точки отказа. Не выдумывай существующие API.',
    'ANALYST':'Ты аналитик. Разделяй факты, предположения и рекомендации; проверяй полноту требований и формулируй выводы структурированно.',
    'DESIGNER':'Ты продуктовый и интерфейсный дизайнер. Учитывай сценарии пользователя, доступность, адаптивность, визуальную иерархию и единообразие компонентов.',
    'COPYWRITER':'Ты редактор и технический автор. Пиши ясно, конкретно, на языке пользователя; сохраняй смысл и не выдумывай факты.',
    'CODER':'Ты разработчик-программист. Реализуй утверждённые требования, соблюдай архитектуру и контракты, учитывай ошибки, безопасность, тесты и сопровождение. Не утверждай, что код запущен, если это не так.',
    'TESTER':'Ты инженер по тестированию. Ищи граничные случаи, регрессии, ошибки обработки данных, безопасность и воспроизводимые критерии приёмки.',
    'DEVOPS':'Ты инженер инфраструктуры. Учитывай воспроизводимые сборки, конфигурацию окружения, логи, мониторинг, откат и минимальные привилегии.'
}

ORCHESTRATOR_JSON_INSTRUCTION = '''
ФОРМАТ ОТВЕТА — строго JSON, без markdown, без пояснений:
{"done": false, "next_role": "<роль>", "task": "<что должен сделать агент>", "reason": "<почему>"}
или, если работа завершена:
{"done": true, "final_answer": "<итоговый ответ пользователю>"}

Правила:
- "next_role" — одна из ролей: MANAGER, DISPATCHER, ARCHITECT, ANALYST, CODER, DESIGNER, COPYWRITER, TESTER, DEVOPS.
- Если нужной роли нет в активных, используй fallback_role из плана взаимодействия.
- Не вызывай одну и ту же роль дважды без причины.
- Если задача выполнена — верни {"done": true, "final_answer": "..."}.
'''

SYSTEM_INSTRUCTIONS_FILE = DATA / 'system_instructions.json'
SYSTEM_INSTRUCTION_ACTIVITY = {
    'MANAGER': "Координация проекта, распределение задач, контроль сроков и приоритетов",
    'DISPATCHER': "Маршрутизация запросов, задач, артефактов и памяти; передача сводного отчёта менеджеру",
    'ARCHITECT': "Проектирование модульной структуры, контрактов, потоков данных",
    'ANALYST': "Анализ требований, проверка полноты, разделение фактов и предположений",
    'DESIGNER': "Проектирование интерфейсов, доступность, визуальная иерархия",
    'COPYWRITER': "Тексты, редактура, ясность и конкретность формулировок",
    'CODER': "Написание и ревью кода, тесты, безопасность, сопровождение",
    'TESTER': "Поиск граничных случаев, регрессий, критериев приёмки",
    'DEVOPS': "Инфраструктура, сборки, конфигурация, мониторинг, откат"
}
SYSTEM_INSTRUCTION_ROLE_NAMES = {
    'MANAGER': 'Менеджер проекта', 'DISPATCHER': 'Диспетчер', 'ARCHITECT': 'Архитектор',
    'ANALYST': 'Аналитик', 'DESIGNER': 'Дизайнер',
    'COPYWRITER': 'Копирайтер', 'CODER': 'Инженер-программист',
    'TESTER': 'Тестировщик', 'DEVOPS': 'DevOps-инженер'
}
SYSTEM_INSTRUCTION_PROMPTS = {
    'MANAGER': """Ты — MANAGER, центральный оркестратор команды ИИ-агентов. Твоя задача — принимать цель пользователя, превращать её в управляемый план, назначать работу подходящим ролям и собирать проверяемый итог. Ты не должен автоматически выполнять всю специализированную работу сам, если её можно корректно делегировать.

Сначала определи ожидаемый результат, ограничения, критерии готовности и недостающие данные. Разделяй подтверждённые факты, предположения и вопросы. Если без уточнения нельзя безопасно продолжать, запроси конкретное уточнение; если можно двигаться дальше, явно зафиксируй разумные допущения.

Декомпозируй задачу на небольшие этапы с понятными входами, выходами и зависимостями. Для архитектуры и контрактов направляй работу ARCHITECT; для сбора требований и анализа — ANALYST; для пользовательских сценариев и интерфейса — DESIGNER; для текстов — COPYWRITER; для реализации — CODER; для независимой проверки — TESTER; для инфраструктуры, сборки и развёртывания — DEVOPS. Назначай только необходимые роли и учитывай, какие исполнители действительно доступны.

Передавая задачу агенту, формулируй конкретный ожидаемый результат, релевантный контекст, ограничения и критерии приёмки. Не выдавай предположение за результат агента. Проверяй полноту возвращённых результатов, соответствие исходной цели и наличие доказательств выполнения. При ошибке определи, кому нужно вернуть работу, и передай исполнителю конкретный дефект или недостающий пункт.

Учитывай зависимости: архитектурные решения и требования должны быть согласованы до реализации; код после изменения должен пройти подходящие проверки; развёртывание допускается только при наличии готового и проверенного артефакта и необходимых разрешений. Если нужной роли нет, используй предусмотренный fallback и сообщи об ограничении. Не заявляй, что тест, команда, API-запрос или развёртывание успешно выполнены, если это не подтверждено фактическим результатом.

Веди работу последовательно, отслеживай завершённые и незавершённые этапы, блокеры, риски и изменения требований. Не допускай бесконечной передачи задач между агентами: повторяй попытку только с конкретной причиной и новым критерием проверки. Сохраняй безопасность, минимальные привилегии и данные пользователя; не выполняй разрушительные действия без явного разрешения. В финале дай краткое, но содержательное резюме: что сделано, что проверено, какие файлы или результаты получены, что не выполнено, какие риски и следующие шаги остаются.""",
    'ARCHITECT': """Ты — ARCHITECT, технический архитектор системы. Отвечай за структуру решения, границы модулей, контракты API, потоки данных, зависимости, безопасность, масштабируемость и отказоустойчивость. Начинай с изучения существующего проекта и его ограничений; не выдумывай файлы, интерфейсы, сервисы или API, наличие которых не подтверждено.

Опиши компоненты и ответственность каждого из них, взаимодействие между компонентами, форматы запросов и ответов, состояния и обработку ошибок. Отделяй обязательные требования от вариантов реализации. Учитывай обратную совместимость, миграцию данных, конфигурацию, наблюдаемость и тестируемость. Предпочитай минимальные согласованные изменения вместо переписывания работающих частей.

Для предложенной архитектуры укажи ключевые решения и причины выбора, альтернативы при существенных компромиссах, риски, точки отказа и критерии приёмки. Проверь, что решения согласуются с текущим стеком и ограничениями проекта. Не внедряй скрытые зависимости и не расширяй объём работ без необходимости. Передавай CODER достаточно конкретную схему реализации, а TESTER — проверяемые свойства и сценарии. Если данных недостаточно, перечисли конкретные вопросы и явно пометь предположения.""",
    'ANALYST': """Ты — ANALYST, бизнес- и системный аналитик. Преобразуй запрос пользователя в однозначные требования, сценарии использования, ограничения, бизнес-правила и критерии приёмки. Разделяй факты из источников, выводы, предположения и неизвестные сведения; не заполняй пробелы выдуманными фактами.

Определи цель, пользователей, входные данные, ожидаемые результаты, исключения, граничные случаи и зависимости. Для неоднозначностей предложи короткие уточняющие вопросы, ранжируя их по влиянию на решение. Если работа может продолжаться с безопасными допущениями, перечисли эти допущения отдельно.

Представляй требования структурированно и проверяемо: формулируй условия и ожидаемое поведение, а не расплывчатые пожелания. Проверяй непротиворечивость требований, выявляй пробелы, дублирование и конфликтующие ограничения. Для API фиксируй поля, типы, обязательность, ограничения и ошибки; для интерфейса — сценарии и состояния; для данных — правила сохранения и миграции. Подготовь CODER и ARCHITECT ясный набор требований, а TESTER — сценарии проверки и критерии успешного результата. Указывай источник каждого существенного требования и не утверждай, что требование реализовано, пока это не проверено.""",
    'DESIGNER': """Ты — DESIGNER, специалист по UI/UX и визуальной системе продукта. Проектируй интерфейс вокруг задач пользователя, понятной иерархии, предсказуемых действий и доступности. Соблюдай существующие дизайн-токены, структуру страниц, общие компоненты и настройки интерфейса; не добавляй локальные CSS-исключения, если проблему можно решить системно.

Для каждого сценария продумай состояния загрузки, успеха, ошибки, пустого результата, недоступности и подтверждения опасного действия. Используй понятные подписи, единообразные кнопки, видимую обратную связь, корректные фокус-состояния, клавиатурную навигацию и достаточный контраст. Учитывай адаптивность, длинный текст, масштабирование и переполнение контейнеров.

Перед предложением изменения изучи существующие страницы и компоненты, чтобы не создавать дубликаты. Описывай конкретные изменения, затрагиваемые компоненты, состояния и критерии визуальной приёмки. Не подменяй функциональные требования декоративными решениями и не удаляй привычные действия без согласования. Передавай CODER спецификацию поведения и стилей, а TESTER — сценарии проверки интерфейса на разных состояниях и ширинах экрана.""",
    'COPYWRITER': """Ты — COPYWRITER, эксперт по текстам интерфейса, технической документации и редактуре. Пиши ясно, конкретно, последовательно и на языке пользователя. Сохраняй исходный смысл и факты; не добавляй неподтверждённых возможностей, гарантий, сроков или результатов.

Для интерфейса используй короткие подписи действий, понятные заголовки, полезные сообщения об ошибках и инструкции, объясняющие следующий шаг. Избегай неопределённых формулировок, канцелярита, повторов и перегруженных описаний. Сохраняй единую терминологию по всему продукту; если термин уже закреплён в проекте, не заменяй его произвольным синонимом.

Для документации указывай назначение, предпосылки, последовательность действий, ожидаемый результат и ограничения. Отличай инструкцию от рекомендации и подтверждённое поведение от планируемого. При редактировании не меняй технические идентификаторы, имена полей, API-контракты и кодовые примеры без явного задания. Если исходных данных недостаточно, обозначь пробел и запроси источник вместо того, чтобы домысливать содержание.""",
    'CODER': """Ты — CODER, старший инженер-программист. Реализуй согласованные требования в существующем коде, сохраняя архитектуру, совместимость и работающие функции. Перед изменением изучи связанные файлы, точки входа, контракты и тесты. Не переписывай несвязанные участки и не удаляй существующее поведение ради упрощения.

Вноси небольшие, целенаправленные изменения. Соблюдай стиль проекта, валидацию входных данных, обработку ошибок, безопасность, логирование и правила хранения данных. Не обходи авторизацию и разрешения. Не добавляй новые зависимости без необходимости. Для миграций сохраняй пользовательские данные и обеспечивай повторяемость безопасных преобразований.

После изменения выполни доступные статические проверки и тесты, изучи diff и проверь регрессии в затронутых сценариях. Ясно отделяй выполненные проверки от тех, которые не удалось запустить. Никогда не утверждай, что сервер, API, браузерный сценарий или команда успешно отработали без фактического запуска. В отчёте перечисли изменённые файлы, ключевые изменения, результаты проверок и оставшиеся риски. Если требование неоднозначно или конфликтует с ограничением проекта, сообщи об этом до рискованного изменения.""",
    'TESTER': """Ты — TESTER, инженер по обеспечению качества. Проверяй соответствие реализации требованиям, находи регрессии, ошибки обработки данных, проблемы безопасности и граничные случаи. Строй проверки по критериям приёмки и фактическому поведению системы, а не по предположению, что код должен работать.

Для каждого сценария указывай предусловия, входные данные, действие и ожидаемый результат. Проверяй корректные, пустые, неверные, чрезмерно длинные и отсутствующие значения; границы лимитов; ошибки зависимостей; повторные запросы; сохранение данных после перезапуска; права доступа; обратную совместимость и состояния интерфейса. Для API проверяй коды ответов, структуру JSON и отсутствие побочных изменений при ошибке.

Отделяй найденный дефект от потенциального риска. Для каждого дефекта приводи воспроизводимые шаги, фактический и ожидаемый результат, серьёзность и затронутую область. Не называй проверку пройденной, если она не запускалась. После исправления повтори исходный сценарий и подходящие регрессионные тесты. Передавай CODER минимальный воспроизводимый отчёт и подтверждай итог только на основании наблюдаемых результатов.""",
    'DEVOPS': """Ты — DEVOPS, инженер по инфраструктуре и CI/CD. Отвечай за воспроизводимость запуска и сборки, конфигурацию окружения, управление секретами, логи, мониторинг, развёртывание и безопасный откат. Учитывай целевую ОС, фактический способ запуска проекта и ограничения доступной среды; не предполагай наличие Docker, облачных сервисов или внешней инфраструктуры без подтверждения.

Предпочитай повторяемые команды и явные настройки окружения. Не помещай пароли, токены и другие секреты в код, логи или репозиторий. Проверяй зависимости, порты, права файлов, таймауты, готовность сервисов и диагностические сообщения. Для CI/CD определяй этапы проверки, сборки, публикации и развёртывания, а также условия остановки при ошибке.

Перед запуском оцени влияние на данные и активные процессы. Для потенциально разрушительных операций требуй резервного копирования и явного разрешения; предусмотри безопасный откат. Проверяй состояние сервиса по реальному health-check и журналам, а не только по коду возврата команды. В отчёте указывай выполненные команды, фактические результаты, конфигурационные изменения, риски и инструкции восстановления. Не заявляй об успешном развёртывании, если оно не выполнялось.""",
};

def read_system_prompt_template(role: str) -> str:
    """Читает agents/templates/{ROLE}.md; встроенный словарь остаётся fallback."""
    role = str(role).strip().upper()
    if role not in AGENT_ROLES:
        raise ValueError('Неизвестная роль: ' + role)
    path = TEMPLATES_DIR / (role + '.md')
    try:
        text = path.read_text(encoding='utf-8').strip()
        if text:
            return text
    except (OSError, UnicodeError):
        pass
    return SYSTEM_INSTRUCTION_PROMPTS.get(role, '')


def read_all_system_prompt_templates() -> dict:
    """Возвращает актуальные тексты шаблонов для всех восьми ролей."""
    result = {}
    for role in AGENT_ROLES:
        try:
            result[role] = read_system_prompt_template(role)
        except Exception:
            result[role] = SYSTEM_INSTRUCTION_PROMPTS.get(role, '')
    return result


def initialize_system_prompt_templates():
    """Создаёт каталог шаблонов и журналирует отсутствующие файлы, не прерывая запуск."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for role in AGENT_ROLES:
        if not (TEMPLATES_DIR / (role + '.md')).is_file():
            log_event('system_instruction.template_missing', role)

def system_instruction_agent_plan():
    return [
        {'from':'MANAGER','trigger':'task_received','condition':'Задача получена','action_instruction':'Выполнить работу и вернуть результат','target_role':'MANAGER','fallback_role':''},
        {'from':'MANAGER','trigger':'need_clarification','condition':'Не хватает данных','action_instruction':'Запросить уточнение у MANAGER','target_role':'MANAGER','fallback_role':''}
    ]
MANAGER_DEFAULT_INTERACTION_PLAN = [
    {'trigger':'new_task','condition':'Есть ARCHITECT','action_instruction':'Декомпозиция, отправка на архитектурное проектирование','target_role':'ARCHITECT','fallback_role':'ANALYST'},
    {'trigger':'new_task','condition':'Нет ARCHITECT, есть ANALYST','action_instruction':'Сбор и структурирование требований','target_role':'ANALYST','fallback_role':'CODER'},
    {'trigger':'spec_ready','condition':'Есть CODER','action_instruction':'Постановка задачи на разработку','target_role':'CODER','fallback_role':''},
    {'trigger':'code_written','condition':'Есть TESTER','action_instruction':'Отправка кода на тестирование и ревью','target_role':'TESTER','fallback_role':'MANAGER'},
    {'trigger':'tests_failed','condition':'Есть CODER','action_instruction':'Отправка баг-репорта на исправление','target_role':'CODER','fallback_role':''},
    {'trigger':'artifact_ready','condition':'Есть DEVOPS','action_instruction':'Постановка задачи на деплой / CI/CD','target_role':'DEVOPS','fallback_role':''}
]
def ensure_system_instructions():
    if SYSTEM_INSTRUCTIONS_FILE.exists():
        current = read_json(SYSTEM_INSTRUCTIONS_FILE, None)
        if isinstance(current, dict) and isinstance(current.get('instructions'), list):
            instructions = current['instructions']
            changed = False
            migrated = 0
            for item in instructions:
                if not isinstance(item, dict):
                    continue
                # Пользовательские инструкции миграция не меняет.
                if item.get('is_default') is not True:
                    continue
                role = item.get('role')
                if role in ('DevOps', 'DEVOPS-инженер', 'DevOps-инженер'):
                    item['role'] = 'DEVOPS'
                    role = 'DEVOPS'
                    changed = True
                if role not in AGENT_ROLES:
                    continue
                item_changed = False
                if role == 'MANAGER':
                    if item.get('interaction_plan') == []:
                        item['interaction_plan'] = [dict(rule) for rule in MANAGER_DEFAULT_INTERACTION_PLAN]
                        item_changed = True
                    elif isinstance(item.get('interaction_plan'), list):
                        # Мигрируем ранее сохранённые имена полей без потери настроенных правил.
                        legacy_keys = {'to': 'target_role', 'fallback': 'fallback_role', 'action': 'action_instruction'}
                        migrated_plan = []
                        for rule in item['interaction_plan']:
                            if not isinstance(rule, dict):
                                migrated_plan.append(rule)
                                continue
                            migrated_rule = dict(rule)
                            for legacy_key, current_key in legacy_keys.items():
                                if current_key not in migrated_rule and legacy_key in migrated_rule:
                                    migrated_rule[current_key] = migrated_rule[legacy_key]
                                migrated_rule.pop(legacy_key, None)
                            migrated_rule.pop('from', None)
                            migrated_plan.append(migrated_rule)
                        try:
                            normalized = validate_manager_interaction_plan(migrated_plan)
                        except ValueError:
                            normalized = migrated_plan
                        if item.get('interaction_plan') != normalized:
                            item['interaction_plan'] = normalized
                            item_changed = True
                else:
                    fixed_plan = system_instruction_agent_plan()
                    if item.get('interaction_plan') != fixed_plan:
                        item['interaction_plan'] = [dict(rule) for rule in fixed_plan]
                        item_changed = True
                if not str(item.get('system_prompt', '')).strip():
                    item['system_prompt'] = read_system_prompt_template(role)
                    item_changed = True
                if role == 'DEVOPS':
                    expected_name = SYSTEM_INSTRUCTION_ROLE_NAMES['DEVOPS'] + ' (по умолчанию)'
                    if item.get('name') != expected_name:
                        item['name'] = expected_name
                        item_changed = True
                if item_changed:
                    item['updated_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                    changed = True
                    migrated += 1
            if changed:
                save_system_instructions(instructions)
                log_event('system_instruction.migrate', str(migrated) + ' instructions')
            return instructions
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    instructions = []
    for role in AGENT_ROLES:
        plan = [dict(rule) for rule in MANAGER_DEFAULT_INTERACTION_PLAN] if role == 'MANAGER' else system_instruction_agent_plan()
        instructions.append({
            'id': 'instr-' + role.lower(),
            'name': SYSTEM_INSTRUCTION_ROLE_NAMES[role] + ' (по умолчанию)',
            'role': role, 'system_prompt': read_system_prompt_template(role),
            'activity': SYSTEM_INSTRUCTION_ACTIVITY[role], 'is_default': True,
            'interaction_plan': plan, 'created_at': now, 'updated_at': now
        })
    write_json(SYSTEM_INSTRUCTIONS_FILE, {'instructions': instructions})
    return instructions
def save_system_instructions(items):
    write_json(SYSTEM_INSTRUCTIONS_FILE, {'instructions': items})
def system_instruction_defaults():
    prompts = read_all_system_prompt_templates()
    return {role: {'system_prompt': prompts[role], 'activity': SYSTEM_INSTRUCTION_ACTIVITY[role]} for role in AGENT_ROLES}
def ensure_agent_roles():
    """Load persisted agent roles and seed missing built-ins without initializing instruction storage."""
    current = read_json(AGENT_ROLES_FILE, [])
    if not isinstance(current, list):
        current = []
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    changed = False

    # Repair only missing values; preserve customized prompts and activity descriptions.
    for item in current:
        if not isinstance(item, dict):
            continue
        code = str(item.get('code', '')).upper()
        if code not in AGENT_ROLES:
            continue
        if not str(item.get('activity', '')).strip():
            item['activity'] = SYSTEM_INSTRUCTION_ACTIVITY.get(code, '')
            changed = True
        if not str(item.get('system_prompt', '')).strip():
            item['system_prompt'] = SYSTEM_INSTRUCTION_PROMPTS.get(code, AGENT_ROLE_PROMPTS.get(code, ''))
            changed = True

    known = {str(x.get('code', '')).upper() for x in current if isinstance(x, dict)}
    for code in AGENT_ROLES:
        if code in known:
            continue
        current.append({
            'id': code, 'code': code, 'name': AGENT_ROLE_DISPLAY_NAMES.get(code, code),
            'activity': SYSTEM_INSTRUCTION_ACTIVITY.get(code, ''),
            'system_prompt': SYSTEM_INSTRUCTION_PROMPTS.get(code, AGENT_ROLE_PROMPTS.get(code, '')),
            'is_system': True, 'created_at': now, 'updated_at': now
        })
        changed = True
    if changed:
        write_json(AGENT_ROLES_FILE, current)
    return current

def save_agent_roles(items):
    write_json(AGENT_ROLES_FILE, items)

def sync_builtin_agent_role(code, name, activity, system_prompt, now):
    if code not in AGENT_ROLES:
        return
    roles = read_json(AGENT_ROLES_FILE, [])
    if not isinstance(roles, list):
        return
    item = next((x for x in roles if isinstance(x, dict) and x.get('code') == code), None)
    if not item:
        return
    item.update({'name': str(name).replace(' (по умолчанию)', ''), 'activity': str(activity), 'system_prompt': str(system_prompt), 'updated_at': now})
    save_agent_roles(roles)

def validate_manager_interaction_plan(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError('План взаимодействия MANAGER должен быть массивом не более 50 правил')
    validated = []
    limits = {'trigger': 120, 'condition': 240, 'action_instruction': 1000}
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError('Правило ' + str(index + 1) + ' должно быть объектом')
        target = row.get('target_role', 'MANAGER')
        fallback = row.get('fallback_role', '')
        if not isinstance(target, str) or not isinstance(fallback, str):
            raise ValueError('target_role и fallback_role в правиле ' + str(index + 1) + ' должны быть строками')
        target = target.upper().strip()
        fallback = fallback.upper().strip()
        if len(target) > 80 or len(fallback) > 80:
            raise ValueError('target_role и fallback_role в правиле ' + str(index + 1) + ' не должны превышать 80 символов')
        item = {'target_role': target, 'fallback_role': fallback}
        for key, limit in limits.items():
            text_value = row.get(key, '')
            if not isinstance(text_value, str):
                raise ValueError('Поле ' + key + ' в правиле ' + str(index + 1) + ' должно быть строкой')
            if len(text_value) > limit:
                raise ValueError('Поле ' + key + ' в правиле ' + str(index + 1) + ' превышает ' + str(limit) + ' символов')
            item[key] = text_value.strip()
        validated.append(item)
    return validated
def system_instruction_warnings(items):
    warnings = []
    for manager in items:
        if manager.get('role') != 'MANAGER':
            continue
        for rule in manager.get('interaction_plan', []):
            if not isinstance(rule, dict):
                continue
            trigger = str(rule.get('trigger', ''))
            target = str(rule.get('target_role', '')).strip()
            fallback = str(rule.get('fallback_role', '')).strip()
            if target not in AGENT_ROLES:
                warnings.append({
                    'trigger': trigger, 'target_role': target,
                    'message': 'Неизвестная целевая роль: ' + (target or '(пусто)')
                })
            elif not fallback:
                warnings.append({
                    'trigger': trigger, 'target_role': target,
                    'message': 'Правило "' + trigger + '" ведёт на ' + target + ', но fallback не задан'
                })
            if fallback and fallback not in AGENT_ROLES:
                warnings.append({
                    'trigger': trigger, 'fallback_role': fallback,
                    'message': 'Неизвестная fallback-роль: ' + fallback
                })
    return warnings

SYSTEM_AGENT_DEFINITIONS = [
    {'id':'manager','name':'Агент №1','role':'MANAGER','description':'Менеджер — руководитель системы. Анализирует сводный отчёт диспетчера и утверждает решения.','authority':1},
    {'id':'dispatcher','name':'Диспетчер','role':'DISPATCHER','description':'Единая точка маршрутизации задач, запросов, артефактов и памяти. Передаёт сводный анализ менеджеру.','authority':2},
    {'id':'architect','name':'Архитектор','role':'ARCHITECT','description':'Инженер-проектировщик: архитектура, модули, интерфейсы и контракты.','authority':3},
    {'id':'analyst','name':'Аналитик','role':'ANALYST','description':'Инженер-технолог: требования, процессы, зависимости и критерии приёмки.','authority':4},
    {'id':'developer','name':'Разработчик','role':'CODER','description':'Программист: реализация утверждённых решений.','authority':5},
    {'id':'designer','name':'Дизайнер','role':'DESIGNER','description':'Художник и проектировщик пользовательского опыта.','authority':6},
    {'id':'copywriter','name':'Копирайтер','role':'COPYWRITER','description':'Писатель и редактор текстов и документации.','authority':7},
    {'id':'tester','name':'Тестировщик','role':'TESTER','description':'Bug reporter: поиск дефектов, регрессий и проверка критериев приёмки.','authority':8},
]
def domain_items(kind):
    if kind == 'projects':
        raw_projects = read_json(DOMAIN_FILES[kind], [])
        if isinstance(raw_projects, list):
            changed = False
            for project_item in raw_projects:
                if isinstance(project_item, dict):
                    if project_item.get('env_type') not in ('local','github','ssh'):
                        project_item['env_type'] = 'local'; changed = True
                    if 'ssh_connection_id' not in project_item:
                        project_item['ssh_connection_id'] = ''; changed = True
                    if 'github_connection_id' not in project_item:
                        project_item['github_connection_id'] = ''; changed = True
                    if 'repo_name' not in project_item:
                        project_item['repo_name'] = ''; changed = True
            if changed: write_json(DOMAIN_FILES[kind], raw_projects)
    fallback=[{'id':'manager','name':'Агент №1','role':'MANAGER','model':'','status':'idle','system':True,'system_enabled':True,'description':'Менеджер — руководитель системы.'}] if kind=='agents' else []
    items = read_json(DOMAIN_FILES[kind],fallback)
    if kind == 'agents' and isinstance(items, list):
        changed = False
        by_id = {str(item.get('id')): item for item in items if isinstance(item, dict)}
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        for definition in SYSTEM_AGENT_DEFINITIONS:
            item = by_id.get(definition['id'])
            if item is None:
                item = {**definition,'model':'','status':'idle','system':True,'system_enabled':True,'permissions':DEFAULT_AGENT_PERMISSIONS.copy(),'created_at':now}
                items.append(item); by_id[definition['id']] = item; changed = True
            else:
                if not item.get('system'): item['system'] = True; changed = True
                if 'system_enabled' not in item: item['system_enabled'] = True; changed = True
                for key in ('role','authority'):
                    if item.get(key) != definition.get(key): item[key] = definition[key]; changed = True
                if item.get('id') == 'manager' and item.get('name') == 'Менеджер проекта':
                    item['name'] = 'Агент №1'; changed = True
        if changed:
            write_json(DOMAIN_FILES[kind], items)
    return items
def save_domain(kind, items): write_json(DOMAIN_FILES[kind],items)

PROJECT_LOGO_DIR = ROOT / 'project' / 'logo'
PROJECT_LOGO_DIR.mkdir(parents=True, exist_ok=True)

def save_project_logo(project_id, value, current_logo=''):
    value = str(value or '').strip()
    logo_dir = PROJECT_LOGO_DIR
    logo_dir.mkdir(parents=True, exist_ok=True)
    if value.startswith('/project/logo/'):
        name = Path(urllib.parse.unquote(value)).name
        if name.startswith(str(project_id) + '.') and (logo_dir / name).is_file():
            return '/project/logo/' + name
        if value == current_logo:
            return current_logo
        raise ValueError('Файл логотипа проекта не найден')
    existing = list(logo_dir.glob(str(project_id) + '.*'))
    if not value:
        for old_file in existing:
            try: old_file.unlink()
            except OSError: pass
        return ''
    match = re.fullmatch(r'data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/]+={0,2})', value)
    if not match or len(value) > 980000:
        raise ValueError('Некорректный логотип проекта или превышен лимит 700 КБ')
    mime, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError('Не удалось декодировать логотип проекта')
    if not raw or len(raw) > 700 * 1024:
        raise ValueError('Логотип должен быть не больше 700 КБ')
    extension = {'jpeg': 'jpg', 'png': 'png', 'webp': 'webp', 'gif': 'gif'}[mime]
    filename = str(project_id) + '.' + extension
    for old_file in existing:
        if old_file.name != filename:
            try: old_file.unlink()
            except OSError: pass
    target = logo_dir / filename
    target.write_bytes(raw)
    return '/project/logo/' + filename

def ollama_request(path, payload=None, timeout=8):
    req=urllib.request.Request(OLLAMA_URL+path,data=json.dumps(payload).encode() if payload is not None else None,method='POST' if payload is not None else 'GET',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response: return json.loads(response.read().decode('utf-8'))

def resolve_ollama_model(model, timeout=4):
    """Resolve a configured Ollama model name against installed tags."""
    requested = str(model or '').strip()[:160]
    try:
        raw = ollama_request('/api/tags', timeout=timeout)
        available = [
            str(item.get('name', '')).strip()
            for item in raw.get('models', [])
            if isinstance(item, dict) and str(item.get('name', '')).strip()
        ]
    except Exception as exc:
        raise ValueError('Не удалось получить список моделей Ollama: ' + str(exc)[:180]) from exc

    if requested in available:
        return requested

    # Agent/module configs can store provider-qualified IDs such as qwen/qwen3-8b.
    candidate = requested.rsplit('/', 1)[-1].strip() if '/' in requested else requested
    if candidate in available:
        return candidate

    # Some catalogs spell Ollama's tag separator as a hyphen (qwen3-8b),
    # while Ollama uses a colon (qwen3:8b). Try that common size-suffix form.
    ollama_candidate = re.sub(r'-(\d+(?:\.\d+)?b(?:[-:].*)?)$', r':\1', candidate, flags=re.IGNORECASE)
    if ollama_candidate != candidate and ollama_candidate in available:
        return ollama_candidate

    model_list = ', '.join(available) if available else '(нет установленных моделей)'
    raise ValueError(
        'Модель «' + (requested or '(не указана)') + '» не найдена в Ollama. '
        'Доступные модели: ' + model_list
    )


def provider_for_model(model, preferred_id=''):
    """Resolve an agent's provider, preferring an explicitly assigned GGUF runtime."""
    providers=provider_items()
    preferred=str(preferred_id or '').strip()
    name=str(model or '').strip().lower()

    # An explicit file-provider assignment is authoritative. The model field can contain
    # a display label, filename, or path depending on how the agent was configured.
    preferred_provider=next((p for p in providers if str(p.get('id',''))==preferred),None)
    if preferred_provider and (
        str(preferred_provider.get('kind') or '').lower() == 'file'
        or str(preferred_provider.get('format') or '').lower() in ('file','gguf')
    ):
        return preferred_provider

    # Resolve GGUF by its actual path/name before trusting a stale or mismatched agent provider_id.
    # Some agents store only the filename or provider display name in their model field.
    for p in providers:
        if str(p.get('kind') or '').lower() == 'file' or str(p.get('format') or '').lower() in ('file', 'gguf'):
            raw_path = str(p.get('base_url') or '').strip()
            if not raw_path:
                continue
            model_path = Path(raw_path).expanduser()
            file_names = {
                model_path.name.lower(),
                model_path.stem.lower(),
                raw_path.lower(),
                str(p.get('id') or '').lower(),
                str(p.get('name') or '').lower(),
            }
            if name in file_names or name == str(model_path.resolve()).lower():
                return p

    # Some UI/legacy agent records keep a decorated GGUF label instead of the
    # exact filename. Resolve that label locally instead of sending it to HTTP.
    if '.gguf' in name:
        file_providers=[
            p for p in providers
            if str(p.get('kind') or '').lower() == 'file'
            or str(p.get('format') or '').lower() in ('file','gguf')
        ]
        for p in file_providers:
            raw_path=str(p.get('base_url') or '').strip()
            if not raw_path:
                continue
            model_path=Path(raw_path).expanduser()
            candidates=(model_path.name.lower(),model_path.stem.lower(),str(p.get('name') or '').strip().lower())
            if any(candidate and candidate in name for candidate in candidates):
                return p
        if len(file_providers)==1:
            return file_providers[0]

    if preferred:
        match=next((p for p in providers if str(p.get('id',''))==preferred),None)
        if match:
            return match
    # Provider-qualified model IDs and provider names.
    for p in providers:
        pid=str(p.get('id','')).lower()
        pname=str(p.get('name','')).lower()
        if pid and (name.startswith(pid+'/') or name.startswith(pid+':') or name.startswith(pid+'-') or name==pid):
            return p
        if pname and (name.startswith(pname+'/') or name.startswith(pname+'-')):
            return p
    # Recognize common cloud model families even if the provider has a custom ID.
    if 'claude' in name:
        match=next((p for p in providers if p.get('format')=='anthropic' and p.get('kind')=='cloud'),None)
        if match: return match
    if 'gemini' in name:
        match=next((p for p in providers if p.get('format')=='gemini' and p.get('kind')=='cloud'),None)
        if match: return match
    if name.startswith(('gpt-','o1-','o3-','o4-')):
        match=next((p for p in providers if p.get('id')=='openai' and p.get('kind')=='cloud'),None)
        if match: return match
    if 'deepseek' in name:
        match=next((p for p in providers if 'deepseek' in (str(p.get('id',''))+' '+str(p.get('name',''))).lower() and p.get('kind')=='cloud'),None)
        if match: return match
    # Preserve known local models on Ollama. For a non-local model without an explicit
    # provider, use the sole configured custom cloud provider rather than misrouting to Ollama.
    local_prefixes=('qwen3.5:','qwen2.5-coder:','llama3.1:','nomic-embed-text:')
    if name.startswith(local_prefixes) or name in ('qwen3.5','llama3.1','nomic-embed-text'):
        return next((p for p in providers if p.get('id')=='ollama'), {'id':'ollama','name':'Ollama','kind':'local','base_url':OLLAMA_URL,'format':'ollama'})
    clouds=[p for p in providers if p.get('kind')=='cloud' and p.get('api_key') and p.get('base_url')]
    custom_clouds=[p for p in clouds if not p.get('builtin')]
    if len(custom_clouds)==1:
        return custom_clouds[0]
    if len(clouds)==1:
        return clouds[0]
    return next((p for p in providers if p.get('id')=='ollama'), {'id':'ollama','name':'Ollama','kind':'local','base_url':OLLAMA_URL,'format':'ollama'})


def _cloud_provider_error(exc):
    """Translate common provider HTTP failures into actionable Russian messages."""
    code=getattr(exc,'code',None)
    try:
        payload=json.loads(exc.read().decode('utf-8','replace'))
        detail=payload.get('error',{})
        if isinstance(detail,dict): detail=detail.get('message') or detail.get('type') or ''
        detail=str(detail or payload.get('message') or '')
    except Exception:
        detail=''
    if code in (401,403):
        return 'Ошибка облачного провайдера: неверный API-ключ или нет доступа (HTTP '+str(code)+').'
    if code==429:
        return 'Ошибка облачного провайдера: превышен лимит запросов или недостаточно средств (HTTP 429).'
    if code==404:
        return 'Ошибка провайдера: модель или endpoint не найдены (HTTP 404).'
    return 'Ошибка провайдера (HTTP '+str(code or '?')+'): '+(detail or str(getattr(exc,'reason','неизвестная ошибка')))[:220]


def send_chat_request(provider, model, messages, timeout=120, max_tokens=2048):
    """Send one non-streaming chat request to Ollama, OpenAI-compatible, Anthropic, or Gemini."""
    provider=provider if isinstance(provider,dict) else {}
    fmt=str(provider.get('format','ollama') or 'ollama').strip().lower()
    kind=str(provider.get('kind') or '').strip().lower()
    base=str(provider.get('base_url') or (OLLAMA_URL if fmt=='ollama' else '')).strip().rstrip('/')
    key=str(provider.get('api_key','') or '').strip()
    requested_model=str(model or '').strip()[:200]
    if kind == 'file' or fmt in ('file', 'gguf'):
        model_path = str(provider.get('base_url') or '').strip()
        try:
            model_obj = get_local_gguf(model_path, provider.get('n_ctx', 4096), provider.get('n_gpu_layers', -1))

            # llama-cpp-python requires any system instruction to precede the
            # conversation. The chat route can prepend project/agent context
            # independently, while the browser may also include system entries.
            # Merge them into one leading system message for GGUF only.
            gguf_messages = []
            system_parts = []
            for message in messages if isinstance(messages, list) else []:
                if not isinstance(message, dict):
                    continue
                role = str(message.get('role', '')).strip()
                content = message.get('content', '')
                if not isinstance(content, str):
                    continue
                if role == 'system':
                    if content.strip():
                        system_parts.append(content.strip())
                elif role in ('user', 'assistant'):
                    gguf_messages.append({'role': role, 'content': content})
            if system_parts:
                gguf_messages.insert(0, {'role': 'system', 'content': '\n\n'.join(system_parts)})

            if not gguf_messages:
                raise ValueError('История сообщений GGUF пуста после проверки ролей')

            with _LOCAL_GGUF_LOCK:
                output = model_obj.create_chat_completion(
                    messages=gguf_messages,
                    max_tokens=max(1, min(int(max_tokens or provider.get('max_tokens', 2048)), 8192)),
                    temperature=float(provider.get('temperature', 0.7)),
                    top_p=float(provider.get('top_p', 0.9)),
                    repeat_penalty=float(provider.get('repeat_penalty', 1.1)),
                )
            choices = output.get('choices') or []
            answer = ((choices[0].get('message') or {}).get('content') if choices else '') or ''
            if not answer.strip():
                raise RuntimeError('GGUF-модель вернула пустой ответ')
            return {'model': Path(model_path).name, 'response': answer, 'done': True}
        except Exception as exc:
            raise RuntimeError(f'Ошибка локального инференса GGUF: {exc}') from exc
    if not requested_model:
        raise ValueError('Не указана модель провайдера')
    if not base:
        raise ValueError('У провайдера не настроен base_url')
    if fmt=='ollama':
        resolved=resolve_ollama_model(requested_model)
        payload={'model':resolved,'messages':messages,'stream':False}
        try:
            req=urllib.request.Request(base+'/api/chat',data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=timeout) as response:
                raw=json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try: detail=json.loads(exc.read().decode('utf-8','replace')).get('error')
            except Exception: detail=''
            raise ValueError('Ошибка Ollama: '+str(detail or exc.reason)[:220]) from exc
        answer=(raw.get('message') or {}).get('content') if isinstance(raw,dict) else None
        if not isinstance(answer,str):
            raise ValueError('Ollama вернула ответ без текста модели')
        return {'model':raw.get('model',resolved),'response':answer,'done':bool(raw.get('done',True))}
    if fmt=='anthropic':
        if not key:
            raise ValueError('У облачного провайдера не настроен API-ключ')
        system_text='\n\n'.join(str(m.get('content','')) for m in messages if m.get('role')=='system')
        chat_messages=[{'role':m['role'],'content':m['content']} for m in messages if m.get('role') in ('user','assistant')]
        headers={'Content-Type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01','User-Agent':'PQlocalAgentOSv3'}
        body={'model':requested_model,'max_tokens':max_tokens,'messages':chat_messages}
        if system_text: body['system']=system_text
        endpoint=base+'/messages'
    elif fmt=='gemini':
        if not key:
            raise ValueError('У облачного провайдера не настроен API-ключ')
        contents=[]
        system_parts=[]
        for m in messages:
            role=m.get('role')
            if role=='system':
                system_parts.append(str(m.get('content','')))
            elif role in ('user','assistant'):
                contents.append({'role':'model' if role=='assistant' else 'user','parts':[{'text':str(m.get('content',''))}]})
        endpoint=base+'/models/'+urllib.parse.quote(requested_model.removeprefix('models/'),safe='')+':generateContent?key='+urllib.parse.quote(key)
        headers={'Content-Type':'application/json','User-Agent':'PQlocalAgentOSv3'}
        body={'contents':contents,'generationConfig':{'maxOutputTokens':max_tokens}}
        if system_parts: body['systemInstruction']={'parts':[{'text':'\n\n'.join(system_parts)}]}
    elif fmt in ('openai','openai-compatible'):
        headers={'Content-Type':'application/json','User-Agent':'PQlocalAgentOSv3'}
        if key: headers['Authorization']='Bearer '+key
        body={'model':requested_model,'messages':messages,'stream':False,'max_tokens':max_tokens}
        endpoint=base+'/chat/completions'
    else:
        raise ValueError('Неподдерживаемый формат провайдера: '+fmt)
    try:
        req=urllib.request.Request(endpoint,data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers=headers,method='POST')
        with urllib.request.urlopen(req,timeout=timeout) as response:
            raw=json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise ValueError(_cloud_provider_error(exc)) from exc
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
        raise ValueError('Провайдер недоступен: '+str(exc)[:180]) from exc
    if fmt=='anthropic':
        answer=''.join(str(x.get('text','')) for x in raw.get('content',[]) if isinstance(x,dict) and x.get('type')=='text')
    elif fmt=='gemini':
        candidates=raw.get('candidates') or []
        parts=(candidates[0].get('content') or {}).get('parts',[]) if candidates else []
        answer=''.join(str(x.get('text','')) for x in parts if isinstance(x,dict))
    else:
        choices=raw.get('choices') or []
        message=(choices[0].get('message') or {}) if choices else {}
        content=message.get('content','')
        answer=content if isinstance(content,str) else ''.join(str(x.get('text','')) for x in content if isinstance(x,dict))
    if not answer.strip():
        raise ValueError('Провайдер вернул пустой ответ')
    return {'model':requested_model,'response':answer,'done':True}



def run_diagnostics():
    checks=[]
    def check(name,status,message,detail=''):
        checks.append({'name':name,'status':status,'message':message,'detail':str(detail)[:240]})
    check('HTTP API','ok','Сервер обработал диагностический запрос.','PQlocalAgentOSv3')
    check('Каталог данных','ok' if os.access(DATA,os.R_OK|os.W_OK) else 'error','Проверены права чтения и записи.',DATA)
    check('Интерпретатор Python','ok','Интерпретатор доступен.',__import__('sys').version.split()[0])
    check('Каталог модулей','ok' if MODULES.is_dir() and os.access(MODULES,os.R_OK|os.W_OK) else 'error','Проверен каталог модулей.',MODULES)
    check('Runtime-инструменты агентов','ok' if (ROOT/'agent_tools.py').is_file() else 'error','Проверен модуль разрешённых инструментов агентов.',ROOT/'agent_tools.py')
    access=permission_settings()
    check('Файловые разрешения','ok' if access.get('local_files') and access.get('roots') else 'warning','Локальные файловые инструменты включены.' if access.get('local_files') and access.get('roots') else 'Доступ к локальным файлам выключен или не заданы разрешённые папки. Это безопасное значение по умолчанию.',DATA/'permissions.json')
    check('Настройки интерфейса','ok' if (DATA/'settings.json').is_file() else 'warning','Файл настроек существует.' if (DATA/'settings.json').is_file() else 'Будет создан при первом сохранении.',DATA/'settings.json')
    check('Реестр страниц','ok' if (PAGES/'index.json').is_file() else 'warning','Файл страниц существует.' if (PAGES/'index.json').is_file() else 'Используются системные страницы по умолчанию.',PAGES/'index.json')
    check('Реестр модулей','ok' if (DATA/'modules.json').is_file() else 'warning','Файл реестра существует.' if (DATA/'modules.json').is_file() else 'Будет создан при первом изменении каталога.',DATA/'modules.json')
    check('Журнал событий','ok' if (DATA/'events.json').is_file() and os.access(DATA/'events.json',os.R_OK|os.W_OK) else 'warning','Журнал доступен.' if (DATA/'events.json').is_file() else 'Файл журнала появится после первого события.',DATA/'events.json')
    check('Реестр агентов','ok' if DOMAIN_FILES['agents'].is_file() else 'warning','Файл агентов существует.' if DOMAIN_FILES['agents'].is_file() else 'Будет создан при сохранении первого изменения.',DOMAIN_FILES['agents'])
    check('Реестр проектов','ok' if DOMAIN_FILES['projects'].is_file() else 'warning','Файл проектов существует.' if DOMAIN_FILES['projects'].is_file() else 'Проекты ещё не сохранялись.',DOMAIN_FILES['projects'])
    check('Реестр задач','ok' if DOMAIN_FILES['tasks'].is_file() else 'warning','Файл задач существует.' if DOMAIN_FILES['tasks'].is_file() else 'Задачи ещё не сохранялись.',DOMAIN_FILES['tasks'])
    schema_path=ROOT/'module-contract.schema.json'
    check('Контракт модулей','ok' if schema_path.is_file() else 'error','JSON-схема контракта доступна.' if schema_path.is_file() else 'Не найдена JSON-схема контракта.',schema_path)
    frontend_ok=all((FRONTEND/name).is_file() for name in ('index.html','app.js','style.css','components.css'))
    check('Frontend-ресурсы','ok' if frontend_ok else 'error','HTML, JavaScript и CSS доступны.' if frontend_ok else 'Не хватает одного или нескольких файлов frontend.',FRONTEND)
    try:
        models=ollama_request('/api/tags',timeout=3).get('models',[])
        check('Сервис Ollama','ok','Локальный сервис моделей отвечает.',OLLAMA_URL)
        check('Доступность моделей','ok' if models else 'warning',f'Доступно моделей: {len(models)}.' if models else 'В Ollama пока нет установленных моделей.',', '.join(x.get('name','') for x in models[:8]) or 'Нет моделей')
    except Exception as exc:
        check('Сервис Ollama','warning','Локальный сервис моделей не отвечает.',str(exc)[:180])
        check('Доступность моделей','warning','Список моделей недоступен без работающей Ollama.',OLLAMA_URL)
    lm_url=os.environ.get('LM_STUDIO_BASE_URL','http://127.0.0.1:1234/v1').rstrip('/')
    try:
        with urllib.request.urlopen(lm_url+'/models',timeout=2.5) as response:
            status=response.status
        check('Сервис LM Studio','ok' if 200<=status<300 else 'warning',f'Локальный сервис вернул HTTP {status}.',lm_url)
    except Exception as exc:
        check('Сервис LM Studio','warning','LM Studio не запущена или недоступна; это необязательный сервис.',str(exc)[:180])
    return {'checked_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'checks':checks,'summary':{'total':len(checks),'ok':sum(x['status']=='ok' for x in checks),'warning':sum(x['status']=='warning' for x in checks),'error':sum(x['status']=='error' for x in checks)}}

GITHUB_CONNECTIONS_FILE = DATA / 'github-connections.json'

def _dpapi_crypt(value, decrypt=False):
    """Protect GitHub tokens with Windows DPAPI for the current Windows user."""
    if sys.platform != 'win32':
        raise RuntimeError('Безопасное хранение токенов поддерживается только на Windows (DPAPI).')
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

    raw = value if isinstance(value, bytes) else str(value).encode('utf-8')
    buffer_in = ctypes.create_string_buffer(raw, max(1, len(raw)))
    blob_in = DATA_BLOB(len(raw), ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 1, ctypes.byref(blob_out))
    else:
        description = ctypes.c_wchar_p('PQlocalAgentOSv3')
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), description, None, None, None, 1, ctypes.byref(blob_out))
    if not ok:
        raise OSError('DPAPI: Не удалось ' + ('расшифровать' if decrypt else 'зашифровать') + ' данные.')
    try:
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))

def github_connections():
    data = read_json(GITHUB_CONNECTIONS_FILE, {'active_id':'', 'connections':[]})
    if not isinstance(data, dict): data = {'active_id':'', 'connections':[]}
    if not isinstance(data.get('connections'), list): data['connections'] = []
    return data

def active_github_connection():
    data = github_connections()
    return next((x for x in data['connections'] if x.get('id') == data.get('active_id')), None) or (data['connections'][0] if data['connections'] else None)

def active_github_repository():
    connection = active_github_connection()
    return str(connection.get('repository') or REPO).strip() if connection else REPO

def github_token_available():
    return bool(active_github_connection() or os.environ.get('GITHUB_TOKEN'))

def github_access_token(connection=None):
    connection = connection or active_github_connection()
    if connection and connection.get('token_encrypted'):
        return _dpapi_crypt(base64.b64decode(connection['token_encrypted']), decrypt=True)
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if token: return token
    raise RuntimeError('Добавьте GitHub-подключение и укажите API-токен.')

def github_request(path, method='GET', payload=None):
    token=github_access_token()
    raw=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request('https://api.github.com'+path,data=raw,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'PQlocalAgentOSv3','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=12) as res:
            body=res.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        message='GitHub API вернул HTTP '+str(e.code)
        try: message += ': '+json.loads(e.read()).get('message','')
        except Exception: pass
        raise RuntimeError(message)

def github_public_request(path):
    req=urllib.request.Request('https://api.github.com'+path,headers={'Accept':'application/vnd.github+json','User-Agent':'PQlocalAgentOSv3','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urllib.request.urlopen(req,timeout=10) as res:
            body=res.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        message='GitHub API вернул HTTP '+str(e.code)
        try: message += ': '+json.loads(e.read()).get('message','')
        except Exception: pass
        raise RuntimeError(message)


MODULE_RUNTIME_KINDS = {'input','template','ollama','transform','output'}
def module_runtime_manifest(module):
    manifest=module.get('manifest') if isinstance(module.get('manifest'),dict) else {}
    if not manifest and (MODULES/module.get('id','')/'module.json').is_file():
        manifest=read_json(MODULES/module['id']/'module.json',{})
    return manifest if isinstance(manifest,dict) else {}

def validate_module_connections(current, connections):
    if not isinstance(connections,list) or len(connections)>300: raise ValueError('Некорректный список связей')
    modules={m.get('id'):m for m in current.get('modules',[]) if isinstance(m,dict) and isinstance(m.get('id'),str)}
    ids=set(modules); normalized=[]; seen_edges=set(); occupied_inputs=set(); adjacency={key:[] for key in ids}
    for raw in connections:
        if not isinstance(raw,dict) or not isinstance(raw.get('from'),str) or not isinstance(raw.get('to'),str) or raw.get('from') not in ids or raw.get('to') not in ids:
            raise ValueError('Связь должна соединять зарегистрированные модули')
        link=dict(raw); source=modules[link['from']]; target=modules[link['to']]
        if link['from']==link['to']: raise ValueError('Модуль не может быть соединён сам с собой')
        source_manifest=module_runtime_manifest(source); target_manifest=module_runtime_manifest(target)
        source_ports=source_manifest.get('outputs') if isinstance(source_manifest.get('outputs'),list) else []
        target_ports=target_manifest.get('inputs') if isinstance(target_manifest.get('inputs'),list) else []
        if not source_ports: link['from_port']='output'
        elif not isinstance(link.get('from_port'),str) or not link.get('from_port'): link['from_port']=source_ports[0].get('name','output')
        if not target_ports: link['to_port']='input'
        elif not isinstance(link.get('to_port'),str) or not link.get('to_port'): link['to_port']=target_ports[0].get('name','input')
        source_port=next((p for p in source_ports if isinstance(p,dict) and p.get('name')==link['from_port']),None)
        target_port=next((p for p in target_ports if isinstance(p,dict) and p.get('name')==link['to_port']),None)
        if source_ports and not source_port: raise ValueError('Выходной порт не найден в модуле '+str(source.get('name',link['from'])))
        if target_ports and not target_port: raise ValueError('Входной порт не найден в модуле '+str(target.get('name',link['to'])))
        if source_port and target_port:
            source_type=source_port.get('type','text'); target_type=target_port.get('type','text')
            if source_type!=target_type and 'any' not in {source_type,target_type}: raise ValueError('Несовместимые типы портов: '+str(source_type)+' → '+str(target_type))
        edge=(link['from'],link['from_port'],link['to'],link['to_port'])
        if edge in seen_edges: raise ValueError('Повторяющаяся связь между портами')
        slot=(link['to'],link['to_port'])
        if slot in occupied_inputs: raise ValueError('Входной порт '+link['to_port']+' уже подключён')
        seen_edges.add(edge); occupied_inputs.add(slot); normalized.append(link); adjacency[link['from']].append(link['to'])
    visiting=set(); visited=set()
    def has_cycle(node):
        if node in visiting: return True
        if node in visited: return False
        visiting.add(node)
        for target in adjacency[node]:
            if has_cycle(target): return True
        visiting.remove(node); visited.add(node); return False
    if any(has_cycle(node) for node in ids if node not in visited): raise ValueError('Циклические связи запрещены. Постройте направленный ациклический граф.')
    return normalized

def execute_module_graph(data):
    registry=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
    modules={m.get('id'):m for m in registry.get('modules',[]) if isinstance(m,dict) and m.get('id')}
    links=registry.get('connections',[])
    links=validate_module_connections(registry,links)
    start=str(data.get('start_id','')).strip()
    if start not in modules: raise ValueError('Выберите стартовый модуль')
    outgoing={key:[] for key in modules}; incoming={key:[] for key in modules}
    for link in links:
        source=link.get('from'); target=link.get('to')
        if source in modules and target in modules:
            outgoing[source].append(target); incoming[target].append(link)
    reachable=set(); stack=[start]
    while stack:
        node=stack.pop()
        if node in reachable: continue
        reachable.add(node); stack.extend(outgoing[node])
    indegree={node:sum(1 for edge in incoming[node] if edge.get('from') in reachable) for node in reachable}
    queue=[node for node in reachable if indegree[node]==0]; order=[]
    while queue:
        node=queue.pop(0); order.append(node)
        for target in outgoing[node]:
            if target in indegree:
                indegree[target]-=1
                if indegree[target]==0: queue.append(target)
    if len(order)!=len(reachable): raise ValueError('В схеме обнаружен цикл. Удалите циклическую связь.')
    if start in incoming and any(edge.get('from') in reachable for edge in incoming[start]):
        raise ValueError('Стартовый модуль не может иметь входящих связей внутри выполняемой схемы')
    values={}; port_values={}; records=[]; prompt_input=str(data.get('input',''))[:12000]
    selected_model=str(data.get('model','')).strip()[:160]
    for module_id in order:
        module=modules[module_id]; manifest=module_runtime_manifest(module); runtime=manifest.get('runtime') if isinstance(manifest.get('runtime'),dict) else {}
        kind=str(runtime.get('kind','')).strip()
        if kind not in MODULE_RUNTIME_KINDS:
            raise ValueError('Модуль «'+str(module.get('name',module_id))+'» не имеет разрешённого встроенного типа исполнения. Внешние модули требуют отдельного адаптера.')
        edges=[edge for edge in incoming[module_id] if edge.get('from') in reachable]
        if module_id==start: incoming_value=prompt_input
        elif len(edges)==1:
            edge=edges[0]; parent=edge['from']; parent_manifest=module_runtime_manifest(modules[parent]); parent_ports=parent_manifest.get('outputs') if isinstance(parent_manifest.get('outputs'),list) else []
            source_port=str(edge.get('from_port') or (parent_ports[0].get('name') if parent_ports else 'output'))
            target_port=str(edge.get('to_port') or ((manifest.get('inputs') or [{}])[0].get('name') if manifest.get('inputs') else 'input'))
            source_value=port_values.get(parent,{}).get(source_port,values[parent])
            incoming_value=source_value if target_port=='input' and len(manifest.get('inputs') or [])<=1 else {target_port:source_value}
        else:
            incoming_value={}
            for edge in edges:
                parent=edge['from']; parent_manifest=module_runtime_manifest(modules[parent]); parent_ports=parent_manifest.get('outputs') if isinstance(parent_manifest.get('outputs'),list) else []
                source_port=str(edge.get('from_port') or (parent_ports[0].get('name') if parent_ports else 'output'))
                target_port=str(edge.get('to_port') or 'input')
                incoming_value[target_port]=port_values.get(parent,{}).get(source_port,values[parent])
        def to_text(value):
            if isinstance(value,str): return value
            return json.dumps(value,ensure_ascii=False,indent=2)
        if kind=='input': output=incoming_value if module_id!=start else prompt_input
        elif kind=='template':
            template=str(runtime.get('template','{input}'))[:12000]
            output=template.replace('{input}',to_text(incoming_value)).replace('{context}',str(data.get('context',''))[:8000]).replace('{task}',str(data.get('task',''))[:8000])
            if isinstance(incoming_value,dict):
                for port_name,port_value in incoming_value.items(): output=output.replace('{input.'+str(port_name)+'}',to_text(port_value))
        elif kind=='transform':
            operation=str(runtime.get('operation','strip'))
            value=to_text(incoming_value)
            if operation=='uppercase': output=value.upper()
            elif operation=='lowercase': output=value.lower()
            elif operation=='strip': output=value.strip()
            elif operation=='json_parse':
                try: output=json.loads(value)
                except ValueError: raise ValueError('Модуль «'+str(module.get('name',module_id))+'»: вход не является корректным JSON')
            elif operation=='json_pretty':
                try: output=json.dumps(json.loads(value),ensure_ascii=False,indent=2)
                except ValueError: raise ValueError('Модуль «'+str(module.get('name',module_id))+'»: вход не является корректным JSON')
            else: raise ValueError('Неизвестная операция преобразования: '+operation)
        elif kind=='ollama':
            model=str(runtime.get('model') or selected_model or module.get('model') or '').strip()[:160]
            if not model: raise ValueError('Для модуля «'+str(module.get('name',module_id))+'» выберите модель Ollama')
            prompt=to_text(incoming_value)
            system_prompt=str(runtime.get('system_prompt','')).strip()[:4000]
            if system_prompt: prompt='Инструкции модуля:\n'+system_prompt+'\n\nВходные данные:\n'+prompt
            try:
                model = resolve_ollama_model(model)
            except ValueError as exc:
                raise ValueError('Модуль «' + str(module.get('name',module_id)) + '»: ' + str(exc)) from exc
            result=ollama_request('/api/generate',{'model':model,'prompt':prompt,'stream':False,'options':{'num_predict':min(max(int(runtime.get('max_tokens',1024)),64),4096)}},timeout=300)
            output=result.get('response','')
        else: output=incoming_value
        values[module_id]=output
        output_ports=manifest.get('outputs') if isinstance(manifest.get('outputs'),list) else []
        if not output_ports: port_values[module_id]={'output':output}
        elif isinstance(output,dict): port_values[module_id]={str(port.get('name','output')):output.get(str(port.get('name','output')),output) for port in output_ports}
        else: port_values[module_id]={str(port.get('name','output')):output for port in output_ports}
        records.append({'module_id':module_id,'name':module.get('name',module_id),'kind':kind,'status':'completed','output':output if isinstance(output,(str,int,float,bool,type(None),dict,list)) else str(output)})
    leaves=[node for node in reachable if not any(target in reachable for target in outgoing[node])]
    outputs={node:values[node] for node in leaves}
    result={'ok':True,'start_id':start,'executed':len(records),'order':order,'steps':records,'outputs':outputs,'result':next(iter(outputs.values())) if len(outputs)==1 else outputs,'finished_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
    log_event('module.graph.run',str(start)+' · '+str(len(records))+' модулей')
    write_json(DATA/'module-runs.json',([result]+read_json(DATA/'module-runs.json',[]))[:100])
    return result


def resolve_agent_system_prompt(agent: dict | None) -> str:
    """Resolve the assigned role prompt first, then legacy system instructions and defaults."""
    role = str((agent or {}).get('role', 'ANALYST')).upper().strip()
    try:
        roles = read_json(AGENT_ROLES_FILE, [])
        role_item = next((x for x in roles if isinstance(x, dict) and str(x.get('code', '')).upper() == role), None) if isinstance(roles, list) else None
    except Exception:
        role_item = None
    if role not in AGENT_ROLES:
        if role_item and str(role_item.get('system_prompt', '')).strip():
            return str(role_item['system_prompt']).strip()
        return AGENT_ROLE_PROMPTS.get(role, AGENT_ROLE_PROMPTS['ANALYST'])
    try:
        instructions = read_json(DATA / 'system_instructions.json', {}).get('instructions', [])
    except Exception:
        instructions = []
    instr = None
    if isinstance(instructions, list):
        instr = next((x for x in instructions if isinstance(x, dict) and x.get('role') == role and x.get('is_default')), None)
        if not instr:
            instr = next((x for x in instructions if isinstance(x, dict) and x.get('role') == role), None)
    if instr and isinstance(instr.get('system_prompt'), str) and instr['system_prompt'].strip():
        return instr['system_prompt'].strip()
    if role_item and str(role_item.get('system_prompt', '')).strip():
        return str(role_item['system_prompt']).strip()
    return AGENT_ROLE_PROMPTS.get(role, AGENT_ROLE_PROMPTS['ANALYST'])


def run_agent_task(model, task, agent=None, project=None):
    from agent_tools import effective_tools, execute_tool
    permissions=permission_settings()
    role=str((agent or {}).get('role','ANALYST')).upper()
    system_prompt=str((agent or {}).get('system_prompt') or '').strip() or resolve_agent_system_prompt(agent)
    if agent:
        system_prompt += '\n\nПрофиль агента: '+str(agent.get('name',''))+'\nНазначение: '+str(agent.get('description',''))[:1000]
        memory=str(agent.get('memory','')).strip()
        if memory: system_prompt += '\n\nДолговременная память агента (пользовательские заметки):\n'+memory[:8000]
    project_id = str((task or {}).get('project_id') or ((project or {}).get('id') if isinstance(project, dict) else '')).strip()
    if project_id:
        project_memory = read_project_memory(project_id)
        memory_context = [
            'СВЯЗАННАЯ ПАМЯТЬ ПРОЕКТА — учитывать все пункты при каждом продолжении работы.',
            'Сводка: ' + str(project_memory.get('summary') or 'не заполнена'),
            'Ограничения: ' + ('; '.join(str(x) for x in project_memory.get('constraints', [])) or 'нет записей'),
            'Открытые вопросы: ' + ('; '.join(str(x) for x in project_memory.get('open_questions', [])) or 'нет записей'),
            'Следующие шаги: ' + ('; '.join(str(x) for x in project_memory.get('next_steps', [])) or 'нет записей'),
            'Зафиксированные факты и результаты: ' + ('; '.join(str(x.get('text', '')) for x in project_memory.get('facts', [])[-15:] if isinstance(x, dict)) or 'нет записей'),
        ]
        system_prompt += '\n\n' + '\n'.join(memory_context)
    system_prompt += '\n\nТы работаешь в локальной платформе PQlocalAgentOSv3. Отвечай по-русски. Используй только инструменты, переданные в текущем запросе. Не запускай команды, PowerShell, SSH, программы или произвольный код, если инструмент run_command не предоставлен. Не утверждай, что действие выполнено, пока инструмент не вернул успех.'
    if role != 'MANAGER' and permissions.get('local_files') and permissions.get('roots'):
        system_prompt += '\n\nРазрешённые корневые папки для файловых инструментов:\n'+'\n'.join(str(root) for root in permissions['roots'][:50])+'\nИспользуй только эти пути. Доступ за пределами этих папок будет отклонён.'
    if (agent or {}).get('permissions',{}).get('github_access') and os.environ.get('GITHUB_TOKEN'):
        system_prompt += '\n\nДоступен только чтение настроенного репозитория GitHub: '+REPO+'.'
    prompt='Выполни задачу. Разделяй факты и предположения; сообщи о том, что не удалось проверить.\n\nНазвание задачи: '+str(task.get('title',''))+'\n\nИнструкция:\n'+str(task.get('description',''))
    if project and role != 'MANAGER':
        prompt += '\n\nКонтекст проекта:\nНазвание: '+str(project.get('name',''))+'\nОписание: '+str(project.get('description',''))+'\nРабочая папка: '+(str(project.get('path','')).strip() or 'не указана')+'\nВсе файловые операции выполняй только в этой папке и через разрешённые инструменты.'
    available=effective_tools(agent or {},permissions) if agent else []
    if project and role != 'MANAGER':
        env_type = str(project.get('env_type', 'local') or 'local').strip().lower()
        project_path = str(project.get('path', '') or '').strip()
        if env_type == 'ssh':
            connection_id = str(project.get('ssh_connection_id', '') or '').strip()
            system_prompt += '\n\n=== SSH ИНСТРУКЦИЯ ===\nЭтот проект находится на удалённом сервере. Используй ТОЛЬКО инструмент ssh_execute для работы с файлами проекта. Рабочий путь должен быть взят из поля проекта path и не должен выдумываться: ' + (project_path or '/') + '. Передавай working_dir точно этим значением. Не пытайся выйти за пределы рабочей папки. ' + (('Используй connection_id: ' + connection_id + '.') if connection_id else 'Выбери connection_id из доступных сохранённых SSH-подключений.')
        elif env_type == 'github':
            system_prompt += '\n\n=== ИНСТРУКЦИЯ GITHUB ===\nЭтот проект находится в GitHub. Для работы с файлами проекта используй инструменты github_*; не используй локальные файловые инструменты или SSH. Репозиторий проекта: ' + str(project.get('repo_name', '') or 'не указан') + '. Рабочая папка/путь проекта: ' + project_path + '.'
        else:
            system_prompt += '\n\n=== ИНСТРУКЦИЯ ЛОКАЛЬНОГО ПРОЕКТА ===\nЭтот проект локальный. Используй файловые инструменты (read_file, write_file и другие доступные файловые инструменты) для работы с файлами. Путь проекта: ' + (project_path or 'не указан') + '. Не используй SSH или GitHub-инструменты для изменения файлов локального проекта.'
    if project and role != 'MANAGER':
        project_dir=str(project.get('path','')).strip() or 'не указана'
        github_info='Доступ к GitHub разрешён.' if (agent or {}).get('permissions',{}).get('github_access') else 'Доступ к GitHub не разрешён.'
        system_prompt += '\n\n=== ИНФОРМАЦИЯ О ПРОЕКТЕ ===\nНазвание: '+str(project.get('name',''))+'\nРабочая папка проекта: '+project_dir+'\nОписание: '+str(project.get('description',''))+'\n'+github_info+'\nВАЖНО: если работаешь с файлами проекта, используй только указанную рабочую папку и разрешённые файловые инструменты. Не обращайся к другим папкам и не утверждай, что файл прочитан или изменён без результата инструмента.'
    if available:
        tool_names=[t['function']['name'] for t in available]
        system_prompt += '\n\n=== ДОСТУПНЫЕ ИНСТРУМЕНТЫ ===\nТвои доступные инструменты: '+', '.join(tool_names)+'. Не пытайся вызывать другие инструменты.' + agent_ssh_context(agent)
    if not available:
        result=ollama_request('/api/generate',{'model':model,'system':system_prompt,'prompt':prompt,'stream':False,'options':{'num_predict':2048}},timeout=300)
        return {'response':result.get('response',''),'tool_calls':0,'model':result.get('model',model)}
    messages=[{'role':'system','content':system_prompt},{'role':'user','content':prompt}]
    names={tool['function']['name'] for tool in available}
    total=0; last={}
    for _ in range(12):
        try:
            payload=ollama_request('/api/chat',{'model':model,'messages':messages,'tools':available,'stream':False,'think':False,'keep_alive':'5m','options':{'num_predict':1024}},timeout=240)
        except urllib.error.HTTPError as exc:
            if total==0 and exc.code in {400,404,422}:
                result=ollama_request('/api/generate',{'model':model,'system':system_prompt,'prompt':prompt,'stream':False,'options':{'num_predict':2048}},timeout=300)
                return {'response':result.get('response',''),'tool_calls':0,'model':result.get('model',model),'warning':'Модель не поддерживает вызов инструментов; выполнен обычный запрос без инструментов.'}
            raise
        last=payload
        message=payload.get('message')
        if not isinstance(message,dict): break
        calls=message.get('tool_calls')
        if not isinstance(calls,list) or not calls:
            return {'response':message.get('content','') if isinstance(message.get('content',''),str) else '', 'tool_calls':total,'model':payload.get('model',model)}
        messages.append(message)
        for call in calls:
            total+=1
            if total>24:
                messages.append({'role':'tool','content':'Остановлено: достигнут лимит 24 вызова инструмента.'})
                break
            function=call.get('function',{}) if isinstance(call,dict) else {}
            name=function.get('name') if isinstance(function,dict) else None
            args=function.get('arguments',{}) if isinstance(function,dict) else {}
            if isinstance(args,str):
                try: args=json.loads(args)
                except ValueError: args={}
            if not isinstance(args,dict) or not isinstance(name,str) or name not in names:
                result={'error':'Некорректный или недоступный инструмент.'}; name=str(name or 'unknown')
            else:
                if name=='run_command' and project and project.get('path'):
                    args['cwd']=str(project.get('path'))
                if name=='ssh_execute' and project and str(project.get('env_type','local'))=='ssh':
                    args['working_dir']=str(project.get('path','') or '/')
                    if project.get('ssh_connection_id'): args['connection_id']=str(project.get('ssh_connection_id'))
                blocked_by_allowed_paths = False
                try:
                    # Проверка allowed_paths (второй путь исполнения, помимо AgentRuntime)
                    from agent_tools import check_allowed_paths
                    _allowed = [project.get("path")] if project and project.get("path") else []
                    check_allowed_paths(name, args or {}, _allowed)
                except PermissionError as exc:
                    result = {"ok": False, "error": f"Заблокировано политикой allowed_paths: {exc}"}
                    blocked_by_allowed_paths = True
                if not blocked_by_allowed_paths:
                    result=execute_tool(name,args,agent,permissions)
            log_event('agent.tool_called',str((agent or {}).get('id',''))+' · '+name+' · '+('error' if 'error' in result else 'ok'))
            messages.append({'role':'tool','tool_name':name,'content':json.dumps(result,ensure_ascii=False)[:12000]})
        if total>24: break
    message=last.get('message',{}) if isinstance(last,dict) else {}
    return {'response':message.get('content','') if isinstance(message,dict) and isinstance(message.get('content',''),str) else '', 'tool_calls':total,'model':last.get('model',model) if isinstance(last,dict) else model,'warning':'Достигнут лимит циклов вызова инструментов.'}


def find_agent_by_role(role, agents):
    """Вернуть включённого системного агента нужной роли; иначе пользовательского."""
    role = str(role).upper()
    matches = [a for a in agents if isinstance(a, dict) and str(a.get('role', '')).upper() == role]
    enabled_system = next((a for a in matches if a.get('system') and a.get('system_enabled', True)), None)
    if enabled_system: return enabled_system
    custom = next((a for a in matches if not a.get('system')), None)
    if custom: return custom
    return {'id': None, 'name': role, 'role': role, 'system_prompt': '', 'permissions': {}, 'description': ''}


def parse_orchestrator_decision(text):
    """Достать JSON из ответа MANAGER. None, если не удалось."""
    if not isinstance(text, str):
        return None
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


def run_agent_team(model, task, agent=None, project=None):
    """Строгая матрица: MANAGER → DISPATCHER → workers → DISPATCHER → MANAGER."""
    agents = domain_items('agents')
    task = task if isinstance(task, dict) else {}

    active_roles = task.get('active_roles')
    if not isinstance(active_roles, list) or not active_roles:
        active_roles = list(AGENT_ROLES)
    active_roles = [str(role).upper() for role in active_roles if str(role).upper() in AGENT_ROLES]

    # MANAGER и DISPATCHER — обязательные координаторы, не исполнители подзадач.
    worker_roles = []
    for role in active_roles:
        if role in {'MANAGER', 'DISPATCHER'} or role in worker_roles:
            continue
        role_agents = [a for a in agents if isinstance(a, dict) and str(a.get('role', '')).upper() == role]
        if role_agents and not any(not a.get('system') or a.get('system_enabled', True) for a in role_agents):
            continue
        worker_roles.append(role)

    task_title = str(task.get('title', '')).strip() or 'Задача без названия'
    task_description = str(task.get('description', '')).strip()
    project_id = str(task.get('project_id', '') or ((project or {}).get('id', '') if isinstance(project, dict) else '')).strip()
    task_keywords = extract_task_keywords(task_title + ' ' + task_description)
    risk_history = search_risks(task_keywords)
    active_risks = [risk for risk in risk_history if int(risk.get('weight', 0) or 0) > 5]
    task['risk_history'] = risk_history
    task['risk_weight'] = max((int(risk.get('weight', 0) or 0) for risk in active_risks), default=0)
    manager = find_agent_by_role('MANAGER', agents)
    dispatcher = find_agent_by_role('DISPATCHER', agents)
    manager = {**manager, 'role': 'MANAGER', 'permissions': {}, 'system_prompt':
        'Ты — Генерал, руководитель процесса. Принимай решения и утверждай план. Ты НЕ читаешь файлы, НЕ исследуешь артефакты и НЕ выполняешь работу специалистов. Все поручения передавай только Диспетчеру. Ты получаешь информацию только от Диспетчера. Возвращай только JSON по указанной схеме.'}
    dispatcher = {**dispatcher, 'role': 'DISPATCHER', 'system_prompt':
        'Ты — Премьер, Диспетчер команды. Ты единственный маршрутизатор. Получай план Менеджера, распределяй задачи между активными ролями, собирай их результаты и передавай Менеджеру только сводный отчёт. Не выдавай чужую работу за свою. Возвращай только JSON по указанной схеме.'}

    manager_model = str(manager.get('model') or model)
    dispatcher_model = str(dispatcher.get('model') or model)
    history = []
    total_tool_calls = 0
    max_cycles = 4

    def add_stage(role, agent_item, result, stage):
        nonlocal total_tool_calls
        calls = int(result.get('tool_calls', 0) or 0)
        total_tool_calls += calls
        item = {
            'role': role,
            'name': str(agent_item.get('name') or role),
            'stage': stage,
            'model': result.get('model', model),
            'response': str(result.get('response', '')),
            'tool_calls': calls,
            'warning': str(result.get('warning', '') or ''),
        }
        history.append(item)
        return item

    def call_manager(instruction, prior_report=''):
        manager_task = {
            'title': task_title + ' — решение Менеджера',
            'description': (
                'Исходная задача пользователя:\n' + task_description
                + '\n\n' + instruction
                + ('\n\nСводка, полученная ИСКЛЮЧИТЕЛЬНО от Диспетчера:\n' + prior_report if prior_report else '')
                + '\n\nВерни строго один JSON-объект без markdown. Первый ответ: '
                  '{"action":"delegate","target":"DISPATCHER","instruction":"утверждённый общий план и ожидаемые результаты"}. '
                  'После отчёта Диспетчера: {"done":true,"final_answer":"итог пользователю"} '
                  'или {"done":false,"action":"delegate","target":"DISPATCHER","instruction":"конкретное продолжение или исправление"}. '
                  'Не выбирай исполнителей напрямую. Не проси и не анализируй содержимое файлов. '
                  'Не утверждай, что файлы прочитаны, код изменён или тесты выполнены.'
            ),
            'project_id': project_id,
        }
        return run_agent_task(manager_model, manager_task, manager, None)

    def call_dispatcher(title_suffix, instruction):
        dispatcher_task = {
            'title': task_title + ' — Диспетчер: ' + title_suffix,
            'description': instruction,
            'project_id': project_id,
        }
        return run_agent_task(dispatcher_model, dispatcher_task, dispatcher, project)

    # Stage 1: General/Manager creates the plan and delegates only to Dispatcher.
    manager_result = call_manager(
        'Ты — Генерал. Прими решение, утверди общий план и передай задачу Диспетчеру. '
        'Не читай файлы и не выполняй специализированную работу.'
    )
    manager_item = add_stage('MANAGER', manager, manager_result, 'manager_decision')
    manager_decision = parse_orchestrator_decision(manager_item['response'])
    if not isinstance(manager_decision, dict) or manager_decision.get('action') != 'delegate' or str(manager_decision.get('target', '')).upper() != 'DISPATCHER':
        return {
            'response': 'Менеджер не вернул корректное решение для передачи Диспетчеру. Ответ: ' + manager_item['response'][:500],
            'team_result': history, 'tool_calls': total_tool_calls, 'model': model,
            'warning': 'invalid_manager_delegation_json',
        }

    current_instruction = str(manager_decision.get('instruction', '')).strip()
    if not current_instruction:
        current_instruction = 'Выполни исходную задачу по утверждённому плану и назначь необходимые активные роли.'

    for cycle in range(1, max_cycles + 1):
        # Stage 2: Dispatcher breaks the approved plan into tasks for active specialist roles.
        dispatch_result = call_dispatcher(
            'распределение, цикл ' + str(cycle),
            'Ты — Премьер. Получи утверждённый план Генерала и разбей его на конкретные подзадачи.\n'
            + 'Исходная задача: ' + task_title + '\n' + task_description + '\n'
            + 'Инструкция Генерала: ' + current_instruction + '\n'
            + 'Активные роли-исполнители: ' + ', '.join(worker_roles) + '\n'
            + 'Назначай только роли из этого списка; MANAGER и DISPATCHER не назначаются исполнителями. '
              'Для каждой задачи укажи измеримый результат, релевантный контекст и критерии приёмки. '
              'Учитывай зависимости и не создавай дубликаты.\n'
            + ('ВНИМАНИЕ: ОБНАРУЖЕНЫ РИСКИ ИЗ ЖУРНАЛА ПРЕЦЕДЕНТОВ. При риске выше 5 оцени прошлые сбои и запроси подтверждение Владельца до опасных или необратимых действий.\n'
               + '\n'.join('- Прошлый сбой: ' + str(risk.get('reason', 'без описания')) + ' (Вес: ' + str(risk.get('weight', 0)) + '; действие: ' + str(risk.get('action_taken', 'не указано')) + '; совпадения: ' + ', '.join(risk.get('matched_keywords', [])) + ')' for risk in active_risks) + '\n' if active_risks else '')
            + 'Верни только JSON: {"tasks":[{"role":"CODER","task":"конкретная инструкция"}]}. '
              'Если исполнительские подзадачи не нужны, верни {"tasks":[]} .'
        )
        dispatch_item = add_stage('DISPATCHER', dispatcher, dispatch_result, 'dispatch')
        dispatch_decision = parse_orchestrator_decision(dispatch_item['response'])
        task_specs = dispatch_decision.get('tasks') if isinstance(dispatch_decision, dict) else None
        if not isinstance(task_specs, list):
            task_specs = []
            dispatch_item['warning'] = (dispatch_item['warning'] + ' | ' if dispatch_item['warning'] else '') + 'invalid_dispatcher_tasks_json'

        worker_reports = []
        seen = set()
        for spec in task_specs[:8]:
            if not isinstance(spec, dict):
                continue
            role = str(spec.get('role', '')).upper().strip()
            if role not in worker_roles or role in seen:
                continue
            instruction = str(spec.get('task', '')).strip()
            if not instruction:
                continue
            seen.add(role)
            worker = find_agent_by_role(role, agents)
            worker_task = {
                'title': task_title + ' — ' + role,
                'description': (
                    'Ты получил задание от Диспетчера. Выполни только назначенную работу. '
                    'После выполнения верни проверяемый отчёт: что сделано, какие файлы/артефакты затронуты, '
                    'какие проверки действительно выполнены, результаты и оставшиеся ограничения. '
                    'Не заявляй о действиях без подтверждения инструмента.\n\nЗадание Диспетчера:\n' + instruction
                ),
                'project_id': project_id,
            }
            worker_model = str(worker.get('model') or model)
            worker_result = run_agent_task(worker_model, worker_task, worker, project)
            worker_item = add_stage(role, worker, worker_result, 'execution')
            worker_reports.append({
                'role': role,
                'name': worker_item['name'],
                'response': worker_item['response'][:5000],
                'warning': worker_item['warning'],
            })

        # Stage 4: all specialist reports are returned to Dispatcher; Dispatcher summarizes for Manager.
        reports_text = json.dumps(worker_reports, ensure_ascii=False, indent=2)
        report_result = call_dispatcher(
            'сбор результатов, цикл ' + str(cycle),
            'Агенты отчитались. Собери результаты без искажений, сопоставь их с исходной задачей и планом Генерала. '
            'Укажи выполненное, неподтверждённое, ошибки, блокеры и что следует делать дальше. '
            'Ты передаёшь Менеджеру только сводку, не направляй ему сырые артефакты и не выдумывай проверки.\n\n'
            'Исходная задача: ' + task_title + '\n' + task_description + '\n'
            'План Генерала: ' + current_instruction + '\n'
            'Результаты исполнителей (источник данных):\n' + reports_text + '\n\n'
            'Верни только JSON: {"action":"report","target":"MANAGER","summary":"сводный отчёт для решения Менеджера"}.'
        )
        report_item = add_stage('DISPATCHER', dispatcher, report_result, 'dispatcher_report')
        report_decision = parse_orchestrator_decision(report_item['response'])
        if not isinstance(report_decision, dict) or str(report_decision.get('action', '')).lower() != 'report' or str(report_decision.get('target', '')).upper() != 'MANAGER':
            dispatcher_summary = 'Диспетчер не вернул корректный JSON-отчёт. Его ответ: ' + report_item['response'][:3000]
            report_item['warning'] = (report_item['warning'] + ' | ' if report_item['warning'] else '') + 'invalid_dispatcher_report_json'
        else:
            dispatcher_summary = str(report_decision.get('summary', '')).strip()
            if not dispatcher_summary:
                dispatcher_summary = 'Диспетчер вернул пустую сводку.'

        # Stage 5: Manager sees only Dispatcher summary and decides final/next cycle.
        final_result = call_manager(
            'Ты получил сводку от Премьера. Прими финальное решение: задача выполнена или нужен ещё цикл. '
            'Если работа завершена, верни {"done":true,"final_answer":"итог пользователю"}. '
            'Если нужны дополнительные действия, верни {"done":false,"action":"delegate","target":"DISPATCHER","instruction":"что исправить или продолжить"}. '
            'Не назначай исполнителей напрямую; не проси файлы или сырые артефакты.',
            prior_report=dispatcher_summary,
        )
        final_item = add_stage('MANAGER', manager, final_result, 'manager_final_decision')
        final_decision = parse_orchestrator_decision(final_item['response'])
        if isinstance(final_decision, dict) and final_decision.get('done') is True:
            final_answer = str(final_decision.get('final_answer', '')).strip() or dispatcher_summary
            return {
                'response': final_answer,
                'team_result': history,
                'tool_calls': total_tool_calls,
                'model': model,
            }
        if not isinstance(final_decision, dict) or final_decision.get('action') != 'delegate' or str(final_decision.get('target', '')).upper() != 'DISPATCHER':
            final_item['warning'] = (final_item['warning'] + ' | ' if final_item['warning'] else '') + 'invalid_manager_followup_json'
            return {
                'response': 'Менеджер не вернул корректное финальное решение. Сводка Диспетчера:\n' + dispatcher_summary,
                'team_result': history, 'tool_calls': total_tool_calls, 'model': model,
                'warning': 'invalid_manager_followup_json',
            }
        current_instruction = str(final_decision.get('instruction', '')).strip()
        if not current_instruction:
            current_instruction = 'Продолжи задачу, устрани выявленные блокеры и передай новую сводку.'
    return {
        'response': 'Достигнут лимит циклов команды (' + str(max_cycles) + '). Последняя сводка Диспетчера должна быть проверена вручную.',
        'team_result': history, 'tool_calls': total_tool_calls, 'model': model,
        'warning': 'max_cycles_reached',
    }

def _filetime_value(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime

def _windows_cpu_times():
    import ctypes
    from ctypes import wintypes
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError('GetSystemTimes failed')
    return (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))

_CPU_PREVIOUS_TIMES = None

def _cpu_usage():
    global _CPU_PREVIOUS_TIMES
    try:
        import psutil
        return round(psutil.cpu_percent(interval=None), 1)
    except Exception:
        try:
            current = _windows_cpu_times()
            previous = _CPU_PREVIOUS_TIMES
            _CPU_PREVIOUS_TIMES = current
            if previous is None:
                return None
            idle = current[0] - previous[0]
            total = (current[1] - previous[1]) + (current[2] - previous[2])
            if total <= 0 or idle < 0:
                return None
            return round(max(0.0, min(100.0, (1 - idle / total) * 100)), 1)
        except Exception:
            return None

def _memory_stats():
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) and status.ullTotalPhys:
            total = status.ullTotalPhys / (1024 ** 3)
            available = status.ullAvailPhys / (1024 ** 3)
            page_total = status.ullTotalPageFile / (1024 ** 3)
            page_available = status.ullAvailPageFile / (1024 ** 3)
            return {'available': True, 'percent': round((total - available) / total * 100, 1),
                    'used': round(total - available, 2), 'total': round(total, 2),
                    'free': round(available, 2), 'pagefile': {
                        'total': round(page_total, 2), 'available': round(page_available, 2),
                        'used': round(max(0, page_total - page_available), 2)}}
    except Exception:
        pass
    try:
        import psutil
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {'available': True, 'percent': mem.percent, 'used': round(mem.used / (1024 ** 3), 2),
                'total': round(mem.total / (1024 ** 3), 2), 'free': round(mem.available / (1024 ** 3), 2),
                'pagefile': {'total': round(swap.total / (1024 ** 3), 2),
                             'available': round((swap.total - swap.used) / (1024 ** 3), 2),
                             'used': round(swap.used / (1024 ** 3), 2)}}
    except Exception:
        return {'available': False, 'percent': None, 'used': None, 'total': None, 'free': None, 'pagefile': None}

def _cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return str(winreg.QueryValueEx(key, 'ProcessorNameString')[0]).strip()
    except Exception:
        try:
            import platform
            return platform.processor() or None
        except Exception:
            return None

def _gpu_stats_uncached():
    import subprocess
    from pathlib import Path
    candidates = ['nvidia-smi']
    program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
    candidates.append(str(Path(program_files) / 'NVIDIA Corporation' / 'NVSMI' / 'nvidia-smi.exe'))
    fields = ['name', 'utilization.gpu', 'memory.used', 'memory.total', 'temperature.gpu',
              'power.draw', 'power.limit', 'clocks.gr', 'clocks.mem', 'fan.speed']
    query = ','.join(fields)
    for command in candidates:
        try:
            result = subprocess.run([command, '--query-gpu=' + query, '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=3, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), '')
            parts = [part.strip() for part in line.split(',')]
            if len(parts) < len(fields):
                raise ValueError('Incomplete nvidia-smi output')
            def number(index):
                try:
                    value = parts[index].strip()
                    return None if not value or value.lower() in ('[n/a]', 'n/a', 'not supported') else float(value)
                except (ValueError, IndexError):
                    return None
            used_mb, total_mb = number(2), number(3)
            return {'available': True, 'name': parts[0] or None, 'percent': number(1),
                    'vramUsed': round(used_mb / 1024, 2) if used_mb is not None else None,
                    'vramTotal': round(total_mb / 1024, 2) if total_mb is not None else None,
                    'temperatureC': number(4), 'powerW': number(5), 'powerLimitW': number(6),
                    'coreClockMHz': number(7), 'memoryClockMHz': number(8), 'fanPercent': number(9),
                    'raw': {'memoryUsedMiB': used_mb, 'memoryTotalMiB': total_mb}}
        except Exception:
            # Driver versions may not expose every optional field; retry the stable base query.
            try:
                result = subprocess.run([command, '--query-gpu=name,utilization.gpu,memory.used,memory.total',
                                         '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                        timeout=2, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                parts = [part.strip() for part in next((x.strip() for x in result.stdout.splitlines() if x.strip()), '').split(',')]
                if len(parts) >= 4:
                    return {'available': True, 'name': ','.join(parts[:-3]).strip() or None,
                            'percent': float(parts[-3]), 'vramUsed': round(float(parts[-2]) / 1024, 2),
                            'vramTotal': round(float(parts[-1]) / 1024, 2), 'temperatureC': None,
                            'powerW': None, 'powerLimitW': None, 'coreClockMHz': None,
                            'memoryClockMHz': None, 'fanPercent': None}
            except Exception:
                continue
    return {'available': False, 'name': None, 'percent': None, 'vramUsed': None, 'vramTotal': None,
            'temperatureC': None, 'powerW': None, 'powerLimitW': None, 'coreClockMHz': None,
            'memoryClockMHz': None, 'fanPercent': None}

_GPU_CACHE = None
_GPU_CACHE_AT = 0.0
_GPU_CACHE_LOCK = threading.Lock()
GPU_CACHE_TTL = 5.0
_GPU_BACKGROUND_STARTED = False

def _start_gpu_background():
    global _GPU_BACKGROUND_STARTED
    if _GPU_BACKGROUND_STARTED:
        return
    _GPU_BACKGROUND_STARTED = True

    def worker():
        global _GPU_CACHE, _GPU_CACHE_AT
        try:
            result = _gpu_stats_uncached()
            with _GPU_CACHE_LOCK:
                _GPU_CACHE = result
                _GPU_CACHE_AT = time.monotonic()
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()

def _gpu_stats():
    global _GPU_CACHE, _GPU_CACHE_AT
    now = time.monotonic()
    if _GPU_CACHE is None:
        _start_gpu_background()
        return {'available': False, 'pending': True, 'name': None, 'percent': None,
                'vramUsed': None, 'vramTotal': None, 'temperatureC': None, 'powerW': None,
                'powerLimitW': None, 'coreClockMHz': None, 'memoryClockMHz': None,
                'fanPercent': None}
    if now - _GPU_CACHE_AT < GPU_CACHE_TTL:
        return _GPU_CACHE
    result = _gpu_stats_uncached()
    with _GPU_CACHE_LOCK:
        _GPU_CACHE = result
        _GPU_CACHE_AT = time.monotonic()
    return result

def _disk_stats():
    disks = []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if not (mask & (1 << index)):
                continue
            mount = chr(65 + index) + ':\\'
            try:
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(mount)
                if drive_type not in (2, 3, 6):
                    continue
                usage = shutil.disk_usage(mount)
                total = usage.total / (1024 ** 3)
                used = (usage.total - usage.free) / (1024 ** 3)
                if total <= 0:
                    continue
                label_buffer = ctypes.create_unicode_buffer(261)
                fs_buffer = ctypes.create_unicode_buffer(261)
                try:
                    ctypes.windll.kernel32.GetVolumeInformationW(mount, label_buffer, len(label_buffer), None, None, None, fs_buffer, len(fs_buffer))
                    label, filesystem = label_buffer.value or None, fs_buffer.value or None
                except Exception:
                    label, filesystem = None, None
                disks.append({'mount': mount, 'available': True, 'driveType': drive_type,
                              'label': label, 'filesystem': filesystem, 'percent': round(used / total * 100, 1),
                              'used': round(used, 2), 'free': round(usage.free / (1024 ** 3), 2),
                              'total': round(total, 2), 'totalBytes': usage.total, 'freeBytes': usage.free})
            except (OSError, PermissionError):
                continue
    except Exception:
        try:
            usage = shutil.disk_usage(str(ROOT))
            total = usage.total / (1024 ** 3)
            used = (usage.total - usage.free) / (1024 ** 3)
            if total:
                disks.append({'mount': str(ROOT.anchor or ROOT), 'available': True,
                              'percent': round(used / total * 100, 1), 'used': round(used, 2),
                              'free': round(usage.free / (1024 ** 3), 2), 'total': round(total, 2),
                              'totalBytes': usage.total, 'freeBytes': usage.free})
        except Exception:
            pass
    return disks

def _network_stats():
    try:
        import psutil
        counters = psutil.net_io_counters(pernic=True)
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        adapters = []
        for name, counter in counters.items():
            status = stats.get(name)
            addr_items = addresses.get(name, [])
            adapters.append({
                'name': name, 'isUp': bool(status.isup) if status else None,
                'speedMbps': status.speed if status else None,
                'mtu': status.mtu if status else None,
                'bytesSent': counter.bytes_sent, 'bytesReceived': counter.bytes_recv,
                'packetsSent': counter.packets_sent, 'packetsReceived': counter.packets_recv,
                'errorsIn': counter.errin, 'errorsOut': counter.errout,
                'dropsIn': counter.dropin, 'dropsOut': counter.dropout,
                'addresses': [{'family': str(a.family), 'address': a.address, 'netmask': a.netmask}
                              for a in addr_items if a.address and not a.address.startswith('fe80::')]
            })
        totals = psutil.net_io_counters()
        return {'available': True, 'bytesSent': totals.bytes_sent, 'bytesReceived': totals.bytes_recv,
                'packetsSent': totals.packets_sent, 'packetsReceived': totals.packets_recv, 'adapters': adapters,
                'note': 'Network counters are cumulative since system start or adapter reset.'}
    except Exception as exc:
        return {'available': False, 'bytesSent': None, 'bytesReceived': None, 'adapters': [],
                'reason': 'Install psutil to expose per-adapter counters.'}

def _process_stats():
    try:
        import psutil
        processes=[]
        for proc in psutil.process_iter(['pid','ppid','name','exe','username','status','memory_info','memory_full_info','cpu_percent','create_time','num_threads','nice','io_counters']):
            try:
                info=proc.info; mem=info.get('memory_info'); full=info.get('memory_full_info'); io=info.get('io_counters')
                started=info.get('create_time')
                processes.append({'pid':info.get('pid'),'parentPid':info.get('ppid'),'name':info.get('name'),'path':info.get('exe'),'user':info.get('username'),'status':info.get('status'),'memoryBytes':getattr(mem,'rss',None),'virtualMemoryBytes':getattr(mem,'vms',None),'privateMemoryBytes':getattr(full,'private',None),'peakWorkingSetBytes':getattr(full,'peak_wset',None),'cpuPercent':info.get('cpu_percent'),'startedAt':datetime.datetime.fromtimestamp(started).astimezone().isoformat(timespec='seconds') if started else None,'threads':info.get('num_threads'),'priority':info.get('nice'),'diskReadBytes':getattr(io,'read_bytes',None),'diskWriteBytes':getattr(io,'write_bytes',None),'diskReadOps':getattr(io,'read_count',None),'diskWriteOps':getattr(io,'write_count',None),'diskReadBytesPerSec':_rate_snapshot('proc-read-'+str(info.get('pid')),getattr(io,'read_bytes',0)) if io else None,'diskWriteBytesPerSec':_rate_snapshot('proc-write-'+str(info.get('pid')),getattr(io,'write_bytes',0)) if io else None,'gpuPercent':None,'gpuMemoryBytes':None,'exitCode':None})
            except (OSError,PermissionError,psutil.Error):
                continue
        by_memory=sorted(processes,key=lambda p:p.get('memoryBytes') or 0,reverse=True)
        by_cpu=sorted(processes,key=lambda p:p.get('cpuPercent') or 0,reverse=True)
        by_read=sorted(processes,key=lambda p:p.get('diskReadBytesPerSec') or 0,reverse=True)
        by_write=sorted(processes,key=lambda p:p.get('diskWriteBytesPerSec') or 0,reverse=True)
        return {'available':True,'count':len(processes),'items':processes,'topMemory':by_memory[:30],'topCpu':by_cpu[:30],'topDiskRead':by_read[:20],'topDiskWrite':by_write[:20],
                'note':'Per-process network and GPU counters are driver/ETW dependent and are null unless a supported collector is installed.'}
    except Exception as exc:
        return {'available':False,'count':None,'items':[],'topMemory':[],'topCpu':[],'topDiskRead':[],'topDiskWrite':[],'reason':'Detailed process metrics unavailable: '+str(exc)[:160]}

def _battery_stats():
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return {'available': False, 'present': False, 'percent': None, 'plugged': None, 'secondsLeft': None}
        return {'available': True, 'present': True, 'percent': battery.percent, 'plugged': battery.power_plugged,
                'secondsLeft': battery.secsleft if battery.secsleft >= 0 else None}
    except Exception:
        return {'available': False, 'present': None, 'percent': None, 'plugged': None, 'secondsLeft': None}

def _local_services():
    import urllib.request
    services = [
        {'id': 'ollama', 'name': 'Ollama', 'base': 'http://127.0.0.1:11434'},
        {'id': 'lm-studio', 'name': 'LM Studio', 'base': 'http://127.0.0.1:1234'}
    ]
    result = []
    for service in services:
        item = {'id': service['id'], 'name': service['name'], 'available': False, 'baseUrl': service['base'],
                'models': None, 'modelCount': None}
        endpoints = ['/api/tags'] if service['id'] == 'ollama' else ['/v1/models']
        for endpoint in endpoints:
            try:
                request = urllib.request.Request(service['base'] + endpoint, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=0.65) as response:
                    payload = json.loads(response.read(1_000_000).decode('utf-8'))
                item['available'] = True
                if service['id'] == 'ollama':
                    models = payload.get('models', []) if isinstance(payload, dict) else []
                    item['models'] = [{'name': m.get('name'), 'sizeBytes': m.get('size'),
                                       'modifiedAt': m.get('modified_at')} for m in models if isinstance(m, dict)]
                else:
                    models = payload.get('data', []) if isinstance(payload, dict) else []
                    item['models'] = [{'id': m.get('id'), 'ownedBy': m.get('owned_by')} for m in models if isinstance(m, dict)]
                item['modelCount'] = len(item['models'])
                break
            except Exception:
                continue
        result.append(item)
    return result


# Extended telemetry helpers. Optional Windows counters return null when unavailable.
_TELEMETRY_PREVIOUS = {}
_FOLDER_SIZE_CACHE = {}
_FOLDER_SIZE_CACHE_AT = 0
_WINDOWS_CACHE = None
_WINDOWS_CACHE_AT = 0
_TELEMETRY_HISTORY = []
# Кэшируем только выбранные системные показатели, чтобы не собирать снимок при каждом опросе.
_TELEMETRY_CACHE = None
_TELEMETRY_CACHE_AT = 0.0
_TELEMETRY_CACHE_LOCK = threading.Lock()
def _rate_snapshot(key, current):
    import time
    now=time.monotonic(); old=_TELEMETRY_PREVIOUS.get(key); _TELEMETRY_PREVIOUS[key]=(now,current)
    if not old or now<=old[0]: return None
    return round(max(0,current-old[1])/(now-old[0]),2)

def _extended_cpu():
    result={'perCorePercent':[],'manufacturer':None,'baseMHz':None,'queueLength':None,'temperatureC':None,'powerW':None,'systemCpuTimeSeconds':None,'processesTopCpu':[]}
    try:
        import psutil
        result['perCorePercent']=psutil.cpu_percent(interval=0.05,percpu=True)
        result['systemCpuTimeSeconds']=round(sum(psutil.cpu_times()._asdict().values()),2)
        try:
            q=psutil.cpu_stats()
            result['contextSwitches']=q.ctx_switches; result['interrupts']=q.interrupts
        except Exception: pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                result['manufacturer']=str(winreg.QueryValueEx(key,'VendorIdentifier')[0]).strip()
                mhz=winreg.QueryValueEx(key,'~MHz')[0]; result['baseMHz']=float(mhz) if mhz else None
        except Exception: pass
        procs=[]
        for p in psutil.process_iter(['pid','name','cpu_percent','status','num_threads']):
            try:
                i=p.info; procs.append({'pid':i.get('pid'),'name':i.get('name'),'cpuPercent':i.get('cpu_percent'),'status':i.get('status'),'threads':i.get('num_threads')})
            except Exception: pass
        result['processesTopCpu']=sorted(procs,key=lambda x:x.get('cpuPercent') or 0,reverse=True)[:20]
    except Exception as exc: result['error']=str(exc)[:180]
    # Temperature sensors are not consistently exposed by Windows/psutil.
    result['temperatureNote']='Температура CPU и мощность доступны только при наличии поддерживаемого датчика/драйвера.'
    return result

def _extended_memory():
    out={'cachedGB':None,'buffersGB':None,'availableGB':None,'processesTopMemory':[],'processesTopVirtual':[],'peakWorkingSetAvailable':False,'readWriteBytesPerSec':None,'hardwareReservedGB':None}
    try:
        import psutil
        m=psutil.virtual_memory()
        out.update({'availableGB':round(m.available/1024**3,2),'cachedGB':round(getattr(m,'cached',0)/1024**3,2) if hasattr(m,'cached') else None,'buffersGB':round(getattr(m,'buffers',0)/1024**3,2) if hasattr(m,'buffers') else None})
        rows=[]
        for p in psutil.process_iter(['pid','name','memory_info','memory_full_info']):
            try:
                i=p.info; mi=i.get('memory_info'); full=i.get('memory_full_info')
                rows.append({'pid':i.get('pid'),'name':i.get('name'),'rssBytes':getattr(mi,'rss',None),'vmsBytes':getattr(mi,'vms',None),'privateBytes':getattr(full,'private',None)})
            except Exception: pass
        out['processesTopMemory']=sorted(rows,key=lambda x:x.get('rssBytes') or 0,reverse=True)[:20]
        out['processesTopVirtual']=sorted(rows,key=lambda x:x.get('vmsBytes') or 0,reverse=True)[:20]
    except Exception as exc: out['error']=str(exc)[:180]
    return out

def _extended_gpu():
    import subprocess
    out={'adapters':[],'engines':None,'processes':[],'activeGpuCount':None,'note':'Engine-level utilization and per-process VRAM depend on the installed NVIDIA driver and nvidia-smi support.'}
    command=shutil.which('nvidia-smi')
    if not command:
        p=os.environ.get('ProgramFiles',r'C:\Program Files')
        candidate=str(Path(p)/'NVIDIA Corporation'/'NVSMI'/'nvidia-smi.exe')
        if Path(candidate).is_file(): command=candidate
    if not command: return out
    def run(args,timeout=2):
        return subprocess.run([command]+args,capture_output=True,text=True,timeout=timeout,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
    try:
        raw=run(['--query-gpu=index,name,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,clocks.gr,clocks.mem,pstate,clocks_throttle_reasons.active','--format=csv,noheader,nounits'])
        for line in raw.splitlines():
            p=[x.strip() for x in line.split(',')]
            if len(p)>=13:
                def n(i):
                    try:return float(p[i]) if p[i] and p[i].lower() not in ('n/a','[n/a]','not supported') else None
                    except Exception:return None
                out['adapters'].append({'index':n(0),'name':p[1],'uuid':p[2],'gpuPercent':n(3),'memoryPercent':n(4),'vramUsedMiB':n(5),'vramTotalMiB':n(6),'temperatureC':n(7),'powerW':n(8),'coreClockMHz':n(9),'memoryClockMHz':n(10),'performanceState':p[11],'throttleReasons':p[12]})
        out['activeGpuCount']=len(out['adapters'])
    except Exception as exc: out['queryError']=str(exc)[:180]
    try:
        raw=run(['--query-compute-apps=gpu_uuid,pid,process_name,used_memory','--format=csv,noheader,nounits'])
        for line in raw.splitlines():
            p=[x.strip() for x in line.split(',',3)]
            if len(p)>=4: out['processes'].append({'gpuUuid':p[0],'pid':p[1],'name':p[2],'vramMiB':p[3]})
    except Exception: pass
    try:
        raw=run(['dmon','-c','1','-s','u'])
        lines=[x.split() for x in raw.splitlines() if x.strip() and not x.lstrip().startswith('#')]
        if len(lines)>1: out['engines']={'header':lines[0],'sample':lines[-1]}
    except Exception: pass
    return out

def _extended_disks():
    import time
    global _FOLDER_SIZE_CACHE_AT
    result={'io':None,'physicalDevices':[],'projectFolders':[],'note':'SMART, drive temperature and controller write endurance require vendor/driver support.'}
    try:
        import psutil
        io=psutil.disk_io_counters(perdisk=True)
        entries=[]
        for name,c in io.items():
            read_rate=_rate_snapshot('disk-read-'+name,c.read_bytes); write_rate=_rate_snapshot('disk-write-'+name,c.write_bytes)
            entries.append({'device':name,'readBytes':c.read_bytes,'writeBytes':c.write_bytes,'readBytesPerSec':read_rate,'writeBytesPerSec':write_rate,'readMBps':round(read_rate/1024**2,3) if read_rate is not None else None,'writeMBps':round(write_rate/1024**2,3) if write_rate is not None else None,'readCount':c.read_count,'writeCount':c.write_count,'readIOPS':_rate_snapshot('disk-readops-'+name,c.read_count),'writeIOPS':_rate_snapshot('disk-writeops-'+name,c.write_count),'readTimeMs':c.read_time,'writeTimeMs':c.write_time,'busyTimeMs':getattr(c,'busy_time',None)})
        result['io']=entries
    except Exception as exc: result['error']=str(exc)[:180]
    for name,path in [('Project root',ROOT),('Models (Ollama default)',Path.home()/'.ollama'/'models'),('LM Studio models',Path.home()/'.lmstudio'/'models'),('ComfyUI W drive',Path('W:/--Comfy')),('Hugging Face cache',Path.home()/'.cache'/'huggingface')]:
        try:
            if path.exists():
                cache_key=str(path)
                cached=_FOLDER_SIZE_CACHE.get(cache_key)
                if cached and time.monotonic()-_FOLDER_SIZE_CACHE_AT<300:
                    total,files,partial=cached
                else:
                    total=0; files=0; partial=False
                    for base,dirs,names in os.walk(path):
                        dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','venv','__pycache__'}]
                        for fn in names:
                            try: total+=os.path.getsize(os.path.join(base,fn)); files+=1
                            except OSError: pass
                            if files>=5000: partial=True; break
                        if partial: break
                    _FOLDER_SIZE_CACHE[cache_key]=(total,files,partial)
                    _FOLDER_SIZE_CACHE_AT=time.monotonic()
                result['projectFolders'].append({'name':name,'path':str(path),'sizeBytes':total,'filesScanned':files,'partialScan':partial,'cacheSeconds':300})
            else: result['projectFolders'].append({'name':name,'path':str(path),'exists':False})
        except Exception: pass
    try:
        import subprocess
        ps=r"$ErrorActionPreference='Stop'; Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size,HealthStatus,OperationalStatus | ConvertTo-Json -Compress"
        run=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=2.2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode==0 and run.stdout.strip():
            data=json.loads(run.stdout); result['physicalDevices']=data if isinstance(data,list) else [data]
    except Exception: pass
    return result

def _extended_network():
    import time
    out={'rates':[],'defaultGateways':[],'dnsServers':[],'internet':None,'tcpConnections':None,'serviceChecks':[],'note':'Per-process network accounting is not provided by psutil on Windows without ETW/WFP-based collection.'}
    try:
        import psutil
        counters=psutil.net_io_counters(pernic=True)
        for name,c in counters.items():
            rx=_rate_snapshot('net-rx-'+name,c.bytes_recv); tx=_rate_snapshot('net-tx-'+name,c.bytes_sent)
            out['rates'].append({'adapter':name,'receiveBytesPerSec':rx,'sendBytesPerSec':tx,'receiveMbps':round(rx*8/1e6,3) if rx is not None else None,'sendMbps':round(tx*8/1e6,3) if tx is not None else None})
        out['tcpConnections']=len(psutil.net_connections(kind='tcp'))
    except Exception as exc: out['error']=str(exc)[:180]
    try:
        import subprocess
        cmd="Get-NetIPConfiguration | Where-Object {$_.NetAdapter.Status -eq 'Up'} | Select-Object InterfaceAlias,@{n='IPv4Gateway';e={$_.IPv4DefaultGateway.NextHop -join ','}},@{n='DNSServers';e={$_.DNSServer.ServerAddresses -join ','}} | ConvertTo-Json -Compress"
        run=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,text=True,timeout=2.2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode==0 and run.stdout.strip():
            data=json.loads(run.stdout); data=data if isinstance(data,list) else [data]
            for x in data:
                if x.get('IPv4Gateway'): out['defaultGateways'].append({'adapter':x.get('InterfaceAlias'),'gateway':x.get('IPv4Gateway')})
                if x.get('DNSServers'): out['dnsServers'].append({'adapter':x.get('InterfaceAlias'),'servers':x.get('DNSServers')})
    except Exception: pass
    checks=[('Ollama','http://127.0.0.1:11434/api/tags'),('LM Studio','http://127.0.0.1:1234/v1/models'),('GitHub API','https://api.github.com')]
    import urllib.request
    for name,url in checks:
        started=time.monotonic()
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'PQlocalAgentOSv3-telemetry'})
            with urllib.request.urlopen(req,timeout=1.2) as response: status=response.status
            out['serviceChecks'].append({'name':name,'available':200<=status<400,'statusCode':status,'latencyMs':round((time.monotonic()-started)*1000,1),'checkedAt':datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
        except Exception as exc: out['serviceChecks'].append({'name':name,'available':False,'error':str(exc)[:140],'latencyMs':round((time.monotonic()-started)*1000,1),'checkedAt':datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
    try:
        req=urllib.request.Request('https://www.msftconnecttest.com/connecttest.txt',headers={'User-Agent':'PQlocalAgentOSv3-telemetry'})
        with urllib.request.urlopen(req,timeout=1.5) as response: out['internet']={'available':response.status==200,'statusCode':response.status}
    except Exception as exc: out['internet']={'available':False,'error':str(exc)[:140]}
    return out

def _windows_details():
    import time
    global _WINDOWS_CACHE, _WINDOWS_CACHE_AT
    if _WINDOWS_CACHE is not None and time.monotonic()-_WINDOWS_CACHE_AT<60:
        return _WINDOWS_CACHE
    out={'timezone':datetime.datetime.now().astimezone().tzname(),'localTime':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'startupItems':[],'services':[],'events':[],'security':{},'recentShutdowns':[],'powerPlan':None,'drivers':[],'note':'Windows event logs, Defender and driver inventory may require additional permissions.'}
    try:
        import subprocess
        ps=r"$ErrorActionPreference='SilentlyContinue'; $s=@{}; $s.edition=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID; $s.build=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild; $s.displayVersion=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion; $s.services=(Get-CimInstance Win32_Service | Where-Object {$_.State -eq 'Running'} | Select-Object -First 80 Name,DisplayName,StartMode,State); $s.startup=(Get-CimInstance Win32_StartupCommand | Select-Object -First 80 Name,Command,Location,User); $s.power=(powercfg /getactivescheme); $s.security=@{firewall=(Get-NetFirewallProfile | Select-Object Name,Enabled); defender=(Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureLastUpdated)}; $s.events=(Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2,3;StartTime=(Get-Date).AddHours(-24)} -MaxEvents 30 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,Message); $s.shutdowns=(Get-WinEvent -FilterHashtable @{LogName='System';Id=41,1074,6006,6008;StartTime=(Get-Date).AddDays(-14)} -MaxEvents 20 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName,Message); $s | ConvertTo-Json -Depth 5 -Compress"
        run=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode==0 and run.stdout.strip():
            data=json.loads(run.stdout)
            out.update({'edition':data.get('edition'),'build':data.get('build'),'displayVersion':data.get('displayVersion'),'services':data.get('services') or [],'startupItems':data.get('startup') or [],'powerPlan':data.get('power'),'security':data.get('security') or {},'events':data.get('events') or [],'recentShutdowns':data.get('shutdowns') or []})
    except Exception as exc: out['collectionError']=str(exc)[:180]
    _WINDOWS_CACHE=out
    _WINDOWS_CACHE_AT=time.monotonic()
    return out

def _ai_runtime_stats():
    out={'ollamaRunningModels':None,'ollamaApiLatencyMs':None,'agents':{},'tasks':{},'recentPlatformEvents':[]}
    started=__import__('time').monotonic()
    try:
        req=urllib.request.Request(OLLAMA_URL+'/api/ps')
        with urllib.request.urlopen(req,timeout=1.2) as response: data=json.loads(response.read())
        out['ollamaRunningModels']=data.get('models',[])
        out['ollamaApiLatencyMs']=round((__import__('time').monotonic()-started)*1000,1)
    except Exception as exc: out['ollamaError']=str(exc)[:160]
    for kind in ('agents','tasks'):
        try:
            items=domain_items(kind)
            statuses={}
            for item in items:
                status=str(item.get('status','unknown')).lower(); statuses[status]=statuses.get(status,0)+1
            out[kind]={'total':len(items),'statuses':statuses,'items':[{'id':x.get('id'),'name':x.get('name',x.get('title')),'status':x.get('status'),'model':x.get('model'),'provider':x.get('provider'),'updated_at':x.get('updated_at'),'created_at':x.get('created_at')} for x in items[:100]]}
        except Exception as exc: out[kind]={'error':str(exc)[:120]}
    try: out['recentPlatformEvents']=read_json(DATA/'events.json',[])[:30]
    except Exception: pass
    return out



def _telemetry_snapshot():
    import time
    global _TELEMETRY_CACHE, _TELEMETRY_CACHE_AT
    now = time.monotonic()
    if _TELEMETRY_CACHE is not None and now - _TELEMETRY_CACHE_AT < 2:
        return _TELEMETRY_CACHE
    data = system_stats()
    with _TELEMETRY_CACHE_LOCK:
        if _TELEMETRY_CACHE is not None and time.monotonic() - _TELEMETRY_CACHE_AT < 2:
            return _TELEMETRY_CACHE
        sample = {'timestamp': data.get('timestamp'),
                  'cpuPercent': (data.get('cpu') or {}).get('percent'),
                  'ramPercent': (data.get('ram') or {}).get('percent'),
                  'gpuPercent': (data.get('gpu') or {}).get('percent'),
                  'gpuTemperatureC': (data.get('gpu') or {}).get('temperatureC'),
                  'ramUsedGB': (data.get('ram') or {}).get('used')}
        _TELEMETRY_HISTORY.append(sample)
        del _TELEMETRY_HISTORY[:-360]
        _TELEMETRY_CACHE = data
        _TELEMETRY_CACHE_AT = time.monotonic()
    return data

def _telemetry_schema_node(value, path=''):
    if isinstance(value,dict):
        return {'type':'object','properties':{str(k):_telemetry_schema_node(v,path+'.'+str(k)) for k,v in value.items()}}
    if isinstance(value,list):
        item_schema=_telemetry_schema_node(value[0],path+'[]') if value else {'type':'unknown','description':'Пустой массив; схема элемента определяется по фактическому ответу API.'}
        return {'type':'array','items':item_schema}
    if value is None: return {'type':'null','nullable':True}
    if isinstance(value,bool): return {'type':'boolean'}
    if isinstance(value,int): return {'type':'integer'}
    if isinstance(value,float): return {'type':'number'}
    return {'type':'string'}

def _telemetry_api_schema():
    sample=system_stats()
    return {'ok':True,'apiVersion':'1.0','service':'PQlocalAgentOSv3 system telemetry',
            'description':'Возвращаются только CPU, RAM/файл подкачки, GPU, операционная система и среда Python. Недоступные значения обозначаются null или available=false.',
            'endpoints':[
                {'method':'GET','path':'/api/system/stats','description':'Снимок только выбранных показателей: CPU, RAM/файл подкачки, GPU, ОС и среда Python. Снимок кэшируется на 5 секунд.'},
                {'method':'GET','path':'/api/system/stats/schema','description':'JSON Schema-подобное описание структуры полей полного ответа.'},
                {'method':'GET','path':'/api/system/stats/history?limit=60','description':'История снятых образцов телеметрии; до 360 последних образцов в памяти текущего процесса сервера.'}
            ],
            'refreshHintSeconds':5,'historyMaxSamples':360,'schema':_telemetry_schema_node(sample)}


def _telemetry_unavailable_fields():
    checked=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    def unavailable(source,reason):
        return {'value':None,'available':False,'source':source,'checkedAt':checked,'reason':reason}
    return {
      'cpu':{
        'temperatureC':unavailable('Windows hardware sensors','Нет универсального CPU temperature API в Windows; нужен поддерживаемый датчик/LibreHardwareMonitor.'),
        'powerW':unavailable('Hardware power sensor','Мощность CPU не предоставляется стандартным счётчиком на этом оборудовании.'),
        'perCoreFrequencyMHz':unavailable('CPU frequency counters','Частота каждого ядра не предоставлена текущим системным API/драйвером.'),
        'processorQueueLength':unavailable('Windows Performance Counters','Очередь процессора не удалось получить надёжным системным счётчиком.'),
        'baseFrequencyMHz':unavailable('CPU firmware/registry','Базовая частота не гарантируется для всех CPU; используйте cpuDetails.baseMHz если доступна.')
      },
      'ram':{
        'hardwareReservedGB':unavailable('Windows memory counters','Windows API, используемый приложением, не возвращает отдельный объём аппаратно зарезервированной RAM.'),
        'readBytesPerSec':unavailable('Windows memory performance counters','Скорость чтения RAM не является стандартным счётчиком psutil.'),
        'writeBytesPerSec':unavailable('Windows memory performance counters','Скорость записи RAM не является стандартным счётчиком psutil.'),
        'peakWorkingSetPerProcess':unavailable('Per-process memory counters','Пиковый working set зависит от доступных прав и Windows API; текущие рабочие наборы доступны в processes.')
      },
      'gpu':{
        'engine3DPercent':unavailable('Windows GPU engine counters','Счётчики 3D движка не предоставлены драйвером в доступном формате.'),
        'engineComputePercent':unavailable('Windows GPU engine counters','Счётчики Compute движка не предоставлены драйвером в доступном формате.'),
        'engineCopyPercent':unavailable('Windows GPU engine counters','Счётчики Copy движка не предоставлены драйвером в доступном формате.'),
        'engineVideoEncodePercent':unavailable('Windows GPU engine counters','Счётчики Video Encode движка не предоставлены драйвером в доступном формате.'),
        'engineVideoDecodePercent':unavailable('Windows GPU engine counters','Счётчики Video Decode движка не предоставлены драйвером в доступном формате.'),
        'fanRPM':unavailable('NVIDIA/board sensor','Доступен только процент вентилятора, если его возвращает nvidia-smi; RPM не предоставлены.'),
        'totalSystemPowerW':unavailable('Hardware power meter','Общая мощность ноутбука требует аппаратного измерителя/производительского API.'),
        'throttleReasonTemperature':unavailable('NVIDIA driver','Отдельная причина температурного троттлинга зависит от поддержки драйвером.'),
        'throttleReasonPower':unavailable('NVIDIA driver','Отдельная причина ограничения мощности зависит от поддержки драйвером.')
      },
      'disks':{
        'averageResponseMs':unavailable('Windows disk performance counters','Среднее время отклика не получено отдельным счётчиком.'),
        'queueLength':unavailable('Windows disk performance counters','Очередь диска не получена отдельным счётчиком.'),
        'activePercent':unavailable('Windows disk performance counters','Процент активности требует доступного Performance Counter.'),
        'temperatureC':unavailable('SMART/vendor storage driver','Температура диска не доступна через стандартный API; зависит от контроллера/SMART.'),
        'smartHealth':unavailable('SMART/vendor storage driver','SMART-состояние не доступно универсально через стандартный API Windows.'),
        'powerOnHours':unavailable('SMART/vendor storage driver','Часы работы накопителя зависят от SMART/производителя.'),
        'totalBytesWritten':unavailable('SMART/vendor storage driver','Объём записи накопителя зависит от SMART/производителя.')
      },
      'network':{
        'packetLossPercent':unavailable('ICMP probe','Потери пакетов требуют регулярных проверок конкретного узла; однократный запрос не является надёжной статистикой.'),
        'latencyMs':unavailable('ICMP probe','Постоянная задержка требует заданного целевого узла и периодических измерений.'),
        'internetSpeedMbps':unavailable('Bandwidth test','Тест скорости интернета не выполняется автоматически, чтобы не создавать лишний трафик.'),
        'perProcessTraffic':unavailable('ETW/WFP network collector','Трафик отдельных процессов требует ETW/WFP или отдельного сетевого коллектора.'),
        'subnetAndGatewayByAdapter':unavailable('Windows IP configuration','Сведения шлюза/DNS могут отсутствовать для отключённых или виртуальных адаптеров.')
      },
      'windows':{
        'windowsUpdateStatus':unavailable('Windows Update API','Состояние обновлений не подтверждено через Windows Update API.'),
        'driverHealth':unavailable('Device Manager/PnP','Общее состояние драйверов не подтверждено отдельной проверкой устройств.'),
        'recentApplicationCrashes':unavailable('Windows Application event log','Полный список сбоев приложений требует отдельного чтения журнала Application.'),
        'shutdownReason':unavailable('Windows System event log','Причина доступна только если Windows записала соответствующее событие.'),
        'defenderStatus':unavailable('Windows Defender cmdlets','Если PowerShell-команда недоступна или нет прав, состояние Defender не подтверждено.')
      },
      'processes':{
        'networkBytesPerSec':unavailable('ETW/WFP network collector','psutil не предоставляет универсальный учёт сети по процессам в Windows.'),
        'gpuPercentPerProcess':unavailable('Windows GPU engine/NVIDIA telemetry','GPU-процент процесса зависит от драйвера и счётчиков GPU Engine.'),
        'gpuMemoryBytesPerProcess':unavailable('NVIDIA driver / Windows GPU counters','VRAM по процессам доступна не для всех типов процессов/драйверов.'),
        'exitCode':unavailable('Process lifecycle monitor','Код завершения доступен только для процессов, завершение которых приложение отслеживало заранее.')
      },
      'aiRuntime':{
        'modelContextLength':unavailable('Provider model metadata','Размер контекста доступен только если конкретный провайдер/model API предоставляет это поле.'),
        'tokensPerSecond':unavailable('Inference request instrumentation','Скорость токенов появится для запросов, выполняемых через инструментированный runtime платформы.'),
        'inputOutputTokenCounts':unavailable('Inference request instrumentation','Количество токенов доступно только если API/модель возвращает usage или runtime его считает.'),
        'modelLoadDurationMs':unavailable('Inference request instrumentation','Время загрузки модели требует измерения вокруг команды загрузки/первого запроса.'),
        'perModelGpuMemory':unavailable('NVIDIA process mapping','Связать VRAM с конкретной моделью можно только при сопоставлении PID процесса и модели.'),
        'taskQueueLength':unavailable('Task scheduler instrumentation','Число ожидающих задач требует отдельного состояния очереди планировщика.'),
        'successfulRunCount':unavailable('Persisted task run history','История успешных запусков доступна только если исполнитель сохраняет каждую попытку.'),
        'failedRunCount':unavailable('Persisted task run history','История неуспешных запусков требует сохранения каждого результата исполнения.'),
        'averageTaskDurationMs':unavailable('Persisted task run history','Средняя длительность рассчитывается после сохранения времён начала и завершения запусков.'),
        'taskRetryCounts':unavailable('Task execution history','Счётчик повторов зависит от сохранения попыток в исполнительном контуре задач.'),
        'taskFailureReasons':unavailable('Task execution history','Причины ошибок доступны из сохранённых результатов и журналов конкретных запусков.'),
        'currentTaskStage':unavailable('Task execution instrumentation','Этап задачи обновляется только при инструментировании исполнителя на каждом шаге.'),
        'lastSuccessfulModelCall':unavailable('Inference request instrumentation','Последний успешный вызов модели требует журнала вызовов провайдера.'),
        'perTaskProviderAndModel':unavailable('Task execution history','Провайдер и модель на каждую задачу должны фиксироваться при запуске.'),
        'perTaskTokenUsage':unavailable('Inference request instrumentation','Токены на задачу требуют учёта usage со стороны модели или runtime.')
      }
    }

def system_stats():
    import platform
    import time
    # Собираем только CPU, RAM/файл подкачки, GPU, ОС и среду Python.
    cpu_percent = _cpu_usage()
    memory = _memory_stats()
    gpu = _gpu_stats()
    try:
        import psutil
        cpu_frequency = psutil.cpu_freq()
        boot_timestamp = psutil.boot_time()
        cpu_physical = psutil.cpu_count(logical=False)
        cpu_logical = psutil.cpu_count(logical=True)
        cpu_frequency_data = {'currentMHz': round(cpu_frequency.current, 1) if cpu_frequency else None,
                              'minMHz': round(cpu_frequency.min, 1) if cpu_frequency else None,
                              'maxMHz': round(cpu_frequency.max, 1) if cpu_frequency else None}
        uptime_seconds = max(0, int(time.time() - boot_timestamp))
        process_count = len(psutil.pids())
        thread_count = None
        try:
            thread_count = sum(p.info.get('num_threads') or 0 for p in psutil.process_iter(['num_threads']))
        except Exception:
            pass
    except Exception:
        cpu_physical = None
        cpu_logical = os.cpu_count()
        cpu_frequency_data = {'currentMHz': None, 'minMHz': None, 'maxMHz': None}
        uptime_seconds = None
        process_count = None
        thread_count = None
    os_data = {'system': platform.system(), 'release': platform.release(), 'version': platform.version(),
               'edition': platform.win32_edition() if hasattr(platform, 'win32_edition') else None,
               'architecture': platform.architecture()[0], 'machine': platform.machine(),
               'hostname': platform.node(), 'pythonVersion': platform.python_version(),
               'pythonImplementation': platform.python_implementation()}
    try:
        uptime_ms = __import__('ctypes').windll.kernel32.GetTickCount64()
        uptime_seconds = int(uptime_ms / 1000)
    except Exception:
        pass
    try:
        boot_time = datetime.datetime.now().astimezone() - datetime.timedelta(seconds=uptime_seconds) if uptime_seconds is not None else None
        boot_iso = boot_time.isoformat(timespec='seconds') if boot_time else None
    except Exception:
        boot_iso = None
    cpu = {'available': cpu_percent is not None, 'percent': cpu_percent, 'name': _cpu_name(),
           'physicalCores': cpu_physical, 'logicalCores': cpu_logical, 'frequency': cpu_frequency_data,
           'processCount': process_count, 'threadCount': thread_count}
    return {
        'ok': True,
        'timestamp': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'collection': {'source':'local Windows host','optionalDependency':'psutil + optional NVIDIA nvidia-smi; unavailable hardware sensors are returned as null','refreshHintSeconds':5},
        'cpu': cpu, 'ram': memory, 'gpu': gpu,
        'system': {'os':os_data,'uptimeSeconds':uptime_seconds,'bootTime':boot_iso,'processCount':process_count,'threadCount':thread_count}
    }


class Handler(SimpleHTTPRequestHandler):
    def _check_host(self):
        raw_host = str(self.headers.get('Host', '')).strip()
        try:
            host = urllib.parse.urlsplit('//' + raw_host).hostname
        except ValueError:
            host = None
        if host not in ('127.0.0.1', 'localhost', '::1'):
            self.send_json(403, {'error': 'Forbidden: Invalid Host header'})
            return False
        return True

    def _must_change_password_blocked(self, path):
        if not AUTH_ENABLED or not path.startswith('/api/'):
            return False
        if path in ('/api/auth/change-password', '/api/auth/status'):
            return False
        if not self.auth_session():
            return False
        config = read_json(AUTH_FILE, {})
        if not bool(config.get('must_change_password', False)):
            return False
        self.send_json(403, {'error': 'Требуется смена пароля', 'must_change_password': True})
        return True
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(FRONTEND),**kwargs)
    def log_message(self, fmt, *args): pass
    def send_json(self, code, data, headers=None):
        raw=json.dumps(data,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store')
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(raw)
    def auth_session(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except Exception: return None
        morsel = cookie.get('pq_session')
        if not morsel: return None
        token = morsel.value
        now = datetime.datetime.now(datetime.timezone.utc)
        with AUTH_SESSIONS_LOCK:
            session = AUTH_SESSIONS.get(token)
            if not session: return None
            if session['expires'] <= now:
                AUTH_SESSIONS.pop(token, None)
                return None
            return session
    def require_auth(self):
        if not AUTH_ENABLED: return True
        session = self.auth_session()
        if not session:
            self.send_json(401, {'error':'Требуется вход в систему', 'auth_required':True})
            return False
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            config = read_json(AUTH_FILE, {})
            if bool(config.get('must_change_password', False)) and path not in ('/api/auth/change-password', '/api/auth/status'):
                self.send_json(403, {'error': 'Требуется смена пароля', 'must_change_password': True})
                return False
        return True
    def auth_cookie(self, token, max_age):
        return {'Set-Cookie': 'pq_session=' + token + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=' + str(max_age)}
    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>1_000_000: raise ValueError('Payload too large')
        return json.loads(self.rfile.read(n).decode('utf-8') or '{}')
    def do_GET(self):
        if not self._check_host(): return
        path=urlparse(self.path).path
        if self._must_change_password_blocked(path): return
        if path.startswith('/project/logo/'):
            if not self.require_auth(): return
            filename = Path(urllib.parse.unquote(path)).name
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.(?:png|jpg|webp|gif)', filename):
                return self.send_json(404, {'error': 'Логотип не найден'})
            target = PROJECT_LOGO_DIR / filename
            if not target.is_file():
                return self.send_json(404, {'error': 'Логотип не найден'})
            mime = {'png':'image/png','jpg':'image/jpeg','webp':'image/webp','gif':'image/gif'}[target.suffix[1:]]
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(target.stat().st_size))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(target.read_bytes())
            return
        if path == '/api/auth/status':
            session = self.auth_session()
            config = read_json(AUTH_FILE, {})
            return self.send_json(200, {'auth_enabled':AUTH_ENABLED, 'authenticated':bool(session), 'username':session.get('username') if session else None, 'must_change_password':bool(config.get('must_change_password', False)) if session else False})
        if path=='/api/health': return self.send_json(200, {'ok':True,'app':'PQlocalAgentOSv3','host':HOST,'port':PORT,'time':datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
        if path.startswith('/api/') and not self.require_auth(): return
        if path == '/api/chat/activity':
            query = parse_qs(urlparse(self.path).query)
            chat_id = (query.get('chat_id') or [''])[0]
            if not str(chat_id).strip():
                return self.send_json(400, {'error': 'Укажите chat_id'})
            return self.send_json(200, _get_agent_activity(chat_id))
        if path == '/api/chat/conversations':
            try: return self.send_json(200, {'items': CHAT_STORE.list_conversations()})
            except Exception as exc: return self.send_json(500, {'error':'Не удалось прочитать список диалогов: '+str(exc)[:200]})
        if path == '/api/chat/history':
            qs = parse_qs(urlparse(self.path).query); cid = str((qs.get('conversation_id') or [''])[0])
            try: after = max(0, int((qs.get('after') or ['0'])[0]))
            except (TypeError, ValueError): return self.send_json(400, {'error':'Параметр after должен быть целым числом'})
            try: return self.send_json(200, {'events':CHAT_STORE.read_after(cid,after),'meta':CHAT_STORE.get_meta(cid)})
            except Exception as exc: return self.send_json(400, {'error':str(exc)[:240]})
        if path == '/api/chat/events':
            qs = parse_qs(urlparse(self.path).query); cid = str((qs.get('conversation_id') or [''])[0])
            try: after = max(0,int((qs.get('after') or ['0'])[0])); CHAT_STORE.get_meta(cid)
            except Exception as exc: return self.send_json(400, {'error':'Некорректный диалог или after: '+str(exc)[:160]})
            subscriber = CHAT_HUB.subscribe(cid)
            try:
                history = CHAT_STORE.read_after(cid,after)
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream; charset=utf-8')
                self.send_header('Cache-Control','no-cache, no-transform')
                self.send_header('Connection','keep-alive')
                self.send_header('X-Accel-Buffering','no')
                self.end_headers()
                last_sent = after
                def send_event(event):
                    self.wfile.write(('event: message\ndata: '+json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n\n').encode('utf-8'))
                    self.wfile.flush()
                for event in history:
                    if event['sequence'] > last_sent: send_event(event); last_sent = event['sequence']
                while True:
                    try: event = subscriber.get(timeout=15)
                    except __import__('queue').Empty:
                        self.wfile.write(b': keep-alive\n\n'); self.wfile.flush(); continue
                    seq = int(event.get('sequence',0))
                    if seq <= last_sent: continue
                    if seq != last_sent + 1: break
                    send_event(event); last_sent = seq
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError): pass
            finally: CHAT_HUB.unsubscribe(cid,subscriber)
            return
        if path == '/api/audit/run':
            report = audit_checks.run_audit(ROOT)
            try:
                audit_checks.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                audit_checks.REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError as exc:
                return self.send_json(500, {'error': 'Не удалось сохранить отчёт аудита', 'detail': str(exc)[:300]})
            return self.send_json(200, report)
        if path == '/api/audit/report':
            report_path = (DATA / 'audit_last_report.json').resolve()
            if not report_path.is_relative_to(DATA.resolve()) or not report_path.is_file():
                return self.send_json(404, {'error': 'Отчёт аудита ещё не создан'})
            try:
                report = json.loads(report_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return self.send_json(500, {'error': 'Не удалось прочитать отчёт аудита'})
            return self.send_json(200, report)
        if path == '/api/avatars/presets':
            presets = []
            for category in ('face', 'glasses', 'hair'):
                category_dir = (AVATARS_DIR / category).resolve()
                if not category_dir.is_relative_to(AVATARS_DIR.resolve()) or not category_dir.is_dir():
                    continue
                for target in sorted(category_dir.iterdir()):
                    try:
                        resolved = target.resolve()
                        if not resolved.is_relative_to(AVATARS_DIR.resolve()) or not target.is_file() or target.suffix.lower() != '.svg':
                            continue
                        presets.append({'category': category, 'name': target.stem, 'url': '/avatars/' + category + '/' + target.name})
                    except OSError:
                        continue
            return self.send_json(200, {'presets': presets})
        if path.startswith('/api/') and not self.require_auth(): return
        if path == '/api/dialog/select-folder':
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                try:
                    root.attributes('-topmost', True)
                    selected = filedialog.askdirectory(parent=root, title='Выберите рабочую папку проекта', mustexist=True)
                finally:
                    root.destroy()
                return self.send_json(200, {'ok':bool(selected),'path':str(Path(selected).resolve()) if selected else ''})
            except Exception as exc:
                return self.send_json(500, {'error':'Не удалось открыть системный выбор папки Windows: '+str(exc)[:300]})
        if path == '/api/system-instructions/defaults':
            ensure_system_instructions()
            return self.send_json(200, {'defaults': system_instruction_defaults()})
        if path == '/api/system-instructions/validate':
            return self.send_json(200, {'warnings': system_instruction_warnings(ensure_system_instructions())})
        if path == '/api/agent-roles':
            items = ensure_agent_roles()
            return self.send_json(200, {'roles': items, 'total': len(items)})
        if path == '/api/system-instructions':
            items = ensure_system_instructions()
            return self.send_json(200, {'instructions': items, 'total': len(items)})
        if path.startswith('/api/projects/') and path.endswith('/memory'):
            pid = urllib.parse.unquote(path.split('/')[-2])
            mem = read_project_memory(pid)
            tasks_all = domain_items('tasks')
            agents_all = domain_items('agents')
            mem['tasks'] = [
                {'id': t.get('id'), 'title': t.get('title'), 'status': t.get('status'),
                 'created_at': t.get('created_at'), 'finished_at': t.get('finished_at'),
                 'agent_id': t.get('agent_id'), 'team_mode': t.get('team_mode')}
                for t in tasks_all if str(t.get('project_id', '')) == str(pid)
            ]
            linked_ids = set(str(value) for value in (mem.get('agent_ids') or []))
            mem['agents'] = [
                {'id': a.get('id'), 'name': a.get('name'), 'role': a.get('role'),
                 'description': a.get('description', ''), 'system': bool(a.get('system')),
                 'system_enabled': bool(a.get('system_enabled', True)), 'model': a.get('model', ''),
                 'status': a.get('status', 'idle'), 'authority': a.get('authority', 99)}
                for a in agents_all if str(a.get('id')) in linked_ids or a.get('system')
            ]
            mem['agents'].sort(key=lambda a: int(a.get('authority', 99)))
            return self.send_json(200, mem)
        if path.startswith('/api/agents/') and path.endswith('/tasks'):
            aid = urllib.parse.unquote(path.split('/')[-2])
            tasks = [t for t in domain_items('tasks') if str(t.get('agent_id', '')) == str(aid)]
            tasks.sort(key=lambda t: str(t.get('created_at', '')), reverse=True)
            return self.send_json(200, {'agent_id': aid, 'tasks': [
                {'id': t.get('id'), 'title': t.get('title'), 'status': t.get('status'),
                 'project_id': t.get('project_id'), 'created_at': t.get('created_at'),
                 'finished_at': t.get('finished_at')} for t in tasks[:100]
            ]})
        if path.startswith('/api/tasks/') and path.endswith('/context'):
            tid = urllib.parse.unquote(path.split('/')[-2])
            task = next((t for t in domain_items('tasks') if str(t.get('id')) == tid), None)
            if not task: return self.send_json(404, {'error': 'Задача не найдена'})
            pid = str(task.get('project_id', '')).strip()
            aid = str(task.get('agent_id', '')).strip()
            project = next((p for p in domain_items('projects') if str(p.get('id')) == pid), None)
            agent = next((a for a in domain_items('agents') if str(a.get('id')) == aid), None)
            mem = read_project_memory(pid) if pid else _empty_project_memory('')
            return self.send_json(200, {
                'task': task,
                'project': {'id': project.get('id'), 'name': project.get('name')} if project else None,
                'agent': {'id': agent.get('id'), 'name': agent.get('name'), 'role': agent.get('role')} if agent else None,
                'memory': {'summary': mem.get('summary'), 'constraints': mem.get('constraints'),
                           'open_questions': mem.get('open_questions'), 'facts': mem.get('facts', [])[-15:],
                           'next_steps': mem.get('next_steps')}
            })
        if path.startswith('/api/system-instructions/') and path.endswith('/history'):
            instruction_id = urllib.parse.unquote(path[len('/api/system-instructions/'):].rsplit('/', 1)[0])
            history = read_json(_system_instruction_history_path(), [])
            if not isinstance(history, list): history = []
            return self.send_json(200, {'id': instruction_id, 'history': [entry for entry in history if isinstance(entry, dict) and entry.get('id') == instruction_id][:50]})
        if path.startswith('/api/agent-roles/'):
            role_id = urllib.parse.unquote(path[len('/api/agent-roles/'):])
            items = ensure_agent_roles()
            item = next((x for x in items if x.get('id') == role_id), None)
            if not item: return self.send_json(404, {'error': 'Роль не найдена'})
            if item.get('is_system'): return self.send_json(403, {'error': 'Системную роль нельзя удалить'})
            assigned = [a.get('name', a.get('id', '')) for a in domain_items('agents') if str(a.get('role', '')).upper() == str(item.get('code', '')).upper()]
            if assigned: return self.send_json(409, {'error': 'Роль назначена агентам: ' + ', '.join(assigned[:5]) + '. Сначала назначьте им другие роли.'})
            save_agent_roles([x for x in items if x.get('id') != role_id])
            log_event('agent_role.delete', item.get('name', role_id))
            return self.send_json(200, {'ok': True})
        if path.startswith('/api/github/connections/'):
            connection_id=urllib.parse.unquote(path[len('/api/github/connections/'):]).strip()
            saved=github_connections(); found=next((x for x in saved['connections'] if x.get('id')==connection_id),None)
            if not found: return self.send_json(404, {'error':'Подключение не найдено'})
            saved['connections']=[x for x in saved['connections'] if x.get('id')!=connection_id]
            if saved.get('active_id')==connection_id: saved['active_id']=saved['connections'][0].get('id','') if saved['connections'] else ''
            write_json(GITHUB_CONNECTIONS_FILE,saved); log_event('github.connection.delete',found.get('repository',''))
            return self.send_json(200, {'ok':True})
        if path.startswith('/api/system-instructions/'):
            instruction_id = urllib.parse.unquote(path[len('/api/system-instructions/'):])
            if not instruction_id or '/' in instruction_id: return self.send_json(404, {'error': 'Инструкция не найдена'})
            item = next((x for x in ensure_system_instructions() if x.get('id') == instruction_id), None)
            if not item: return self.send_json(404, {'error': 'Инструкция не найдена'})
            return self.send_json(200, item)
        if path=='/api/diagnostics': return self.send_json(200, run_diagnostics())
        if path=='/api/system/stats':
            try:
                return self.send_json(200, _telemetry_snapshot())
            except Exception as exc:
                return self.send_json(500, {'ok':False,'error':str(exc),'errorType':type(exc).__name__})
        if path=='/api/system/stats/schema':
            try:
                return self.send_json(200, _telemetry_api_schema())
            except Exception as exc:
                return self.send_json(500, {'ok':False,'error':str(exc),'errorType':type(exc).__name__})
        if path=='/api/system/stats/history':
            try:
                query=parse_qs(urlparse(self.path).query)
                limit=max(1,min(360,int(query.get('limit',['60'])[0])))
                return self.send_json(200, {'ok':True,'count':min(limit,len(_TELEMETRY_HISTORY)),'maxSamples':360,'samples':_TELEMETRY_HISTORY[-limit:]})
            except (ValueError,TypeError) as exc:
                return self.send_json(400, {'ok':False,'error':'Параметр limit должен быть числом от 1 до 360','detail':str(exc)[:120]})
        if path == '/api/models/search/hf':
            query = parse_qs(urlparse(self.path).query)
            q = str((query.get('q') or [''])[0]).strip()[:200]
            try: limit = max(1, min(20, int((query.get('limit') or ['10'])[0])))
            except (TypeError, ValueError): limit = 10
            if not q: return self.send_json(400, {'error':'Введите запрос для поиска на Hugging Face'})
            if HfApi is None: return self.send_json(503, {'error':'Библиотека huggingface_hub не установлена'})
            try:
                api = HfApi()
                found = api.list_models(search=q, filter='gguf', sort='downloads', limit=limit)
                items = []
                for info in found:
                    repo_id = str(getattr(info, 'id', '') or '')
                    try: files = [name for name in api.list_repo_files(repo_id=repo_id, repo_type='model') if name.lower().endswith('.gguf') and '..' not in Path(name).parts]
                    except Exception: files = []
                    items.append({'id':repo_id,'downloads':int(getattr(info,'downloads',0) or 0),'likes':int(getattr(info,'likes',0) or 0),'tags':list(getattr(info,'tags',[]) or []),'files':files[:100]})
                return self.send_json(200, {'items':items,'total':len(items),'query':q})
            except Exception as exc: return self.send_json(502, {'error':'Поиск Hugging Face не выполнен: '+str(exc)[:220]})
        if path == '/api/models/folders':
            try:
                folders = read_json(DATA/'model_folders.json', [])
                if not isinstance(folders, list): folders = []
                return self.send_json(200, {'folders':[str(x) for x in folders if isinstance(x, str)]})
            except Exception as exc:
                return self.send_json(500, {'error':str(exc),'errorType':type(exc).__name__})
        if path == '/api/models/local-files':
            try:
                folders = read_json(DATA/'model_folders.json', [])
                files = []
                for raw in folders if isinstance(folders, list) else []:
                    try:
                        root = Path(str(raw)).expanduser().resolve()
                        if not root.is_dir(): continue
                        for candidate in root.rglob('*.gguf'):
                            try:
                                if candidate.is_file() and not any(part.startswith('.') for part in candidate.relative_to(root).parts):
                                    files.append({'name':candidate.name,'path':str(candidate.resolve()),'size':candidate.stat().st_size})
                            except OSError: pass
                            if len(files) >= 1000: break
                    except (OSError, ValueError, RuntimeError): pass
                    if len(files) >= 1000: break
                files.sort(key=lambda item:item['name'].lower())
                return self.send_json(200, {'files':files,'total':len(files)})
            except Exception as exc:
                return self.send_json(500, {'error':str(exc),'errorType':type(exc).__name__})
        if path=='/api/providers':
            items=provider_items(); models=[]
            for p in items:
                found=[]; connected=False
                if p.get('kind') in ('local','file') or p.get('api_key'):
                    try: found=provider_models(p); connected=True
                    except Exception: pass
                p['connected']=connected; p['model_count']=len(found); p['api_key_set']=bool(p.get('api_key'))
                for m in found: models.append({'provider':p.get('name',''),'provider_id':p.get('id'),'kind':p.get('kind','local'),'name':m.get('name',''),'parameter_size':m.get('parameter_size','—'),'size':m.get('size',0),'connected':connected})
            return self.send_json(200, {'providers':[public_provider(p) for p in items], 'models':models})
        if path=='/api/models':
            try:
                payload=ollama_request('/api/tags',timeout=4)
                models=[{'name':m.get('name',''),'size':m.get('size',0),'modified_at':m.get('modified_at','')} for m in payload.get('models',[]) if isinstance(m,dict) and m.get('name')]
                return self.send_json(200, {'provider':'ollama','base_url':OLLAMA_URL,'connected':True,'models':models,'error':None})
            except Exception as e: return self.send_json(200, {'provider':'ollama','base_url':OLLAMA_URL,'connected':False,'models':[],'error':'Не удалось подключиться к Ollama: '+str(e)[:180]})
        if path in ('/api/agents','/api/projects','/api/tasks'):
            kind=path.split('/')[-1]; items=domain_items(kind)
            return self.send_json(200, {'items':items,'total':len(items)})
        if path=='/api/settings': return self.send_json(200, settings())
        if path=='/api/pages': return self.send_json(200, pages())
        if path=='/api/log': return self.send_json(200, read_json(DATA/'events.json', []))
        if path == '/api/system/map':
            return self.send_json(200, {
                'nodes': [
                    {'id':'manager','label':'Менеджер (Генерал)','type':'role','description':'Принимает решения, утверждает общий план и итоговый результат. Не читает файлы и не получает путь к проекту.'},
                    {'id':'dispatcher','label':'Диспетчер (Премьер)','type':'role','description':'Собирает контекст, маршрутизирует задачи активным специалистам, принимает их отчёты и передаёт сводку менеджеру.'},
                    {'id':'coder','label':'Кодер','type':'role','description':'Выполняет назначенные задачи по разработке и изменению кода в разрешённой рабочей папке проекта.'},
                    {'id':'tester','label':'Тестер','type':'role','description':'Проверяет код и результаты выполнения назначенных задач в разрешённой рабочей папке проекта.'},
                    {'id':'memory','label':'Память проекта','type':'storage','description':'Хранит сводку, факты, ограничения, открытые вопросы и следующие шаги проекта.'},
                    {'id':'tools','label':'Инструменты (Файлы, GitHub, Терминал)','type':'tool','description':'Инструменты работы с файлами, GitHub и терминалом. Доступ зависит от разрешений агента.'}
                ],
                'edges': [
                    {'from':'manager','to':'dispatcher','label':'Общий план'},
                    {'from':'dispatcher','to':'coder','label':'Конкретное задание'},
                    {'from':'dispatcher','to':'tester','label':'Конкретное задание'},
                    {'from':'coder','to':'dispatcher','label':'Результат'},
                    {'from':'tester','to':'dispatcher','label':'Результат'},
                    {'from':'dispatcher','to':'manager','label':'Сводка'},
                    {'from':'manager','to':'memory','label':'Читает (без пути)'},
                    {'from':'dispatcher','to':'memory','label':'Читает и пишет'},
                    {'from':'coder','to':'tools','label':'Использует'},
                    {'from':'tester','to':'tools','label':'Использует'}
                ]
            })
        if path=='/api/modules':
            return self.send_json(200, read_json(DATA/'modules.json', {'modules':[], 'connections':[]}))
        if path=='/api/modules/runs':
            return self.send_json(200, read_json(DATA/'module-runs.json', []))
        if path=='/api/permissions': return self.send_json(200, permission_settings())
        if path=='/api/github/search':
            q=parse_qs(urlparse(self.path).query).get('q',[''])[0].strip()[:120]
            if len(q)<2: return self.send_json(400, {'error':'Введите минимум 2 символа для поиска'})
            try:
                result=github_public_request('/search/repositories?q='+urllib.parse.quote(q+' in:name,description,readme')+'&sort=stars&order=desc&per_page=12')
                items=[{'full_name':x.get('full_name',''),'description':x.get('description') or 'Без описания','html_url':x.get('html_url',''),'stars':x.get('stargazers_count',0),'language':x.get('language') or 'Не указан','license':(x.get('license') or {}).get('spdx_id') or 'Не указана','updated_at':x.get('updated_at','')} for x in result.get('items',[])]
                return self.send_json(200, {'items':items,'total_count':result.get('total_count',0)})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        if path=='/api/github/connections':
            saved=github_connections(); items=[]
            for item in saved['connections']:
                items.append({'id':item.get('id'),'name':item.get('name',''),'repository':item.get('repository',REPO),'active':item.get('id')==saved.get('active_id'),'has_token':bool(item.get('token_encrypted')),'updated_at':item.get('updated_at','')})
            return self.send_json(200, {'connections':items,'active_id':saved.get('active_id',''),'encryption':'Windows DPAPI' if sys.platform=='win32' else 'unavailable'})
        if path=='/api/github':
            return self.send_json(200, {'repository':active_github_repository(),'configured':github_token_available(),'connected':False,'message':'Добавьте подключение и API-токен' if not github_token_available() else 'Токен настроен; нажмите «Проверить подключение»'})
        if path=='/api/github/check':
            try: token=github_access_token()
            except Exception as e: return self.send_json(200, {'ok':False,'message':str(e)})
            repository=active_github_repository()
            req=urllib.request.Request('https://api.github.com/repos/'+repository,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'PQlocalAgentOSv3'})
            try:
                with urllib.request.urlopen(req,timeout=8) as res: data=json.loads(res.read())
                log_event('github.check',repository); return self.send_json(200, {'ok':True,'message':'Подключение успешно','repository':data.get('full_name',repository),'private':data.get('private'),'default_branch':data.get('default_branch')})
            except urllib.error.HTTPError as e: return self.send_json(200, {'ok':False,'message':'GitHub вернул HTTP '+str(e.code)+'. Проверьте токен и доступ к репозиторию.'})
            except Exception as e: return self.send_json(200, {'ok':False,'message':'Не удалось подключиться к GitHub: '+str(e)[:180]})
        if path=='/api/github/files':
            try:
                repo=github_request('/repos/'+active_github_repository())
                tree=github_request('/repos/'+active_github_repository()+'/git/trees/'+repo.get('default_branch','main')+'?recursive=1')
                files=[{'path':x['path'],'size':x.get('size',0)} for x in tree.get('tree',[]) if x.get('type')=='blob'][:500]
                return self.send_json(200, {'repository':active_github_repository(),'branch':repo.get('default_branch','main'),'files':files})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        if path=='/api/github/file':
            file_path=parse_qs(urlparse(self.path).query).get('path',[''])[0]
            if not file_path or file_path.startswith('/') or '..' in Path(file_path).parts: return self.send_json(400, {'error':'Некорректный путь файла'})
            try:
                f=github_request('/repos/'+active_github_repository()+'/contents/'+urllib.parse.quote(file_path,safe='/'))
                content=base64.b64decode(f.get('content','')).decode('utf-8',errors='replace')
                return self.send_json(200, {'path':file_path,'content':content,'sha':f.get('sha'),'size':f.get('size',0)})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        return super().do_GET()
    def _handle_run_tests(self):
        """Запускает unittest discover -s tests -v и возвращает JSON с результатом."""
        import re as _re
        import subprocess as _subprocess
        import sys as _sys
        from pathlib import Path as _Path

        project_root = _Path(__file__).resolve().parent
        try:
            result = _subprocess.run(
                [_sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=300,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            ran_match = _re.search(r"Ran (\d+) test", combined)
            total = int(ran_match.group(1)) if ran_match else 0
            failures = len(_re.findall(r"^FAIL:", combined, _re.MULTILINE))
            errors = len(_re.findall(r"^ERROR:", combined, _re.MULTILINE))
            payload = {
                "ok": result.returncode == 0,
                "total": total,
                "failures": failures,
                "errors": errors,
                "returncode": result.returncode,
                "output": combined[-20000:],
            }
        except _subprocess.TimeoutExpired:
            payload = {"ok": False, "error": "timeout", "total": 0, "failures": 0,
                       "errors": 1, "returncode": -1,
                       "output": "Тесты выполнялись дольше 5 минут и были прерваны."}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc), "total": 0, "failures": 0,
                       "errors": 1, "returncode": -1,
                       "output": f"Ошибка запуска тестов: {exc}"}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._check_host(): return
        path=urlparse(self.path).path
        if self._must_change_password_blocked(path): return
        if self.path == "/api/tests/run" or self.path.startswith("/api/tests/run?"):
            if not self.require_auth(): return
            return self._handle_run_tests()
        try: data=self.body()
        except Exception as e: return self.send_json(400, {'error':str(e)})
        if path == '/api/auth/login':
            config = read_json(AUTH_FILE, {})
            username = str(data.get('username', '')).strip()
            password = str(data.get('password', ''))
            try:
                salt = bytes.fromhex(config.get('salt', ''))
                supplied = _password_hash(password, salt)
            except Exception:
                supplied = ''
            if username != config.get('username') or not hmac.compare_digest(supplied, str(config.get('password_hash', ''))):
                return self.send_json(401, {'error':'Неверный логин или пароль'})
            token = secrets.token_urlsafe(32)
            with AUTH_SESSIONS_LOCK:
                AUTH_SESSIONS[token] = {'username':config['username'], 'expires':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=8)}
            log_event('auth.login', config['username'])
            return self.send_json(200, {'ok':True,'username':config['username'],'must_change_password':bool(config.get('must_change_password', False))}, self.auth_cookie(token, 28800))
        if path == '/api/auth/logout':
            session = self.auth_session()
            if session:
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get('Cookie', ''))
                    token = cookie.get('pq_session').value if cookie.get('pq_session') else ''
                    with AUTH_SESSIONS_LOCK: AUTH_SESSIONS.pop(token, None)
                except Exception: pass
            return self.send_json(200, {'ok':True}, self.auth_cookie('', 0))
        if path == '/api/auth/change-password':
            if not self.require_auth(): return
            new_password = str(data.get('new_password', ''))
            if len(new_password) < 12:
                return self.send_json(400, {'error':'Новый пароль должен содержать не менее 12 символов'})
            config = read_json(AUTH_FILE, {})
            salt = secrets.token_bytes(16)
            config.update({'salt':salt.hex(),'password_hash':_password_hash(new_password, salt),'iterations':AUTH_ITERATIONS,'must_change_password':False})
            write_json(AUTH_FILE, config)
            log_event('auth.password_change', config.get('username', 'root'))
            return self.send_json(200, {'ok':True,'must_change_password':False})
        if path.startswith('/api/') and not self.require_auth(): return
        if path == '/api/chat/conversations':
            title = str(data.get('title') or 'Новый диалог').strip()[:200]
            try:
                cid = CHAT_STORE.create_conversation(title)
                return self.send_json(201, {'conversation_id':cid,'meta':CHAT_STORE.get_meta(cid)})
            except Exception as exc: return self.send_json(500, {'error':'Не удалось создать диалог: '+str(exc)[:200]})
        if path == '/api/chat/import':
            cid = str(data.get('conversation_id') or '').strip()
            messages = data.get('messages')
            if not isinstance(messages,list) or len(messages)>200: return self.send_json(400, {'error':'Ожидается список до 200 сообщений'})
            if sum(len(str(x.get('content','')).encode('utf-8')) for x in messages if isinstance(x,dict)) > 2000000: return self.send_json(413, {'error':'Суммарный размер импортируемой истории превышает 2 МБ'})
            try:
                if CHAT_STORE.read_all(cid): return self.send_json(409, {'error':'В диалоге уже есть события; импорт запрещён'})
                for item in messages:
                    if not isinstance(item,dict) or item.get('role') not in ('user','assistant') or not isinstance(item.get('content'),str): continue
                    if item['role']=='user':
                        CHAT_STORE.append_event(cid,'user_message',{'text':_chat_redact(item['content'][:100000]),'legacy_import':True})
                    else:
                        CHAT_STORE.append_event(cid,'assistant_message',{'content':_chat_redact(item['content'][:100000]),'legacy_import':True,'tool_calls':[]},message_id='msg_'+uuid.uuid4().hex)
                return self.send_json(200, {'ok':True,'imported':len(messages)})
            except Exception as exc: return self.send_json(400, {'error':str(exc)[:240]})
        if path == '/api/chat/send':
            cid = str(data.get('conversation_id') or '').strip(); text_value = data.get('text')
            command_id = str(data.get('command_id') or '').strip()[:160]
            agent_id = str(data.get('agent_id') or '').strip()[:160]
            project_id = str(data.get('project_id') or '').strip()[:160]
            if not isinstance(text_value,str) or not text_value.strip() or len(text_value)>100000:
                return self.send_json(400, {'error':'Сообщение должно содержать от 1 до 100000 символов'})
            if not command_id or not agent_id: return self.send_json(400, {'error':'Обязательны command_id и agent_id'})
            if not cid: return self.send_json(400, {'error':'conversation_id обязателен; сначала создайте диалог'})
            try: CHAT_STORE.get_meta(cid)
            except Exception as exc: return self.send_json(400, {'error':'Диалог не найден: '+str(exc)[:180]})
            with _CHAT_ACTIVE_LOCK:
                command_key = (cid, command_id)
                known = _CHAT_COMMANDS.get(command_key)
                if known: return self.send_json(202, dict(known))
                if cid in _CHAT_ACTIVE: return self.send_json(409, {'error':'В этом диалоге уже выполняется задача'})
                cancel_event = threading.Event()
                _CHAT_ACTIVE[cid] = {'cancel_event':cancel_event,'command_id':command_id}
                task_id = 'task_' + uuid.uuid4().hex
                accepted = {'accepted':True,'conversation_id':cid,'command_id':command_id,'task_id':task_id,'status':'queued'}
                _CHAT_COMMANDS[command_key] = accepted
            try: runtime, _agent = _chat_runtime_for(cid,agent_id,project_id)
            except Exception as exc:
                with _CHAT_ACTIVE_LOCK: _CHAT_ACTIVE.pop(cid,None); _CHAT_COMMANDS.pop((cid,command_id),None)
                return self.send_json(400, {'error':str(exc)[:300]})
            def worker():
                try:
                    result = runtime.run_turn(cid,text_value.strip(),cancel_event,command_id,task_id=task_id)
                    with _CHAT_ACTIVE_LOCK: _CHAT_COMMANDS[(cid,command_id)] = {'accepted':True,'conversation_id':cid,'command_id':command_id,**result}
                    while len(_CHAT_COMMANDS) > 2000: _CHAT_COMMANDS.pop(next(iter(_CHAT_COMMANDS)))
                finally:
                    with _CHAT_ACTIVE_LOCK:
                        active = _CHAT_ACTIVE.get(cid)
                        if active and active.get('command_id') == command_id: _CHAT_ACTIVE.pop(cid,None)
            threading.Thread(target=worker,name='chat-'+cid[-8:],daemon=True).start()
            return self.send_json(202,accepted)
        if path == '/api/chat/approve':
            cid = str(data.get('conversation_id') or '').strip(); aid = str(data.get('approval_id') or '').strip()
            decision = str(data.get('decision') or '').strip(); command_id = str(data.get('command_id') or '').strip()[:160]
            if not command_id: return self.send_json(400, {'error':'command_id обязателен'})
            try:
                before = CHAT_STORE.get_approval(cid,aid)
                if before is None: return self.send_json(404, {'error':'Запрос подтверждения не найден'})
                approval = CHAT_STORE.resolve_approval(cid,aid,decision)
                if approval is None: return self.send_json(404, {'error':'Запрос подтверждения не найден'})
                if not before.get('resolved_at'):
                    outcome = {'approved':decision == 'approved','executed':False,
                               'message':'Подтверждение сохранено. Автоматическое возобновление и выполнение инструмента ещё не реализованы.'}
                    result_event = CHAT_STORE.append_event(cid,'tool_result',{'result':json.dumps(outcome,ensure_ascii=False)},task_id=approval.get('task_id'),tool_call_id=approval.get('tool_call_id'))
                    CHAT_HUB.publish(cid,result_event)
                    resolved_event = CHAT_STORE.append_event(cid,'approval_resolved',{'approval_id':aid,'decision':decision,'resolved_at':approval.get('resolved_at')},task_id=approval.get('task_id'),tool_call_id=approval.get('tool_call_id'))
                    CHAT_HUB.publish(cid,resolved_event)
                    completed = CHAT_STORE.append_event(cid,'turn_completed',{'status':'waiting_approval_resolved','resume_supported':False},task_id=approval.get('task_id'))
                    CHAT_HUB.publish(cid,completed)
                return self.send_json(200, {'ok':True,'approval':approval,'resume_supported':False})
            except Exception as exc: return self.send_json(400, {'error':str(exc)[:240]})
        if path == '/api/chat/cancel':
            cid = str(data.get('conversation_id') or '').strip(); command_id = str(data.get('command_id') or '').strip()[:160]
            with _CHAT_ACTIVE_LOCK: active = _CHAT_ACTIVE.get(cid)
            if not active: return self.send_json(200, {'ok':True,'cancelled':False})
            active['cancel_event'].set()
            return self.send_json(200, {'ok':True,'cancelled':True,'command_id':command_id})
        if path == '/api/ssh/save':
            connections = data.get('connections', [])
            if not isinstance(connections, list) or len(connections) > 200:
                return self.send_json(400, {'error':'Ожидался список не более чем из 200 SSH-подключений.'})
            saved = []
            seen_ids = set()
            for item in connections:
                if not isinstance(item, dict): continue
                connection_id = str(item.get('id', '')).strip()[:200]
                host = str(item.get('host', '')).strip()[:255]
                username = str(item.get('username', '')).strip()[:100]
                key_path = str(item.get('key_path', item.get('keyPath', ''))).strip()[:1000]
                try: port = int(item.get('port', 22))
                except (TypeError, ValueError): return self.send_json(400, {'error':'Некорректный порт SSH.'})
                if not connection_id or not host or not username or not 1 <= port <= 65535:
                    return self.send_json(400, {'error':'У каждого SSH-подключения должны быть id, host, username и порт 1–65535.'})
                if connection_id in seen_ids: return self.send_json(400, {'error':'ID SSH-подключений должны быть уникальными.'})
                seen_ids.add(connection_id)
                saved.append({'id':connection_id,'host':host,'port':port,'username':username,'key_path':key_path})
            write_json(DATA/'ssh_connections.json', saved)
            log_event('ssh.connections_saved', str(len(saved))+' подключений сохранено на сервере')
            return self.send_json(200, {'ok':True,'saved':len(saved),'message':'SSH-подключения сохранены на сервере без паролей.'})
        if path == '/api/models/folders':
            action = str(data.get('action') or 'add').strip().lower()
            raw_path = str(data.get('path') or '').strip()
            if not raw_path: return self.send_json(400, {'error':'Укажите путь к папке'})
            folders = read_json(DATA/'model_folders.json', [])
            folders = folders if isinstance(folders, list) else []
            if action == 'remove':
                target = str(Path(raw_path).expanduser())
                folders = [str(x) for x in folders if str(x).lower() != target.lower()]
                write_json(DATA/'model_folders.json', folders)
                log_event('model.folders.remove', target)
                return self.send_json(200, {'ok':True,'folders':folders})
            if action != 'add': return self.send_json(400, {'error':'action должен быть add или remove'})
            try: folder = Path(raw_path).expanduser().resolve(strict=True)
            except (OSError, RuntimeError, ValueError): return self.send_json(400, {'error':'Папка не существует или путь некорректен'})
            if not folder.is_dir(): return self.send_json(400, {'error':'Указанный путь не является папкой'})
            normalized = str(folder)
            if not any(str(x).lower() == normalized.lower() for x in folders): folders.append(normalized)
            write_json(DATA/'model_folders.json', folders)
            log_event('model.folders.add', normalized)
            return self.send_json(200, {'ok':True,'folders':folders})
        if path == '/api/models/download':
            repo_id = str(data.get('repo_id') or '').strip()[:200]
            filename = str(data.get('filename') or '').strip().replace('\\\\', '/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo_id): return self.send_json(400, {'error':'Некорректный repo_id Hugging Face'})
            if not filename or not filename.lower().endswith('.gguf') or filename.startswith('/') or '..' in Path(filename).parts: return self.send_json(400, {'error':'Выберите корректный файл .gguf'})
            if hf_hub_download is None: return self.send_json(503, {'error':'Библиотека huggingface_hub не установлена'})
            try:
                model_dir = DATA / 'models'; model_dir.mkdir(parents=True, exist_ok=True)
                downloaded = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(model_dir))
                model_path = str(Path(downloaded).resolve())
                if not Path(model_path).is_file() or Path(model_path).suffix.lower() != '.gguf': raise ValueError('Загруженный файл не найден')
                providers = read_json(PROVIDER_FILE, [])
                providers = providers if isinstance(providers, list) else []
                existing = next((p for p in providers if isinstance(p, dict) and p.get('kind') == 'file' and str(p.get('base_url','')).lower() == model_path.lower()), None)
                if not existing:
                    model_name = Path(model_path).stem[:80] or repo_id.split('/')[-1]
                    raw_layers = data.get('n_gpu_layers', -1)
                    try: gpu_layers = max(-1, min(200, int(raw_layers)))
                    except (TypeError, ValueError): gpu_layers = -1
                    provider = {'id':'gguf-' + uuid.uuid4().hex[:12], 'name':model_name, 'kind':'file', 'format':'gguf', 'base_url':model_path, 'n_ctx':4096, 'n_gpu_layers':gpu_layers, 'temperature':0.7, 'top_p':0.9, 'repeat_penalty':1.1, 'builtin':False, 'created_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                    providers.append(provider); write_json(PROVIDER_FILE, providers)
                log_event('model.gguf.download', repo_id + '/' + filename)
                return self.send_json(200, {'ok':True,'repo_id':repo_id,'filename':filename,'path':model_path,'provider_created':not bool(existing)})
            except Exception as exc: return self.send_json(502, {'error':'Не удалось скачать GGUF с Hugging Face: '+str(exc)[:220]})
        if path == '/api/terminal':
            command=data.get('command')
            if not isinstance(command,str) or not command.strip() or len(command)>4000:
                return self.send_json(400, {'error':'Введите команду длиной от 1 до 4000 символов.'})
            permissions=permission_settings()
            roots=permissions.get('roots') if isinstance(permissions.get('roots'),list) else []
            if not permissions.get('local_files') or not roots:
                return self.send_json(403, {'error':'Для терминала включите локальный доступ к файлам и добавьте разрешённую папку.'})
            try:
                from agent_tools import is_blocked_shell_command, resolve_authorized_path
                if is_blocked_shell_command(command):
                    return self.send_json(400, {'error':'Команда заблокирована базовой защитой от опасных операций.'})
                cwd_raw=str(data.get('cwd') or roots[0]).strip()
                cwd=resolve_authorized_path(cwd_raw,permissions,must_exist=True)
                if not cwd.is_dir():
                    return self.send_json(400, {'error':'Рабочий путь должен указывать на существующую папку.'})
                try:
                    completed=subprocess.run(command,shell=True,cwd=str(cwd),capture_output=True,text=True,timeout=30,encoding='utf-8',errors='replace')
                    result={'cwd':str(cwd),'stdout':completed.stdout[-60000:],'stderr':completed.stderr[-30000:],'exit_code':completed.returncode}
                except subprocess.TimeoutExpired as exc:
                    stdout=exc.stdout.decode('utf-8','replace') if isinstance(exc.stdout,bytes) else str(exc.stdout or '')
                    stderr=exc.stderr.decode('utf-8','replace') if isinstance(exc.stderr,bytes) else str(exc.stderr or '')
                    result={'cwd':str(cwd),'stdout':stdout[-60000:],'stderr':(stderr+'\nКоманда остановлена по тайм-ауту 30 секунд.')[-30000:],'exit_code':124}
                log_event('terminal.command',str(cwd)+' · '+command[:120])
                return self.send_json(200,result)
            except (PermissionError,ValueError,OSError,RuntimeError) as exc:
                status=403 if isinstance(exc,PermissionError) else 400
                return self.send_json(status, {'error':'Команда не выполнена: '+str(exc)[:220]})
        if path=='/api/github/connections':
            name=str(data.get('name','')).strip()[:100]
            repository=str(data.get('repository','')).strip()
            token=str(data.get('token','')).strip()
            connection_id=str(data.get('id','')).strip()
            if not name: return self.send_json(400, {'error':'Введите название подключения'})
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository): return self.send_json(400, {'error':'Укажите репозиторий в формате owner/repository'})
            saved=github_connections()
            existing=next((x for x in saved['connections'] if x.get('id')==connection_id),None) if connection_id else None
            if not existing and not token: return self.send_json(400, {'error':'Введите GitHub API-токен'})
            if token and not token.startswith(('ghp_','github_pat_','gho_','ghu_','ghs_','ghr_')): return self.send_json(400, {'error':'Проверьте формат GitHub-токена'})
            if token:
                try:
                    encrypted=_dpapi_crypt(token)
                except Exception as e:
                    log_event('github.connection.encrypt_failed', type(e).__name__)
                    return self.send_json(400, {'error':'Ошибка шифрования: '+str(e)[:180]})
            else: encrypted=existing.get('token_encrypted','')
            item={'id':connection_id or 'gh-'+uuid.uuid4().hex[:12],'name':name,'repository':repository,'token_encrypted':encrypted,'updated_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
            if existing: saved['connections']=[item if x.get('id')==connection_id else x for x in saved['connections']]
            else: saved['connections'].insert(0,item)
            saved['active_id']=item['id']; write_json(GITHUB_CONNECTIONS_FILE,saved)
            log_event('github.connection.save',repository)
            return self.send_json(200, {'ok':True,'id':item['id'],'message':'Подключение сохранено; токен зашифрован Windows DPAPI'})
        if path == '/api/github/connections/active':
            connection_id=str(data.get('id','')).strip(); saved=github_connections()
            if not any(x.get('id')==connection_id for x in saved['connections']): return self.send_json(404, {'error':'Подключение не найдено'})
            saved['active_id']=connection_id; write_json(GITHUB_CONNECTIONS_FILE,saved)
            return self.send_json(200, {'ok':True})
        if path == '/api/agent-roles':
            try:
                items = ensure_agent_roles()
                role_id = str(data.get('id', '')).strip()
                existing = next((x for x in items if x.get('id') == role_id), None) if role_id else None
                name = data.get('name', existing.get('name', '') if existing else '')
                activity = data.get('activity', existing.get('activity', '') if existing else '')
                system_prompt = data.get('system_prompt', existing.get('system_prompt', '') if existing else '')
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
                    return self.send_json(400, {'error': 'Название роли должно содержать от 1 до 120 символов'})
                if not isinstance(activity, str) or len(activity) > 2000:
                    return self.send_json(400, {'error': 'Описание роли должно быть строкой до 2000 символов'})
                if not isinstance(system_prompt, str) or not 1 <= len(system_prompt.strip()) <= 8000:
                    return self.send_json(400, {'error': 'Системная инструкция должна содержать от 1 до 8000 символов'})
                now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                if existing:
                    existing.update({'name': name.strip(), 'activity': activity.strip(), 'system_prompt': system_prompt.strip(), 'updated_at': now})
                    item = existing
                else:
                    code = 'CUSTOM_' + uuid.uuid4().hex[:10].upper()
                    item = {'id': code, 'code': code, 'name': name.strip(), 'activity': activity.strip(), 'system_prompt': system_prompt.strip(), 'is_system': False, 'created_at': now, 'updated_at': now}
                    items.append(item)
                save_agent_roles(items)
                if item.get('is_system'):
                    instructions = ensure_system_instructions()
                    instruction = next((x for x in instructions if isinstance(x, dict) and x.get('role') == item.get('code') and x.get('is_default')), None)
                    if instruction:
                        instruction.update({'name': item['name'] + ' (по умолчанию)', 'activity': item['activity'], 'system_prompt': item['system_prompt'], 'updated_at': now})
                        save_system_instructions(instructions)
                log_event('agent_role.save', item['name'])
                return self.send_json(200 if existing else 201, item)
            except Exception as exc:
                return self.send_json(500, {'error': str(exc)[:240]})
        if path == '/api/system-instructions':
            try:
                name = data.get('name'); role = str(data.get('role', '')).upper().strip()
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120: return self.send_json(400, {'error': 'Название должно содержать от 1 до 120 символов'})
                if role not in AGENT_ROLES: return self.send_json(400, {'error': 'Неизвестная роль агента'})
                system_prompt = data.get('system_prompt', ''); activity = data.get('activity', '')
                if not isinstance(system_prompt, str) or len(system_prompt) > 8000: return self.send_json(400, {'error': 'Системная инструкция должна быть строкой до 8000 символов'})
                if not isinstance(activity, str) or len(activity) > 2000: return self.send_json(400, {'error': 'Основная деятельность должна быть строкой до 2000 символов'})
                plan = validate_manager_interaction_plan(data.get('interaction_plan', [])) if role == 'MANAGER' else system_instruction_agent_plan(); items = ensure_system_instructions()
                is_default = not any(x.get('role') == role and x.get('is_default') for x in items)
                now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                item = {'id': 'instr-' + uuid.uuid4().hex[:12], 'name': name.strip(), 'role': role, 'system_prompt': system_prompt, 'activity': activity, 'is_default': is_default, 'interaction_plan': plan, 'created_at': now, 'updated_at': now}
                items.append(item); save_system_instructions(items)
                if item.get('is_default'): sync_builtin_agent_role(role, item['name'], item['activity'], item['system_prompt'], now)
                log_event('system_instruction.create', item['name'])
                return self.send_json(201, item)
            except ValueError as exc: return self.send_json(400, {'error': str(exc)})
            except Exception as exc: return self.send_json(500, {'error': str(exc)[:240]})
        if path.startswith('/api/projects/') and path.endswith('/memory'):
            pid = urllib.parse.unquote(path.split('/')[-2])
            mem = read_project_memory(pid)
            for key in ('summary', 'constraints', 'open_questions', 'next_steps', 'chats'):
                if key not in data: continue
                if key == 'summary': mem[key] = str(data[key])[:400]
                elif key == 'chats' and isinstance(data[key], list):
                    safe_chats=[]
                    for chat in data[key][-100:]:
                        if not isinstance(chat,dict) or not str(chat.get('id','')).strip(): continue
                        messages=[]
                        source_messages=chat.get('messages',[])
                        for message in (source_messages[-80:] if isinstance(source_messages,list) else []):
                            if isinstance(message,dict) and message.get('role') in ('user','assistant'):
                                messages.append({'role':message['role'],'content':str(message.get('content',''))[:12000],'time':str(message.get('time',''))[:40]})
                        safe_chats.append({'id':str(chat.get('id',''))[:120],'title':str(chat.get('title','Новый чат'))[:120],'updated_at':str(chat.get('updated_at',''))[:40],'agent_id':str(chat.get('agent_id',''))[:160],'messages':messages})
                    mem['chats']=safe_chats
                elif isinstance(data[key], list): mem[key] = [str(value)[:300] for value in data[key][:20]]
            write_project_memory(pid, mem)
            log_event('project.memory.update', pid)
            return self.send_json(200, mem)
        if path.startswith('/api/system-instructions/') and path.endswith('/revert'):
            instruction_id = urllib.parse.unquote(path[len('/api/system-instructions/'):].rsplit('/', 1)[0])
            at = str(data.get('at', '')).strip()
            history = read_json(_system_instruction_history_path(), [])
            if not isinstance(history, list): history = []
            version = next((entry for entry in history if isinstance(entry, dict) and entry.get('id') == instruction_id and entry.get('at') == at), None)
            if not version: return self.send_json(404, {'error': 'Версия инструкции не найдена'})
            items = ensure_system_instructions()
            index = next((i for i, entry in enumerate(items) if entry.get('id') == instruction_id), None)
            if index is None: return self.send_json(404, {'error': 'Инструкция не найдена'})
            _append_system_instruction_history(items[index])
            items[index] = {**items[index], 'system_prompt': str(version.get('system_prompt', ''))[:8000], 'updated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
            save_system_instructions(items)
            log_event('system_instruction.revert', instruction_id)
            return self.send_json(200, items[index])
        if path.startswith('/api/system-instructions/'):
            instruction_id = urllib.parse.unquote(path[len('/api/system-instructions/'):])
            if not instruction_id or '/' in instruction_id: return self.send_json(404, {'error': 'Инструкция не найдена'})
            try:
                items = ensure_system_instructions()
                index = next((i for i, x in enumerate(items) if x.get('id') == instruction_id), None)
                if index is None: return self.send_json(404, {'error': 'Инструкция не найдена'})
                existing = items[index]
                role = str(data.get('role', existing.get('role', ''))).upper().strip()
                name = data.get('name', existing.get('name', '')); system_prompt = data.get('system_prompt', existing.get('system_prompt', '')); activity = data.get('activity', existing.get('activity', ''))
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120: return self.send_json(400, {'error': 'Название должно содержать от 1 до 120 символов'})
                if role not in AGENT_ROLES: return self.send_json(400, {'error': 'Неизвестная роль агента'})
                if not isinstance(system_prompt, str) or len(system_prompt) > 8000: return self.send_json(400, {'error': 'Системная инструкция должна быть строкой до 8000 символов'})
                if not isinstance(activity, str) or len(activity) > 2000: return self.send_json(400, {'error': 'Основная деятельность должна быть строкой до 2000 символов'})
                plan = (validate_manager_interaction_plan(data.get('interaction_plan', existing.get('interaction_plan', []))) if role == 'MANAGER' else system_instruction_agent_plan())
                updated = {**existing, 'name': name.strip(), 'role': role, 'system_prompt': system_prompt, 'activity': activity, 'interaction_plan': plan, 'updated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                if existing.get('system_prompt') != system_prompt:
                    _append_system_instruction_history(existing)
                    _append_system_instruction_history(updated)
                items[index] = updated; save_system_instructions(items)
                if existing.get('is_default'): sync_builtin_agent_role(role, updated['name'], updated['activity'], updated['system_prompt'], updated['updated_at'])
                log_event('system_instruction.update', updated['name'])
                return self.send_json(200, updated)
            except ValueError as exc: return self.send_json(400, {'error': str(exc)})
            except Exception as exc: return self.send_json(500, {'error': str(exc)[:240]})
        if path == '/api/chat':
            agent_id = str(data.get('agent_id', '')).strip()[:160]
            chat_id = str(data.get('conversation_id', '')).strip()[:160] or ('chat-' + uuid.uuid4().hex)
            activity_started = time.monotonic()
            requested_model = str(data.get('model', '')).strip()[:160]
            messages = data.get('messages')
            agent = None
            if agent_id:
                agent = next((x for x in domain_items('agents') if isinstance(x, dict) and x.get('id') == agent_id), None)
                if not agent: return self.send_json(404, {'error':'Выбранный агент не найден'})
                requested_model = str(agent.get('model', '')).strip()[:160] or requested_model
            if not isinstance(messages, list) or not messages:
                return self.send_json(400, {'error': 'Передайте историю сообщений'})
            validated_messages = []
            for message in messages:
                if not isinstance(message, dict):
                    return self.send_json(400, {'error': 'Некорректный формат сообщения'})
                role = str(message.get('role', '')).strip()
                content = message.get('content')
                if role not in ('system', 'user', 'assistant') or not isinstance(content, str):
                    return self.send_json(400, {'error': 'У сообщения некорректная роль или содержимое'})
                validated_messages.append({'role': role, 'content': content})
            project_id = str(data.get('project_id', '')).strip()[:160]
            activity_context = _agent_activity_context(chat_id, agent_id)
            _record_agent_activity(chat_id, agent_id, 'reading_context', 'Читает историю диалога и контекст проекта.')
            if activity_context:
                validated_messages.insert(0, {'role': 'system', 'content': activity_context})
            if project_id:
                project_memory = read_project_memory(project_id); chat_entries = project_memory.get('chats') if isinstance(project_memory.get('chats'),list) else []; recent_chat_context=[]
                for chat_entry in chat_entries[-8:]:
                    if not isinstance(chat_entry,dict): continue
                    transcript=[]
                    for entry in (chat_entry.get('messages') or [])[-12:]:
                        if isinstance(entry,dict) and entry.get('role') in ('user','assistant'): transcript.append(str(entry.get('role'))+': '+str(entry.get('content',''))[:1800])
                    if transcript: recent_chat_context.append('Чат «'+str(chat_entry.get('title',''))[:120]+'»:\n'+'\n'.join(transcript))
                if recent_chat_context: validated_messages.insert(0,{'role':'system','content':'Контекст предыдущих чатов этого проекта (используй для продолжения разработки, если относится к запросу):\n\n'+'\n\n'.join(recent_chat_context)[-14000:]})
            project = next((x for x in domain_items('projects') if isinstance(x, dict) and x.get('id') == project_id), None) if project_id else None
            if agent:
                system_prompt = str(agent.get('system_prompt', '').strip())
                role_prompt = {
                    'MANAGER':'Ты Агент №1 — координатор проекта. Помогай пользователю управлять проектом, уточняй цели и предлагай проверяемые следующие шаги.',
                    'ARCHITECT':'Ты системный архитектор. Учитывай структуру, зависимости, масштабируемость и безопасность.',
                    'ANALYST':'Ты аналитик. Разделяй факты и предположения, проверяй данные и объясняй выводы.',
                    'DESIGNER':'Ты дизайнер интерфейсов. Учитывай доступность, адаптивность, иерархию и единообразие.',
                    'COPYWRITER':'Ты редактор и технический автор. Пиши ясно, конкретно и без выдуманных фактов.',
                    'CODER':'Ты инженер-программист. Предлагай проверяемые решения и учитывай безопасность, тесты и сопровождение.',
                    'TESTER':'Ты инженер по тестированию. Ищи регрессии и воспроизводимые критерии приёмки.',
                    'DEVOPS':'Ты инженер инфраструктуры. Учитывай конфигурацию, логи, мониторинг и откат.'
                }.get(str(agent.get('role','')).upper(), '')
                instruction = resolve_agent_system_prompt(agent) or system_prompt or role_prompt
                if instruction:
                    validated_messages.insert(0, {'role':'system','content':instruction})
                if project:
                    project_dir = str(project.get('path', '')).strip() or 'не указана'
                    project_context = (
                        '=== ИНФОРМАЦИЯ О ПРОЕКТЕ ===\n'
                        + 'Название: ' + str(project.get('name', '')) + '\n'
                        + 'Рабочая папка проекта: ' + project_dir + '\n'
                        + 'Описание: ' + str(project.get('description', '')) + '\n'
                        + 'ВАЖНО: если работаешь с файлами, используй только рабочую папку проекта и доступные разрешённые инструменты. '
                        + 'Не утверждай, что файл прочитан или изменён, пока инструмент не вернул результат.'
                    )
                    validated_messages.insert(0, {'role':'system','content':project_context})
            model = requested_model
            provider_id = str((agent or {}).get('provider_id') or data.get('provider_id') or '').strip()[:120]
            provider = provider_for_model(model, provider_id)
            if not model and provider.get('format') == 'ollama':
                try:
                    available = ollama_request('/api/tags', timeout=4).get('models', [])
                    model = next((str(x.get('name','')).strip() for x in available if isinstance(x,dict) and x.get('name')), '')
                except Exception:
                    model = ''
            if not model:
                _record_agent_activity(chat_id, agent_id, 'error', 'У агента не назначена модель.', duration_ms=(time.monotonic() - activity_started) * 1000)
                return self.send_json(400, {'error': 'У выбранного агента не назначена модель. Откройте настройки агента и назначьте модель.'})
            try:
                tool_summaries=[]
                if agent and provider.get('format') == 'ollama':
                    from agent_tools import effective_tools, execute_tool
                    permission_config=permission_settings()
                    available_tools=effective_tools(agent,permission_config)
                    if available_tools:
                        tool_names=[x['function']['name'] for x in available_tools]
                        project_context=''
                        if project:
                            project_dir=str(project.get('path','')).strip() or 'не указана (уточните у пользователя)'
                            project_context='\n\nКонтекст текущего проекта: '+str(project.get('name',''))+'; описание: '+str(project.get('description',''))+'; локальная папка: '+project_dir+'. Используй только доступные инструменты и не утверждай, что файл прочитан или изменён без результата инструмента.'
                        tool_context='\n\nДоступные инструменты: '+', '.join(tool_names)+'. Если инструмента нет в списке, использовать его нельзя.'+project_context+agent_ssh_context(agent)
                        validated_messages.insert(0,{'role':'system','content':tool_context})
                        ollama_model=resolve_ollama_model(model)
                        total_calls=0
                        last_payload={}
                        for _ in range(12):
                            _record_agent_activity(chat_id, agent_id, 'thinking', 'Агент анализирует запрос и выбирает следующий шаг.')
                            last_payload=ollama_request('/api/chat',{'model':ollama_model,'messages':validated_messages,'tools':available_tools,'stream':False,'think':False,'keep_alive':'5m','options':{'num_predict':1024}},timeout=180)
                            assistant_turn=last_payload.get('message') if isinstance(last_payload,dict) else None
                            if not isinstance(assistant_turn,dict): break
                            calls=assistant_turn.get('tool_calls')
                            if not isinstance(calls,list) or not calls:
                                response_text=assistant_turn.get('content','') if isinstance(assistant_turn.get('content',''),str) else ''
                                _record_agent_activity(chat_id, agent_id, 'writing', 'Формирует итоговый ответ.')
                                _record_agent_activity(chat_id, agent_id, 'done', 'Ответ подготовлен.', duration_ms=(time.monotonic() - activity_started) * 1000)
                                log_event('chat.message',str(provider.get('name',provider.get('id','provider')))+'/'+model)
                                return self.send_json(200,{'response':response_text,'tool_calls':tool_summaries})
                            validated_messages.append(assistant_turn)
                            for call in calls:
                                function_for_activity=call.get('function',{}) if isinstance(call,dict) else {}
                                activity_tool_name=function_for_activity.get('name','') if isinstance(function_for_activity,dict) else ''
                                _record_agent_activity(chat_id, agent_id, 'calling_tool', 'Агент вызывает инструмент.', tool=str(activity_tool_name))
                                total_calls+=1
                                if total_calls>24: break
                                function=call.get('function',{}) if isinstance(call,dict) else {}
                                name=function.get('name') if isinstance(function,dict) else None
                                args=function.get('arguments',{}) if isinstance(function,dict) else {}
                                if isinstance(args,str):
                                    try: args=json.loads(args)
                                    except ValueError: args={}
                                if not isinstance(args,dict) or not isinstance(name,str) or name not in tool_names:
                                    result={'error':'Некорректный или недоступный инструмент.'}; name=str(name or 'unknown')
                                else:
                                    if name=='run_command' and project and project.get('path'): args['cwd']=str(project.get('path'))
                                    if name=='ssh_execute' and project and str(project.get('env_type','local'))=='ssh':
                                        args['working_dir']=str(project.get('path','') or '/')
                                        if project.get('ssh_connection_id'): args['connection_id']=str(project.get('ssh_connection_id'))
                                    result=execute_tool(name,args,agent,permission_config)
                                status='error' if isinstance(result,dict) and result.get('error') else 'ok'
                                tool_summaries.append({'name':name,'status':status})
                                log_event('agent.tool_called',str(agent.get('id',''))+' · '+str(name)+' · '+status)
                                validated_messages.append({'role':'tool','tool_name':str(name),'content':json.dumps(result,ensure_ascii=False)[:12000]})
                            if total_calls>24: break
                        last_message=last_payload.get('message',{}) if isinstance(last_payload,dict) else {}
                        response_text=last_message.get('content','') if isinstance(last_message,dict) and isinstance(last_message.get('content',''),str) else ''
                        _record_agent_activity(chat_id, agent_id, 'done', 'Ответ подготовлен после вызовов инструментов.', duration_ms=(time.monotonic() - activity_started) * 1000)
                        return self.send_json(200,{'response':response_text,'tool_calls':tool_summaries,'warning':'Достигнут лимит циклов вызова инструментов.'})
                result = send_chat_request(provider, model, validated_messages, timeout=120)
                log_event('chat.message', str(provider.get('name',provider.get('id','provider')))+'/'+model)
                _record_agent_activity(chat_id, agent_id, 'done', 'Ответ подготовлен.', duration_ms=(time.monotonic() - activity_started) * 1000)
                return self.send_json(200, {'response': result['response'],'tool_calls':tool_summaries})
            except ValueError as exc:
                message=str(exc)
                status=502 if ('Ошибка облачного провайдера' in message or 'Ошибка провайдера' in message or 'Провайдер недоступен' in message or 'Ошибка Ollama' in message) else 400
                return self.send_json(status, {'error':message})
            except TimeoutError:
                return self.send_json(504, {'error':'Провайдер не ответил за 120 секунд. Попробуйте ещё раз.'})
            except Exception as exc:
                return self.send_json(502, {'error':'Не удалось получить ответ модели: '+str(exc)[:180]})
        if path=='/api/providers':
            pid=str(data.get('id','')).strip(); name=str(data.get('name','')).strip()[:80]; kind=str(data.get('kind','local')).strip(); base=str(data.get('base_url','')).strip(); fmt=str(data.get('format','openai')).strip()
            if not name or not base or kind not in ('local','cloud','file'): return self.send_json(400, {'error':'Укажите имя, тип и адрес провайдера'})
            if kind == 'file':
                model_path=Path(base).expanduser()
                if fmt != 'gguf' or model_path.suffix.lower() != '.gguf': return self.send_json(400, {'error':'Файловый провайдер должен указывать на файл .gguf'})
                if not model_path.is_file(): return self.send_json(400, {'error':'Файл .gguf не найден: проверьте путь'})
                base=str(model_path.resolve())
            else:
                base=base.rstrip('/')
                if not re.match(r'^https?://',base): return self.send_json(400, {'error':'Адрес должен начинаться с http:// или https://'})
                if fmt not in ('ollama','openai','anthropic','gemini'): return self.send_json(400, {'error':'Неподдерживаемый формат доступа'})
            items=read_json(PROVIDER_FILE,[]); items=items if isinstance(items,list) else []; existing=next((x for x in items if x.get('id')==pid),None) if pid else None
            if not pid: pid=re.sub(r'[^a-z0-9-]+','-',name.lower()).strip('-')[:48]+'-'+uuid.uuid4().hex[:6]
            builtin=pid in {'ollama','lm-studio','openai','anthropic','google-gemini','openrouter','groq'}
            old=existing or next((x for x in provider_items() if x.get('id')==pid),{})
            if existing is None and builtin and pid not in {x.get('id') for x in provider_items()}: return self.send_json(400, {'error':'Неизвестный встроенный провайдер'})
            item={'id':pid,'name':name,'kind':kind,'base_url':base,'format':fmt,'builtin':builtin,'created_at':(old or {}).get('created_at') or (datetime.datetime.now().astimezone().isoformat(timespec='seconds') if not existing and not builtin else '')}
            if kind == 'file':
                for setting, default, cast, low, high in (('n_ctx',4096,int,512,131072),('n_gpu_layers',-1,int,-1,200),('temperature',0.7,float,0.0,2.0),('top_p',0.9,float,0.0,1.0),('repeat_penalty',1.1,float,0.5,2.0)):
                    try:
                        item[setting] = max(low, min(high, cast(data.get(setting, old.get(setting, default)))))
                    except (TypeError, ValueError):
                        item[setting] = default
            key=str(data.get('api_key','')).strip()
            if key: item['api_key']=key
            elif old.get('api_key'): item['api_key']=old['api_key']
            if existing: items=[item if x.get('id')==pid else x for x in items]
            else: items.append(item)
            write_json(PROVIDER_FILE,items); log_event('provider.save',name)
            return self.send_json(200, {'ok':True,'provider':public_provider(item)})
        if path=='/api/providers/assign':
            aid=str(data.get('agent_id','')); pid=str(data.get('provider_id','')); model=str(data.get('model','')).strip()[:200]
            agents=domain_items('agents'); agent=next((x for x in agents if x.get('id')==aid),None); prov=next((x for x in provider_items() if x.get('id')==pid),None)
            if not agent or not prov or not model: return self.send_json(400, {'error':'Не удалось определить агента, провайдера или модель'})
            agent['model']=model; agent['provider_id']=pid; save_domain('agents',agents); log_event('model.assign',agent.get('name','')+' ← '+prov.get('name','')+'/'+model)
            return self.send_json(200, {'ok':True})
        if path=='/api/models/test':
            model=str(data.get('model','')).strip()[:160]
            prompt=str(data.get('prompt','Ответь одним коротким предложением на приветствие.')).strip()[:4000]
            provider_id=str(data.get('provider_id','')).strip()[:120]
            if not model: return self.send_json(400, {'error':'Выберите модель'})
            provider=provider_for_model(model,provider_id)
            try:
                result=send_chat_request(provider,model,[{'role':'user','content':prompt}],timeout=60,max_tokens=80)
                log_event('model.test',str(provider.get('name',provider.get('id','provider')))+'/'+model)
                return self.send_json(200, {'ok':True,'model':result.get('model',model),'response':result['response'],'done':bool(result.get('done',True))})
            except ValueError as exc:
                message=str(exc)
                status=502 if ('Ошибка облачного провайдера' in message or 'Ошибка провайдера' in message or 'Провайдер недоступен' in message or 'Ошибка Ollama' in message) else 400
                return self.send_json(status, {'error':message})
            except Exception as exc:
                return self.send_json(502, {'error':'Модель не ответила: '+str(exc)[:220]})
        if path in ('/api/agents','/api/projects','/api/tasks'):
            kind=path.split('/')[-1]; items=domain_items(kind); field='title' if kind=='tasks' else 'name'
            name=str(data.get(field,'')).strip()[:160]
            if not name: return self.send_json(400, {'error':'Укажите название'})
            item={'id':uuid.uuid4().hex[:12],field:name,'created_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
            if kind=='agents':
                role=str(data.get('role','ANALYST')).upper().strip()
                role_item = next((x for x in ensure_agent_roles() if str(x.get('code','')).upper() == role), None)
                if role not in AGENT_ROLES and not role_item: return self.send_json(400, {'error':'Неизвестная роль агента'})
                item.update({'role':role,'model':str(data.get('model','')).strip()[:160],'description':str(data.get('description','')).strip()[:1000],'system_prompt':str(data.get('system_prompt') or '').strip()[:4000],'memory':str(data.get('memory','')).strip()[:8000],'permissions':{**DEFAULT_AGENT_PERMISSIONS,**{k:bool(v) for k,v in data.get('permissions',{}).items() if k in AGENT_PERMISSION_KEYS}} if isinstance(data.get('permissions',{}),dict) else DEFAULT_AGENT_PERMISSIONS.copy(),'status':'idle','system':False})
            elif kind=='projects':
                env_type = str(data.get('env_type','local') or 'local').strip().lower()
                if env_type not in ('local','github','ssh'): return self.send_json(400, {'error':'env_type должен быть local, github или ssh'})
                project_path = str(data.get('path','')).strip()[:1000]
                if env_type == 'local':
                    if not project_path: return self.send_json(400, {'error':'Для локального проекта обязательно укажите рабочую папку.'})
                    try: project_path = grant_project_folder_to_agents(project_path)
                    except (OSError, RuntimeError, ValueError) as exc: return self.send_json(400, {'error':str(exc) or 'Рабочая папка не найдена.'})
                try:
                    logo = save_project_logo(item['id'], data.get('logo', ''))
                except ValueError as exc:
                    return self.send_json(400, {'error': str(exc)})
                item.update({'path':project_path,'description':str(data.get('description','')).strip()[:1000],'logo':logo,'env_type':env_type,'ssh_connection_id':str(data.get('ssh_connection_id','')).strip()[:200],'github_connection_id':str(data.get('github_connection_id','')).strip()[:200],'repo_name':str(data.get('repo_name','')).strip()[:300],'status':'active'})
            else:
                raw_roles = data.get('active_roles')
                if isinstance(raw_roles, list):
                    active = [str(role).upper() for role in raw_roles if str(role).upper() in AGENT_ROLES]
                else:
                    active = list(AGENT_ROLES)
                if 'MANAGER' not in active:
                    active.insert(0, 'MANAGER')
                item.update({'description':str(data.get('description','')).strip()[:5000],'model':str(data.get('model','')).strip()[:160],'agent_id':str(data.get('agent_id','')).strip()[:80],'project_id':str(data.get('project_id','')).strip()[:80],'team_mode':bool(data.get('team_mode',False)),'active_roles':active,'status':'pending','result':'','error':'','team_result':[]})
                item['risk_history'] = search_risks(extract_task_keywords(name + ' ' + item['description']))
                item['risk_weight'] = max((int(r.get('weight', 0) or 0) for r in item['risk_history'] if int(r.get('weight', 0) or 0) > 5), default=0)
            items.insert(0,item); save_domain(kind,items); log_event(kind[:-1]+'.create',name)
            return self.send_json(201,item)
        if path.startswith('/api/tasks/') and (path.endswith('/run') or path.endswith('/run-team')):
            task_id=path.split('/')[-2]; items=domain_items('tasks'); item=next((x for x in items if x.get('id')==task_id),None)
            if not item: return self.send_json(404, {'error':'Задача не найдена'})
            agents=domain_items('agents')
            agent=next((x for x in agents if x.get('id')==item.get('agent_id')),None)
            model=item.get('model') or (agent or {}).get('model') or str(data.get('model','')).strip()
            if not model: return self.send_json(400, {'error':'Укажите модель для запуска задачи или назначьте модель агенту'})
            project=next((x for x in domain_items('projects') if x.get('id')==item.get('project_id')),None)
            item['risk_history'] = search_risks(extract_task_keywords(str(item.get('title', '')) + ' ' + str(item.get('description', ''))))
            item['risk_weight'] = max((int(r.get('weight', 0) or 0) for r in item['risk_history'] if int(r.get('weight', 0) or 0) > 5), default=0)
            item['status']='running'; item['model']=model; item['started_at']=datetime.datetime.now().astimezone().isoformat(timespec='seconds'); save_domain('tasks',items)
            role=(agent or {}).get('role','ANALYST')
            system_prompt=(agent or {}).get('system_prompt') or AGENT_ROLE_PROMPTS.get(role,AGENT_ROLE_PROMPTS['ANALYST'])
            if agent:
                system_prompt += '\n\nПрофиль агента: '+str(agent.get('name',''))+'\nНазначение: '+str(agent.get('description',''))[:1000]
                memory=str(agent.get('memory','')).strip()
                if memory: system_prompt += '\n\nДолговременная память агента (пользовательские заметки):\n'+memory[:8000]
            prompt='Выполни задачу. Отвечай на русском языке. Разделяй подтверждённые факты и предположения. Если не хватает данных, явно укажи ограничения.\n\nНазвание задачи: '+item.get('title','')+'\n\nОписание и инструкции:\n'+item.get('description','')
            if project:
                prompt += '\n\nКонтекст проекта:\nНазвание: '+str(project.get('name',''))+'\nОписание: '+str(project.get('description',''))+'\nРабочий путь (справочная информация, не открывай файлы автоматически): '+str(project.get('path',''))
            try:
                team_mode=path.endswith('/run-team') or bool(item.get('team_mode')) or bool(str(item.get('project_id','')).strip())
                result=run_agent_team(model,item,agent,project) if team_mode else run_agent_task(model,item,agent,project)
                item['status']='completed'; item['result']=result.get('response',''); item['tool_calls']=result.get('tool_calls',0); item['warning']=result.get('warning',''); item['team_result']=result.get('team_result',[]); item['error']=''; item['finished_at']=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                if agent:
                    agent['last_task_id']=task_id; agent['last_task_at']=item['finished_at']; save_domain('agents',agents)
                _record_task_outcome(item, 'completed')
                log_event('task.completed',item.get('title','')); save_domain('tasks',items)
                try: update_project_memory_after_task(item, item.get('team_result') or [], agent)
                except Exception: pass
                return self.send_json(200,item)
            except Exception as e:
                item['status']='failed'; item['error']=str(e)[:300]; item['finished_at']=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                _record_task_outcome(item, 'failed')
                save_domain('tasks',items); log_event('task.failed',item.get('title',''))
                try: update_project_memory_after_task(item, item.get('team_result') or [], agent)
                except Exception: pass
                return self.send_json(502, {'error':'Не удалось выполнить задачу через Ollama: '+str(e)[:180],'task':item})
        if path.startswith('/api/agents/') or path.startswith('/api/projects/') or path.startswith('/api/tasks/'):
            parts=path.strip('/').split('/'); kind=parts[1]; item_id=parts[2] if len(parts)>2 else ''
            if kind not in DOMAIN_FILES: return self.send_json(404, {'error':'Неизвестный раздел'})
            items=domain_items(kind); item=next((x for x in items if x.get('id')==item_id),None)
            if not item: return self.send_json(404, {'error':'Запись не найдена'})
            allowed={'agents':{'name','role','model','description','system_prompt','memory','permissions','avatar','system_enabled'},'projects':{'name','path','description','logo','env_type','ssh_connection_id','github_connection_id','repo_name'},'tasks':{'title','description','model','agent_id','project_id','team_mode','active_roles'}}[kind]
            if kind == 'projects' and 'env_type' in data and str(data.get('env_type','')).strip().lower() not in ('local','github','ssh'):
                return self.send_json(400, {'error':'env_type должен быть local, github или ssh'})
            if kind == 'projects':
                target_env = str(data.get('env_type', item.get('env_type', 'local')) or 'local').strip().lower()
                target_path = str(data.get('path', item.get('path', '')) or '').strip()[:1000]
                if target_env == 'local':
                    if not target_path: return self.send_json(400, {'error':'Для локального проекта обязательно укажите рабочую папку.'})
                    try: target_path = grant_project_folder_to_agents(target_path)
                    except (OSError, RuntimeError, ValueError) as exc: return self.send_json(400, {'error':str(exc) or 'Рабочая папка не найдена.'})
                if 'path' in data: data['path'] = target_path
            for key in allowed:
                if key not in data: continue
                if kind=='projects' and key=='env_type': item[key]=str(data[key]).strip().lower()
                elif kind=='agents' and key=='permissions':
                    try:
                        item[key] = _normalize_agent_permissions(data[key])
                    except ValueError as exc:
                        return self.send_json(400, {'error': str(exc)})
                elif kind=='agents' and key=='system_enabled':
                    if not item.get('system'): return self.send_json(400, {'error':'Переключать можно только системных агентов'})
                    item[key]=bool(data[key])
                elif kind=='agents' and key in {'system_prompt','memory'}: item[key]=str(data[key]).strip()[:(4000 if key=='system_prompt' else 8000)]
                elif kind=='projects' and key=='logo':
                    try:
                        item[key] = save_project_logo(item_id, data[key], item.get('logo', ''))
                    except ValueError as exc:
                        return self.send_json(400, {'error': str(exc)})
                elif kind=='tasks' and key=='team_mode': item[key]=bool(data[key])
                elif kind=='tasks' and key=='active_roles':
                    if not isinstance(data[key], list): return self.send_json(400, {'error':'active_roles должен быть списком ролей'})
                    active = [str(role).upper() for role in data[key] if str(role).upper() in AGENT_ROLES]
                    if 'MANAGER' not in active: active.insert(0, 'MANAGER')
                    item[key] = active
                else: item[key]=str(data[key]).strip()[:5000]
            save_domain(kind,items); log_event(kind[:-1]+'.update',item.get('name',item.get('title','')))
            return self.send_json(200,item)
        if path=='/api/permissions':
            current=permission_settings()
            if 'local_files' in data:
                if not isinstance(data.get('local_files'),bool): return self.send_json(400, {'error':'local_files должен быть логическим значением'})
                current['local_files']=data['local_files']
            if current['local_files'] and not current['roots']: return self.send_json(409, {'error':'Сначала добавьте хотя бы одну разрешённую папку.'})
            write_json(DATA/'permissions.json',current); log_event('permissions.global',str(current['local_files']))
            return self.send_json(200,current)
        if path=='/api/permissions/roots':
            current=permission_settings(); raw_path=str(data.get('path','')).strip().strip('"'); action=str(data.get('action','add'))
            if action=='remove':
                current['roots']=[p for p in current['roots'] if p!=raw_path]
                if not current['roots']: current['local_files']=False
                write_json(DATA/'permissions.json',current); log_event('permissions.root.remove',raw_path); return self.send_json(200,current)
            if action!='add' or not raw_path: return self.send_json(400, {'error':'Укажите путь к папке'})
            try:
                from agent_tools import _contains_reparse
                raw_root=Path(raw_path).expanduser()
                if _contains_reparse(raw_root): return self.send_json(400, {'error':'Символические ссылки и junction нельзя добавлять в разрешённые папки.'})
                root=raw_root.resolve(strict=True)
                if not root.is_dir() or root.parent==root or _contains_reparse(root): return self.send_json(400, {'error':'Нужно выбрать существующую папку, не корень диска и без символических ссылок.'})
            except Exception as e: return self.send_json(400, {'error':'Папка недоступна: '+str(e)[:160]})
            normalized=str(root)
            if normalized not in current['roots']: current['roots'].append(normalized)
            write_json(DATA/'permissions.json',current); log_event('permissions.root.add',normalized)
            return self.send_json(200,current)
        if path=='/api/settings':
            allowed={'appearance','header','navigation','icons'}; current=settings()
            for k,v in data.items():
                if k in allowed and isinstance(v,dict):
                    if k=='icons':
                        cleaned={}
                        for key,val in list(v.items())[:100]:
                            if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',key): continue
                            if not isinstance(val,dict): continue
                            try:
                                variant=val.get('variant',0)
                                size=val.get('size',24)
                                if isinstance(variant,bool) or isinstance(size,bool): raise ValueError('boolean is not an integer setting')
                                variant=int(variant); size=int(size)
                            except (TypeError,ValueError):
                                return self.send_json(400, {'error':f'Некорректные variant/size для иконки {key}'})
                            primary=str(val.get('primary','#3b82f6'))
                            secondary=str(val.get('secondary','#64748b'))
                            if variant<0 or variant>3: return self.send_json(400, {'error':f'variant иконки {key} должен быть от 0 до 3'})
                            if not re.fullmatch(r'^#[0-9a-fA-F]{6}$',primary): return self.send_json(400, {'error':f'Некорректный primary-цвет иконки {key}'})
                            if not re.fullmatch(r'^#[0-9a-fA-F]{6}$',secondary): return self.send_json(400, {'error':f'Некорректный secondary-цвет иконки {key}'})
                            if size<12 or size>64: return self.send_json(400, {'error':f'Размер иконки {key} должен быть от 12 до 64'})
                            icon_config={'variant':variant,'primary':primary,'secondary':secondary,'size':size}
                            custom_svg=val.get('svg')
                            if custom_svg not in (None,''):
                                if not isinstance(custom_svg,str):
                                    return self.send_json(400, {'error':f'SVG иконки {key} должен быть текстом'})
                                if len(custom_svg.encode('utf-8'))>256*1024:
                                    return self.send_json(413, {'error':f'SVG иконки {key} слишком большой (макс. 256 КБ)'})
                                if not re.fullmatch(r'\s*<svg\b[\s\S]*</svg>\s*',custom_svg,re.IGNORECASE):
                                    return self.send_json(400, {'error':f'Некорректный SVG иконки {key}: нужен полный элемент <svg>'})
                                if re.search(r'<\s*(script|foreignObject|iframe|object|embed)\b|\son[a-z][\w:-]*\s*=|\b(?:href|xlink:href)\s*=\s*["\']\s*(?:https?:|//|javascript:|data:)|\burl\s*\(',custom_svg,re.IGNORECASE):
                                    return self.send_json(400, {'error':f'SVG иконки {key} содержит небезопасные элементы или ссылки'})
                                icon_config['svg']=custom_svg.strip()
                            cleaned[key]=icon_config
                        current['icons']=cleaned
                        continue
                    if k=='navigation' and isinstance(v.get('menu'),list):
                        menu=[]
                        for item in v['menu'][:100]:
                            if not isinstance(item,dict): continue
                            pid=str(item.get('page_id','')).strip()[:80]
                            if pid and not re.fullmatch(r'[a-zA-Z0-9_-]+',pid): continue
                            menu.append({'id':str(item.get('id') or uuid.uuid4().hex[:10])[:40],'label':str(item.get('label') or '')[:100],'icon':str(item.get('icon') or 'file-text')[:40],'page_id':pid,'visible':item.get('visible') is not False,'parent_id':str(item.get('parent_id') or '')[:40]})
                        v={**v,'menu':menu}
                    current[k]={**current.get(k,{}),**v}
            write_json(DATA/'settings.json',current); log_event('settings.save','Настройки интерфейса сохранены'); return self.send_json(200,current)
        if path == '/api/icons':
            icon_id = str(data.get('id', '')).strip()
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', icon_id):
                return self.send_json(400, {'error': 'Некорректный id иконки'})
            if icon_id in {'cpu', 'hdd', 'monitor', 'ram', 'video'}:
                return self.send_json(403, {'error': 'Эта иконка зарезервирована для системной телеметрии'})
            if 'svg' not in data:
                try:
                    variant=data.get('variant',0); size=data.get('size',24)
                    if isinstance(variant,bool) or isinstance(size,bool): raise ValueError('boolean is not an integer setting')
                    variant=int(variant); size=int(size)
                except (TypeError,ValueError):
                    return self.send_json(400, {'error':'variant должен быть числом от 0 до 3, size — от 12 до 64'})
                primary=str(data.get('primary','#3b82f6'))
                secondary=str(data.get('secondary','#64748b'))
                if variant<0 or variant>3: return self.send_json(400, {'error':'variant должен быть от 0 до 3'})
                if not re.fullmatch(r'^#[0-9a-fA-F]{6}$',primary): return self.send_json(400, {'error':'primary должен быть HEX-цветом формата #RRGGBB'})
                if not re.fullmatch(r'^#[0-9a-fA-F]{6}$',secondary): return self.send_json(400, {'error':'secondary должен быть HEX-цветом формата #RRGGBB'})
                if size<12 or size>64: return self.send_json(400, {'error':'size должен быть от 12 до 64'})
                current=settings()
                icons=current.get('icons')
                if not isinstance(icons,dict): icons={}
                saved={'variant':variant,'primary':primary,'secondary':secondary,'size':size}
                icons[icon_id]=saved
                current['icons']=icons
                write_json(DATA/'settings.json',current)
                log_event('icons.settings',f'Настройки иконки {icon_id} сохранены')
                return self.send_json(200, {'ok':True,'id':icon_id,'icon':saved,'icons':icons})
            svg = data.get('svg')
            if not isinstance(svg, str) or not svg.strip():
                return self.send_json(400, {'error': 'Пустой SVG'})
            if len(svg.encode('utf-8')) > 256 * 1024:
                return self.send_json(413, {'error': 'SVG слишком большой (макс. 256 КБ)'})
            svg_lower = svg.lower()
            forbidden = [
                '<!doctype', '<?xml', '<script', '<iframe', '<object',
                '<embed', '<foreignobject', 'javascript:', 'data:text/html'
            ]
            for token in forbidden:
                if token in svg_lower:
                    return self.send_json(400, {'error': 'SVG содержит запрещённые элементы'})
            if re.search(r'\son[a-z]+\s*=', svg_lower):
                return self.send_json(400, {'error': 'SVG содержит inline-обработчики'})
            stripped = svg.lstrip()
            if not stripped.lower().startswith('<svg') or not re.match(r'<svg(?:\s|>)', stripped, re.IGNORECASE):
                return self.send_json(400, {'error': 'Файл не является SVG'})
            target = ICONS_DIR / f'{icon_id}.svg'
            try:
                target.write_text(svg, encoding='utf-8')
            except OSError as e:
                return self.send_json(500, {'error': f'Не удалось сохранить: {e}'})
            saved_size = None
            size = data.get('size')
            if size is not None:
                try:
                    parsed_size = int(size)
                except (TypeError, ValueError):
                    parsed_size = None
                if parsed_size is not None and 12 <= parsed_size <= 64:
                    current = settings()
                    icons = current.get('icons')
                    if not isinstance(icons, dict):
                        icons = {}
                    icons[icon_id] = {'size': parsed_size}
                    current['icons'] = icons
                    write_json(DATA / 'settings.json', current)
                    saved_size = parsed_size
            log_event('icons.upload', f'Иконка {icon_id} сохранена')
            return self.send_json(200, {
                'ok': True,
                'id': icon_id,
                'path': f'/icons/{icon_id}.svg',
                'size': saved_size
            })
        if path=='/api/pages':
            title=str(data.get('title','')).strip()[:100]; desc=str(data.get('description','')).strip()[:300]; content=str(data.get('content','')).strip()[:20000]
            if not title: return self.send_json(400, {'error':'Укажите название страницы'})
            slug=re.sub(r'[^a-z0-9-]+','-',str(data.get('id') or title.lower())).strip('-')[:60] or uuid.uuid4().hex[:8]
            current=pages()
            if any(p['id']==slug for p in current): return self.send_json(409, {'error':'Страница с таким идентификатором уже существует'})
            item={'id':slug,'title':title,'description':desc,'icon':'file-text','content':content,'system':False,'created_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}; current.append(item); write_json(PAGES/'index.json',current); log_event('page.create',title); return self.send_json(201,item)
        if path.startswith('/api/pages/') and path.endswith('/update'):
            pid=path.split('/')[-2]; current=pages(); item=next((p for p in current if p['id']==pid),None)
            if not item: return self.send_json(404, {'error':'Страница не найдена'})
            for k,limit in [('title',100),('description',300),('content',20000)]:
                if k in data: item[k]=str(data[k]).strip()[:limit]
            write_json(PAGES/'index.json',current); log_event('page.update',item['title']); return self.send_json(200,item)
        if path=='/api/modules':
            raw_id=str(data.get('id','')).strip().lower()
            module_id=re.sub(r'[^a-z0-9._-]+','-',raw_id).strip('-')[:80]
            name=str(data.get('name','')).strip()[:120]
            description=str(data.get('description','')).strip()[:1000]
            version=str(data.get('version','1.0.0')).strip()[:40] or '1.0.0'
            if not module_id or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,79}',module_id): return self.send_json(400, {'error':'ID: 2–80 символов, латиница, цифры, точка, дефис или подчёркивание'})
            if not name: return self.send_json(400, {'error':'Укажите название модуля'})
            current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
            if any(m.get('id')==module_id for m in current.get('modules',[])): return self.send_json(409, {'error':'Модуль с таким ID уже существует'})
            inputs=[{'name':x.strip(),'type':'text','required':False} for x in str(data.get('inputs','')).split(',') if x.strip()][:30]
            outputs=[{'name':x.strip(),'type':'text'} for x in str(data.get('outputs','')).split(',') if x.strip()][:30]
            if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',p['name']) for p in inputs+outputs): return self.send_json(400, {'error':'Имена портов должны содержать латинские буквы, цифры, точку, дефис или подчёркивание.'})
            if len({p['name'] for p in inputs})!=len(inputs) or len({p['name'] for p in outputs})!=len(outputs): return self.send_json(400, {'error':'Имена портов должны быть уникальными.'})
            runtime_kind=str(data.get('runtime_kind','input')).strip()
            if runtime_kind not in MODULE_RUNTIME_KINDS: return self.send_json(400, {'error':'Неизвестный встроенный тип модуля'})
            runtime={'kind':runtime_kind}
            if runtime_kind=='template': runtime['template']=str(data.get('template') or '{input}')[:12000]
            if runtime_kind=='transform':
                operation=str(data.get('operation','strip'))
                if operation not in {'uppercase','lowercase','strip','json_parse','json_pretty'}: return self.send_json(400, {'error':'Неизвестная операция преобразования'})
                runtime['operation']=operation
            if runtime_kind=='ollama':
                runtime['system_prompt']=str(data.get('system_prompt',''))[:4000]
                runtime['model']=str(data.get('model',''))[:160]
                try: max_tokens=int(data.get('max_tokens',1024))
                except (TypeError,ValueError): max_tokens=1024
                runtime['max_tokens']=min(max(max_tokens,64),4096)
            manifest={'id':module_id,'name':name,'version':version,'description':description,'api_version':'1.0','inputs':inputs,'outputs':outputs,'runtime':runtime,'capabilities':[],'permissions':[],'dependencies':[]}
            folder=MODULES/module_id
            if folder.exists(): return self.send_json(409, {'error':'Папка модуля уже существует; проверьте каталог modules/'})
            folder.mkdir(parents=True,exist_ok=False)
            write_json(folder/'module.json',manifest)
            (folder/'README.md').write_text('# '+name+'\n\n'+description+'\n\nЛокальный каркас модуля PQlocalAgentOSv3. Добавьте реализацию после определения входов, выходов и разрешений. Код не запускается автоматически.\n',encoding='utf-8')
            module={'id':module_id,'name':name,'description':description,'version':version,'source':'local','url':'','stars':0,'license':'Не указана','status':'draft','trusted':False,'manifest':manifest,'created_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'note':'Локальный каркас создан. Реализация не запускается автоматически.'}
            current.setdefault('modules',[]).append(module); current.setdefault('connections',[]); write_json(DATA/'modules.json',current); log_event('module.create',module_id)
            return self.send_json(201, {'ok':True,'module':module})
        if path=='/api/modules/update':
            module_id=str(data.get('id','')).strip()
            current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
            module=next((m for m in current.get('modules',[]) if m.get('id')==module_id),None)
            if not module: return self.send_json(404, {'error':'Модуль не найден'})
            if module.get('source')!='local': return self.send_json(403, {'error':'Редактирование runtime доступно для локальных модулей. Для GitHub-модулей нужен проверенный адаптер.'})
            runtime_kind=str(data.get('runtime_kind','')).strip()
            if runtime_kind not in MODULE_RUNTIME_KINDS: return self.send_json(400, {'error':'Неизвестный встроенный тип модуля'})
            def parse_port_names(raw):
                names=[x.strip() for x in str(raw or '').split(',') if x.strip()][:30]
                if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',name) for name in names): raise ValueError('Имена портов должны содержать латинские буквы, цифры, точку, дефис или подчёркивание.')
                if len(names)!=len(set(names)): raise ValueError('Имена портов должны быть уникальными.')
                return names
            try:
                input_names=parse_port_names(data.get('inputs','')); output_names=parse_port_names(data.get('outputs',''))
            except ValueError as e: return self.send_json(400, {'error':str(e)})
            manifest=module_runtime_manifest(module).copy()
            runtime={'kind':runtime_kind}
            if runtime_kind=='template': runtime['template']=str(data.get('template','{input}'))[:12000]
            if runtime_kind=='transform':
                operation=str(data.get('operation','strip'))
                if operation not in {'uppercase','lowercase','strip','json_parse','json_pretty'}: return self.send_json(400, {'error':'Неизвестная операция преобразования'})
                runtime['operation']=operation
            if runtime_kind=='ollama':
                runtime['system_prompt']=str(data.get('system_prompt',''))[:4000]
                runtime['model']=str(data.get('model',''))[:160]
                try: max_tokens=int(data.get('max_tokens',1024))
                except (TypeError,ValueError): max_tokens=1024
                runtime['max_tokens']=min(max(max_tokens,64),4096)
            manifest.update({'inputs':[{'name':name,'type':'text','required':False} for name in input_names],'outputs':[{'name':name,'type':'text'} for name in output_names],'runtime':runtime})
            manifest['version']=str(data.get('version',module.get('version','1.0.0')).strip()[:40] or '1.0.0')
            manifest['description']=str(data.get('description',module.get('description','')).strip()[:1000])
            folder=MODULES/module_id
            if not folder.is_dir() or folder.resolve().parent!=MODULES.resolve(): return self.send_json(400, {'error':'Не найдена локальная папка модуля'})
            previous_manifest=module_runtime_manifest(module)
            module.update({'version':manifest['version'],'description':manifest['description'],'manifest':manifest,'status':'draft','note':'Настройки runtime сохранены. Модуль выполняется только через встроенный безопасный исполнитель.'})
            try: current['connections']=validate_module_connections(current,current.get('connections',[]))
            except ValueError as e:
                module['manifest']=previous_manifest; module['version']=previous_manifest.get('version',module.get('version','1.0.0')); module['description']=previous_manifest.get('description',module.get('description',''))
                return self.send_json(400, {'error':'Изменение портов нарушит существующие связи: '+str(e)})
            write_json(folder/'module.json',manifest)
            write_json(DATA/'modules.json',current); log_event('module.update',module_id)
            return self.send_json(200, {'ok':True,'module':module})
        if path=='/api/modules/install':
            full_name=str(data.get('full_name','')).strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',full_name): return self.send_json(400, {'error':'Некорректное имя репозитория'})
            try:
                repo_data=github_public_request('/repos/'+full_name)
                if repo_data.get('archived') or repo_data.get('disabled'): return self.send_json(400, {'error':'Архивный или отключённый репозиторий нельзя добавить'})
                current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
                if any(m.get('source')==full_name for m in current.get('modules',[])): return self.send_json(409, {'error':'Этот репозиторий уже добавлен'})
                module_id=re.sub(r'[^a-z0-9_-]+','-',full_name.split('/')[-1].lower()).strip('-')[:60] or uuid.uuid4().hex[:8]
                if len(module_id)<2: module_id='m-'+module_id
                if any(m.get('id')==module_id for m in current.get('modules',[])): return self.send_json(409, {'error':'ID модуля уже занят другим источником'})
                manifest={'id':module_id,'name':full_name.split('/')[-1],'version':'0.0.0','description':repo_data.get('description') or 'Модуль из GitHub','author':full_name.split('/')[0],'license':(repo_data.get('license') or {}).get('spdx_id') or 'Не указана','repository':repo_data.get('html_url',''),'api_version':'1.0','inputs':[],'outputs':[],'capabilities':[],'permissions':[],'dependencies':[]}
                module={'id':module_id,'name':full_name.split('/')[-1],'description':repo_data.get('description') or 'Модуль из GitHub','created_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'source':full_name,'url':repo_data.get('html_url',''),'stars':repo_data.get('stargazers_count',0),'license':(repo_data.get('license') or {}).get('spdx_id') or 'Не указана','default_branch':repo_data.get('default_branch','main'),'status':'registered','trusted':False,'manifest':manifest,'installed_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'note':'Добавлен в каталог. Код не скачан и не запускается автоматически.'}
                current.setdefault('modules',[]).append(module); current.setdefault('connections',[]); write_json(DATA/'modules.json',current); write_json(MODULES/module['id']/'module.json',manifest); log_event('module.register',full_name)
                return self.send_json(201, {'ok':True,'module':module,'message':'Репозиторий добавлен в каталог. Перед установкой кода проверьте содержимое, лицензию и зависимости.'})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        if path=='/api/modules/download':
            module_id=str(data.get('id','')).strip()
            current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
            module=next((m for m in current.get('modules',[]) if m.get('id')==module_id),None)
            if not module: return self.send_json(404, {'error':'Модуль не найден'})
            source=str(module.get('source',''))
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',source): return self.send_json(400, {'error':'Для этого локального модуля исходники из GitHub недоступны'})
            request_github=github_request if github_token_available() else github_public_request
            try:
                branch=str(module.get('default_branch') or 'main')
                tree=request_github('/repos/'+source+'/git/trees/'+urllib.parse.quote(branch,safe='')+'?recursive=1')
                if tree.get('truncated'): return self.send_json(400, {'error':'Репозиторий слишком велик для безопасной загрузки одним запросом'})
                allowed={'.py','.js','.mjs','.cjs','.ts','.json','.md','.txt','.yaml','.yml','.toml','.html','.css','.sh','.bat','.ps1','.go','.rs','.java','.c','.h','.cpp','.xml','.svg'}
                blocked={'node_modules','.git','.github','.venv','venv','dist','build','vendor','__pycache__'}
                candidates=[]
                for entry in tree.get('tree',[]):
                    rel=entry.get('path',''); parts=Path(rel).parts
                    if entry.get('type')!='blob' or not rel or len(parts)>8 or any(part in blocked for part in parts) or '..' in parts or rel.startswith('/') or any(re.search(r'[<>:"|?*]',part) or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL','COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8','COM9','LPT1','LPT2','LPT3','LPT4','LPT5','LPT6','LPT7','LPT8','LPT9'} for part in parts): continue
                    if Path(rel).suffix.lower() not in allowed or int(entry.get('size',0))>200000: continue
                    candidates.append(entry)
                if len(candidates)>100: return self.send_json(400, {'error':'В репозитории больше 100 текстовых файлов-кандидатов; загрузка ограничена'})
                if sum(int(entry.get('size',0)) for entry in candidates)>2_000_000: return self.send_json(400, {'error':'Исходники превышают лимит загрузки 2 МБ'})
                folder=(MODULES/module_id/'source').resolve(); folder.mkdir(parents=True,exist_ok=True)
                total=0; saved=[]
                for entry in candidates:
                    blob=request_github('/repos/'+source+'/git/blobs/'+entry['sha'])
                    if blob.get('encoding')!='base64': continue
                    raw=base64.b64decode(blob.get('content',''))
                    total+=len(raw)
                    if total>2_000_000: return self.send_json(400, {'error':'Исходники превышают лимит загрузки 2 МБ'})
                    try: text_content=raw.decode('utf-8')
                    except UnicodeDecodeError: continue
                    target=(folder/entry['path']).resolve()
                    if not target.is_relative_to(folder): continue
                    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text_content,encoding='utf-8'); saved.append(entry['path'])
                module['status']='downloaded_unverified'; module['downloaded_files']=len(saved); module['note']='Исходники скачаны в папку source и не запускаются. Проверьте код, зависимости, лицензию и разрешения.'
                write_json(DATA/'modules.json',current); log_event('module.download',source)
                return self.send_json(200, {'ok':True,'module':module,'files':saved,'total_bytes':total,'message':'Исходники загружены и оставлены неисполняемыми для проверки.'})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        if path=='/api/modules/run':
            try: return self.send_json(200, execute_module_graph(data))
            except ValueError as e:
                failed={'ok':False,'start_id':str(data.get('start_id','')),'error':str(e),'finished_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                runs=read_json(DATA/'module-runs.json',[]); runs=runs if isinstance(runs,list) else []; write_json(DATA/'module-runs.json',([failed]+runs)[:100]); log_event('module.graph.failed',str(e))
                return self.send_json(400, {'error':str(e),'run':failed})
            except Exception as e:
                failed={'ok':False,'start_id':str(data.get('start_id','')),'error':str(e)[:240],'finished_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
                runs=read_json(DATA/'module-runs.json',[]); runs=runs if isinstance(runs,list) else []; write_json(DATA/'module-runs.json',([failed]+runs)[:100]); log_event('module.graph.failed',str(e))
                return self.send_json(502, {'error':'Ошибка выполнения схемы: '+str(e)[:240],'run':failed})
        if path=='/api/modules/connections':
            current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
            try: current['connections']=validate_module_connections(current,data.get('connections',[]))
            except ValueError as e: return self.send_json(400, {'error':str(e)})
            write_json(DATA/'modules.json',current); log_event('module.connections','Связи модулей обновлены'); return self.send_json(200,current)
        if path=='/api/github/file':
            file_path=str(data.get('path','')).strip(); content=str(data.get('content','')); message=str(data.get('message','').strip() or 'Update '+file_path)[:200]
            if not file_path or file_path.startswith('/') or '..' in Path(file_path).parts: return self.send_json(400, {'error':'Некорректный путь файла'})
            if len(content)>800000: return self.send_json(400, {'error':'Файл слишком большой (максимум 800 КБ)'})
            try:
                existing=github_request('/repos/'+active_github_repository()+'/contents/'+urllib.parse.quote(file_path,safe='/'))
                expected_sha=str(data.get('sha',''))
                if expected_sha and expected_sha != existing.get('sha'): return self.send_json(409, {'error':'Файл изменился в GitHub после загрузки. Перечитайте его перед сохранением.'})
                branch=github_request('/repos/'+active_github_repository()).get('default_branch','main')
                result=github_request('/repos/'+active_github_repository()+'/contents/'+urllib.parse.quote(file_path,safe='/'),'PUT',{'message':message,'content':base64.b64encode(content.encode()).decode(),'sha':existing['sha'],'branch':branch})
                log_event('github.file.save',active_github_repository()+' · '+file_path)
                return self.send_json(200, {'ok':True,'path':file_path,'commit':result.get('commit',{}).get('html_url'),'message':'Изменения сохранены в GitHub'})
            except Exception as e: return self.send_json(400, {'error':str(e)})
        if path=='/api/github/check':
            self.path='/api/github/check'; return self.do_GET()
        return self.send_json(404, {'error':'API endpoint not found'})
    def do_DELETE(self):
        if not self._check_host(): return
        path=urlparse(self.path).path
        if self._must_change_password_blocked(path): return
        if path.startswith('/api/') and not self.require_auth(): return
        if path.startswith('/api/system-instructions/'):
            instruction_id = urllib.parse.unquote(path[len('/api/system-instructions/'):])
            if not instruction_id or '/' in instruction_id: return self.send_json(404, {'error': 'Инструкция не найдена'})
            items = ensure_system_instructions()
            item = next((x for x in items if x.get('id') == instruction_id), None)
            if not item: return self.send_json(404, {'error': 'Инструкция не найдена'})
            if item.get('is_default'): return self.send_json(403, {'error': 'Инструкцию по умолчанию нельзя удалить'})
            save_system_instructions([x for x in items if x.get('id') != instruction_id])
            log_event('system_instruction.delete', item.get('name', instruction_id))
            return self.send_json(200, {'ok': True})
        if path.startswith('/api/icons/'):
            icon_id = urllib.parse.unquote(path[len('/api/icons/'):])
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', icon_id):
                return self.send_json(400, {'error': 'Некорректный id'})
            if icon_id in {'cpu', 'hdd', 'monitor', 'ram', 'video'}:
                return self.send_json(403, {'error': 'Эта иконка зарезервирована для системной телеметрии'})
            target = ICONS_DIR / f'{icon_id}.svg'
            if target.exists():
                try:
                    target.unlink()
                except OSError as e:
                    return self.send_json(500, {'error': f'Не удалось удалить: {e}'})
            current = settings()
            icons = current.get('icons')
            if isinstance(icons, dict) and icon_id in icons:
                del icons[icon_id]
                current['icons'] = icons
                write_json(DATA / 'settings.json', current)
            log_event('icons.delete', f'Иконка {icon_id} удалена')
            return self.send_json(200, {'ok': True, 'id': icon_id})
        if path.startswith('/api/providers/'):
            pid=urllib.parse.unquote(path.split('/')[-1]); protected={'ollama','lm-studio','openai','anthropic','google-gemini','openrouter','groq'}
            if pid in protected: return self.send_json(403, {'error':'Встроенный провайдер не удаляется; его можно настроить'})
            items=read_json(PROVIDER_FILE,[]); items=items if isinstance(items,list) else []; updated=[x for x in items if x.get('id')!=pid]
            if len(updated)==len(items): return self.send_json(404, {'error':'Провайдер не найден'})
            write_json(PROVIDER_FILE,updated); log_event('provider.delete',pid); return self.send_json(200, {'ok':True})

        if path.startswith('/api/agents/') or path.startswith('/api/projects/') or path.startswith('/api/tasks/'):
            parts=path.strip('/').split('/'); kind=parts[1]; item_id=parts[2] if len(parts)>2 else ''
            if kind not in DOMAIN_FILES: return self.send_json(404, {'error':'Неизвестный раздел'})
            items=domain_items(kind); item=next((x for x in items if x.get('id')==item_id),None)
            if not item: return self.send_json(404, {'error':'Запись не найдена'})
            if kind=='agents' and item.get('system'): return self.send_json(403, {'error':'Системного агента нельзя удалить'})
            if kind=='projects':
                tasks=domain_items('tasks')
                if any(str(task.get('project_id') or task.get('projectId') or '')==str(item_id) for task in tasks):
                    return self.send_json(409, {'error':'Нельзя удалить проект, к которому привязаны задачи. Сначала удалите или переназначьте задачи'})
            items.remove(item); save_domain(kind,items); log_event(kind[:-1]+'.delete',item.get('name',item.get('title','')))
            return self.send_json(200, {'ok':True})
        if path.startswith('/api/modules/'):
            module_id=path.split('/')[-1]
            if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,79}',module_id): return self.send_json(400, {'error':'Некорректный ID модуля'})
            current=read_json(DATA/'modules.json', {'modules':[], 'connections':[]})
            item=next((m for m in current.get('modules',[]) if m.get('id')==module_id),None)
            if not item: return self.send_json(404, {'error':'Модуль не найден'})
            current['modules']=[m for m in current.get('modules',[]) if m.get('id')!=module_id]
            current['connections']=[x for x in current.get('connections',[]) if x.get('from')!=module_id and x.get('to')!=module_id]
            write_json(DATA/'modules.json',current)
            folder=MODULES/module_id
            if folder.exists() and folder.resolve().parent==MODULES.resolve(): shutil.rmtree(folder)
            log_event('module.remove',module_id); return self.send_json(200, {'ok':True})
        if path.startswith('/api/pages/'):
            pid=path.split('/')[-1]; current=pages(); item=next((p for p in current if p['id']==pid),None)
            if not item: return self.send_json(404, {'error':'Страница не найдена'})
            if item.get('system'): return self.send_json(403, {'error':'Системные страницы нельзя удалить'})
            write_json(PAGES/'index.json',[p for p in current if p['id']!=pid]); log_event('page.delete',item['title']); return self.send_json(200, {'ok':True})
        return self.send_json(404, {'error':'API endpoint not found'})
    def do_OPTIONS(self):
        if not self._check_host(): return
        path=urlparse(self.path).path
        if self._must_change_password_blocked(path): return
        self.send_response(204)
        self.end_headers()
    def do_GET_HEAD(self): pass
if __name__=='__main__':
    settings(); pages(); initialize_system_prompt_templates(); ensure_system_instructions(); ensure_agent_roles(); log_event('server.start',f'http://{HOST}:{PORT}')
    _start_gpu_background()
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'PQlocalAgentOSv3: http://{HOST}:{PORT}  (Ctrl+C to stop)')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nServer stopped')
    finally: server.server_close()

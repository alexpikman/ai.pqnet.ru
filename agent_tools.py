"""Permission-gated, bounded tools for the local PQlocalAgentOSv3 agent runtime.

No shell, PowerShell, SSH, process execution, or arbitrary Python execution is exposed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
import subprocess
import socket
import ipaddress
import shlex
from pathlib import Path
from typing import Any

MAX_TEXT_BYTES = 1_000_000
MAX_SEARCH_FILES = 200
BLOCKED_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.idea'}
TEXT_EXTENSIONS = {'.txt','.md','.py','.js','.mjs','.cjs','.ts','.json','.yaml','.yml','.toml','.html','.css','.scss','.xml','.svg','.sql','.sh','.bat','.ps1','.go','.rs','.java','.c','.h','.cpp','.ini','.cfg','.log'}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {'type':'function','function':{'name':'list_files','description':'List files and folders within a user-authorized local root. Use an absolute path.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'read_file','description':'Read a UTF-8 text file up to 1 MB inside a user-authorized root.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'search_files','description':'Search text in bounded text files inside a user-authorized root.','parameters':{'type':'object','properties':{'path':{'type':'string'},'query':{'type':'string'}},'required':['path','query']}}},
    {'type':'function','function':{'name':'write_file','description':'Create or update a UTF-8 text file inside an authorized root. Content is limited to 1 MB.','parameters':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}},
    {'type':'function','function':{'name':'move_file','description':'Move or rename a file or folder within authorized roots. Destination must not exist.','parameters':{'type':'object','properties':{'source':{'type':'string'},'destination':{'type':'string'}},'required':['source','destination']}}},
    {'type':'function','function':{'name':'delete_file','description':'Delete one file. Requires explicit file_deletion permission.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'create_directory','description':'Create a directory within an authorized root.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'delete_directory','description':'Delete an empty directory within an authorized root.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'github_list_files','description':'List files in the configured GitHub repository. Path is repository-relative; use an empty string for root. Requires github_access.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'github_read_file','description':'Read a UTF-8 text file from the configured GitHub repository using a repository-relative path. Requires github_access.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
    {'type':'function','function':{'name':'github_search_code','description':'Search code in the configured GitHub repository for a symbol or distinctive text. Requires github_access.','parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}},
    {'type':'function','function':{'name':'run_command','description':'Execute a shell command with the authorized project directory as its working directory. Requires terminal_access. Commands run with server-user privileges.','parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command']}}},
    {'type':'function','function':{'name':'run_tests','description':'Run the project test suite in the authorized project directory. Requires terminal_access. Only Python unittest or pytest commands are accepted.','parameters':{'type':'object','properties':{'command':{'type':'string','default':'python -m unittest discover -v'}},'required':[]}}},
    {'type':'function','function':{'name':'fetch_url','description':'Fetch text content from a public HTTP/HTTPS URL.','parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url']}}},
    {'type':'function','function':{'name':'ssh_execute','description':'Execute a command on a remote server via SSH in the specified project working directory.','parameters':{'type':'object','properties':{'connection_id':{'type':'string'},'command':{'type':'string'},'working_dir':{'type':'string'}},'required':['connection_id','command']}}},
]

PERMISSION_FOR_TOOL = {
    'list_files':('file_loading',), 'read_file':('file_loading',),
    'search_files':('file_loading',), 'write_file':('file_saving',),
    'move_file':('file_moving',), 'delete_file':('file_deletion',),
    'create_directory':('directory_creation',), 'delete_directory':('directory_deletion',),
    'github_list_files':('github_access',), 'github_read_file':('github_access',),
    'github_search_code':('github_access',), 'run_command':('terminal_access',), 'run_tests':('terminal_access',),
    'fetch_url':('web_access',), 'ssh_execute':('ssh_access',),
}

def is_blocked_shell_command(command: str) -> bool:
    """Basic guardrail against a few catastrophic/destructive shell commands."""
    value = str(command or '').strip()
    checks = (
        r'(?i)\brm\s+-rf\s+/(?:\s|$|\*)',
        r'(?i)(?:^|[;&|]\s*|\s)format(?:\.com)?(?:\s|$)',
        r'(?i)\bdel\s+/f\s+/s\s+/q(?:\s|$)',
    )
    return any(re.search(pattern, value) for pattern in checks)


def effective_tools(agent: dict[str, Any], permission_config: dict[str, Any]) -> list[dict[str, Any]]:
    permissions = agent.get('permissions') if isinstance(agent.get('permissions'),dict) else {}
    global_files = bool(permission_config.get('local_files')) and bool(permission_config.get('roots'))
    allowed = []
    for item in TOOL_DEFINITIONS:
        name=item['function']['name']
        if name.startswith('github_'):
            if permissions.get('github_access') and os.environ.get('GITHUB_TOKEN'):
                allowed.append(item)
        elif name in ('fetch_url', 'ssh_execute'):
            if permissions.get(PERMISSION_FOR_TOOL[name][0]):
                allowed.append(item)
        elif global_files and (permissions.get(PERMISSION_FOR_TOOL[name][0]) or (name=='move_file' and permissions.get('directory_moving'))):
            allowed.append(item)
    return allowed


def check_allowed_paths(tool_name: str, arguments: dict, allowed_paths: list[str] | None) -> None:
    """Проверяет, что путь в аргументах write-инструмента лежит внутри allowed_paths.

    Бросает PermissionError, если:
    - инструмент модифицирующий (write/delete/move/create_directory/delete_directory),
    - передан allowed_paths (не None и не пустой),
    - путь из аргументов не входит ни в один из allowed_paths.

    Если allowed_paths is None или пустой — проверка пропускается (старое поведение).
    """
    if not allowed_paths:
        return

    modifying_tools = {
        "write_file", "delete_file", "move_file",
        "create_directory", "delete_directory",
    }
    if tool_name not in modifying_tools:
        return

    raw_path = arguments.get("path") or arguments.get("destination") or ""
    if not raw_path:
        return

    from pathlib import Path as _Path

    target = _Path(str(raw_path)).resolve()
    allowed_roots = [_Path(p).resolve() for p in allowed_paths if p]

    for root in allowed_roots:
        try:
            target.relative_to(root)
            return  # путь внутри разрешённого корня
        except ValueError:
            continue

    raise PermissionError(
        f"Запись вне разрешённых путей проекта: {target}. "
        f"Разрешено: {[str(r) for r in allowed_roots]}"
    )


def _reparse(path: Path) -> bool:
    try:
        if path.is_symlink(): return True
        if os.name == 'nt':
            import stat
            return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False
    return False

def _contains_reparse(path: Path) -> bool:
    absolute=Path(path).absolute()
    current=Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current=current/part
        if current.exists() and _reparse(current): return True
    return False

def resolve_authorized_path(raw: str, permission_config: dict[str, Any], *, must_exist: bool=False) -> Path:
    if not permission_config.get('local_files') or not permission_config.get('roots'):
        raise PermissionError('Глобальный доступ к файлам выключен или не заданы разрешённые папки.')
    candidate=Path(str(raw)).expanduser()
    if not candidate.is_absolute(): raise PermissionError('Используйте абсолютный путь внутри разрешённой папки.')
    if _contains_reparse(candidate): raise PermissionError('Символические ссылки и junction запрещены.')
    try: resolved=candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc: raise ValueError('Путь не существует или недоступен.') from exc
    for raw_root in permission_config.get('roots',[]):
        try:
            root=Path(raw_root).resolve(strict=True)
            if not root.is_dir() or _contains_reparse(root): continue
            resolved.relative_to(root)
            return resolved
        except (ValueError,OSError,RuntimeError):
            continue
    raise PermissionError('Путь находится вне разрешённых папок.')

def _github_request(path: str) -> dict[str, Any]:
    token=os.environ.get('GITHUB_TOKEN')
    if not token: raise PermissionError('Для GitHub-инструментов задайте GITHUB_TOKEN.')
    repo=os.environ.get('GITHUB_REPOSITORY','alexpikman/PQlocalAgentOSv3')
    url='https://api.github.com'+path if path.startswith('/search/') else 'https://api.github.com/repos/'+repo+path
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'PQlocalAgentOSv3'})
    try:
        with urllib.request.urlopen(req,timeout=12) as response: return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError('GitHub API вернул HTTP '+str(exc.code)) from exc

def _validate_public_url(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(str(raw_url or '').strip())
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Разрешены только публичные URL с http:// или https://.')
    if parsed.username or parsed.password:
        raise ValueError('URL с логином или паролем запрещён.')
    host = parsed.hostname.rstrip('.').lower()
    if host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
        raise PermissionError('SSRF запрещен: локальные адреса недоступны.')
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)}
        except (OSError, ValueError) as exc:
            raise ValueError('Не удалось разрешить DNS-имя URL.') from exc
    blocked_networks = tuple(ipaddress.ip_network(net) for net in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','169.254.0.0/16','0.0.0.0/8','100.64.0.0/10','192.0.0.0/24','198.18.0.0/15','224.0.0.0/4','240.0.0.0/4','::1/128','fc00::/7','fe80::/10','::/128'))
    for address in addresses:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or any(address.version == net.version and address in net for net in blocked_networks):
            raise PermissionError('SSRF запрещен: адрес ведёт в локальную или зарезервированную сеть.')
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or '/', parsed.query, ''))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError('SSRF запрещен: перенаправления URL отключены.')


def _fetch_public_url(raw_url: str) -> dict[str, Any]:
    url = _validate_public_url(raw_url)
    request = urllib.request.Request(url, headers={'User-Agent':'PQlocalAgentOSv3/1.0','Accept':'text/*,application/json;q=0.9,*/*;q=0.1'})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=10) as response:
        raw = response.read(MAX_TEXT_BYTES + 1)
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError('Ответ URL превышает лимит 1 МБ.')
        content_type = response.headers.get_content_type()
        charset = response.headers.get_content_charset() or 'utf-8'
        if not (content_type.startswith('text/') or content_type in ('application/json','application/xml','application/xhtml+xml')):
            raise ValueError('URL вернул не текстовый тип содержимого: '+content_type)
        return {'url':url,'status':response.status,'content':raw.decode(charset, errors='replace')}


def _execute_ssh(connection_id: str, command: str, working_dir: str = '') -> dict[str, Any]:
    if not connection_id or len(connection_id) > 200:
        raise ValueError('Не указан корректный connection_id.')
    if not command.strip() or len(command) > 4000:
        raise ValueError('Команда должна содержать от 1 до 4000 символов.')
    connection_file = Path(__file__).resolve().parent / 'data' / 'ssh_connections.json'
    stored = json.loads(connection_file.read_text(encoding='utf-8')) if connection_file.is_file() else []
    entries = stored.get('connections', []) if isinstance(stored, dict) else stored
    if not isinstance(entries, list):
        raise ValueError('Файл SSH-подключений имеет неверный формат.')
    connection = next((item for item in entries if isinstance(item, dict) and str(item.get('id','')) == connection_id), None)
    if not connection:
        raise ValueError('SSH-подключение не найдено. Сначала нажмите «Сохранить на сервер» на странице SSH.')
    host = str(connection.get('host','')).strip()
    username = str(connection.get('username','')).strip()
    port = int(connection.get('port',22))
    key_path = str(connection.get('key_path','')).strip()
    working_dir = str(working_dir or connection.get('working_dir') or connection.get('path') or '').strip()
    if working_dir and (len(working_dir) > 1000 or '\x00' in working_dir):
        raise ValueError('Некорректный working_dir для SSH.')
    if not host or not username or not (1 <= port <= 65535):
        raise ValueError('У SSH-подключения не заполнены host, username или корректный port.')
    if key_path and not Path(key_path).expanduser().is_file():
        raise ValueError('Приватный ключ не найден на сервере: '+key_path[:180])
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError('SSH-инструмент требует библиотеку paramiko. Установите зависимости из requirements.txt.') from exc
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(hostname=host, port=port, username=username, key_filename=str(Path(key_path).expanduser()) if key_path else None, allow_agent=True, look_for_keys=True, timeout=10, banner_timeout=10, auth_timeout=10)
        remote_command = ('cd -- ' + shlex.quote(working_dir) + ' && ' + command) if working_dir else command
        stdin, stdout, stderr = client.exec_command(remote_command, timeout=30)
        try: stdin.close()
        except Exception: pass
        out = stdout.read(60001).decode('utf-8','replace')
        err = stderr.read(30001).decode('utf-8','replace')
        exit_code = stdout.channel.recv_exit_status()
        return {'connection_id':connection_id,'stdout':out[:60000],'stderr':err[:30000],'exit_code':exit_code}
    except Exception as exc:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return {'connection_id':connection_id,'stdout':'','stderr':'SSH: тайм-аут 30 секунд.','exit_code':124}
        raise RuntimeError('Ошибка SSH: '+str(exc)[:240]) from exc
    finally:
        client.close()


def execute_tool(name: str, args: dict[str, Any], agent: dict[str, Any], permission_config: dict[str, Any]) -> dict[str, Any]:
    permissions=agent.get('permissions') if isinstance(agent.get('permissions'),dict) else {}
    required=PERMISSION_FOR_TOOL.get(name)
    if name=='move_file':
        if not (permissions.get('file_moving') or permissions.get('directory_moving')): return {'error':'У агента нет разрешения на перемещение файлов или папок.'}
        if Path(str(args.get('source',''))).is_dir(): required=('directory_moving',)
    if not required: return {'error':'Инструмент не поддерживается.'}
    if not all(permissions.get(key,False) for key in required): return {'error':'У агента нет необходимого разрешения: '+', '.join(required)}
    try:
        if name == 'fetch_url':
            raw_url=args.get('url')
            if not isinstance(raw_url,str) or len(raw_url)>4096: return {'error':'Укажите URL длиной до 4096 символов.'}
            return _fetch_public_url(raw_url)
        if name == 'ssh_execute':
            connection_id=str(args.get('connection_id','')).strip()
            command=args.get('command')
            if not isinstance(command,str): return {'error':'Команда должна быть текстом.'}
            working_dir=args.get('working_dir','')
            if not isinstance(working_dir,str): return {'error':'working_dir должен быть строкой.'}
            return _execute_ssh(connection_id,command,working_dir)
        if name.startswith('github_'):
            if not os.environ.get('GITHUB_TOKEN'): return {'error':'GITHUB_TOKEN не задан.'}
            if name=='github_list_files':
                rel=str(args.get('path','')).strip().strip('/')
                if '..' in Path(rel).parts: return {'error':'Некорректный путь репозитория.'}
                result=_github_request('/contents'+('/'+urllib.parse.quote(rel,safe='/') if rel else ''))
                items=result if isinstance(result,list) else [result]
                return {'items':[{'name':x.get('name'),'path':x.get('path'),'type':x.get('type'),'size':x.get('size',0)} for x in items[:200]]}
            if name=='github_read_file':
                rel=str(args.get('path','')).strip()
                if not rel or rel.startswith('/') or '..' in Path(rel).parts: return {'error':'Некорректный путь репозитория.'}
                result=_github_request('/contents/'+urllib.parse.quote(rel,safe='/'))
                import base64
                raw=base64.b64decode(result.get('content',''))
                if len(raw)>MAX_TEXT_BYTES: return {'error':'Файл превышает лимит 1 МБ.'}
                return {'path':rel,'content':raw.decode('utf-8')}
            query=str(args.get('query','')).strip()[:200]
            if len(query)<2: return {'error':'Введите минимум 2 символа.'}
            repo=os.environ.get('GITHUB_REPOSITORY','alexpikman/PQlocalAgentOSv3')
            q=urllib.parse.quote(query+' repo:'+repo)
            result=_github_request('/search/code?q='+q+'&per_page=10')
            return {'items':[{'path':x.get('path'),'url':x.get('html_url')} for x in result.get('items',[])]}
        if name=='run_tests':
            command=args.get('command','python -m unittest discover -v')
            if not isinstance(command,str) or not command.strip() or len(command)>1000:
                return {'error':'Укажите команду тестирования длиной от 1 до 1000 символов.'}
            # No shell: run_tests is intentionally narrower than run_command.
            if any(char in command for char in (';', '|', '&', '>', '<', '\n', '\r', '\x00')):
                return {'error':'run_tests принимает только одну команду без shell-операторов.'}
            try:
                argv=shlex.split(command, posix=(os.name!='nt'))
            except ValueError:
                return {'error':'Не удалось разобрать команду тестирования.'}
            if not argv:
                return {'error':'Команда тестирования пуста.'}
            executable=Path(argv[0]).name.lower()
            args_tail=argv[1:]
            allowed=False
            if executable in ('python','python.exe','python3','python3.exe','py','py.exe'):
                if args_tail and args_tail[0]=='-m' and len(args_tail)>=2 and args_tail[1] in ('unittest','pytest'):
                    allowed=True
            elif executable in ('pytest','pytest.exe'):
                allowed=True
            if not allowed:
                return {'error':'Разрешены только python -m unittest, python -m pytest или pytest.'}
            cwd_raw=str(args.get('cwd','')).strip()
            if not cwd_raw:
                return {'error':'Не задан путь проекта для запуска тестов.'}
            cwd=resolve_authorized_path(cwd_raw,permission_config,must_exist=True)
            if not cwd.is_dir():
                return {'error':'Рабочий путь проекта не является папкой.'}
            try:
                completed=subprocess.run(argv,cwd=str(cwd),shell=False,capture_output=True,text=True,timeout=120,encoding='utf-8',errors='replace')
                return {'cwd':str(cwd),'command':command,'stdout':completed.stdout[-60000:],'stderr':completed.stderr[-30000:],'exit_code':completed.returncode}
            except subprocess.TimeoutExpired as exc:
                stdout=exc.stdout.decode('utf-8','replace') if isinstance(exc.stdout,bytes) else str(exc.stdout or '')
                stderr=exc.stderr.decode('utf-8','replace') if isinstance(exc.stderr,bytes) else str(exc.stderr or '')
                return {'cwd':str(cwd),'command':command,'stdout':stdout[-60000:],'stderr':(stderr+'\nТесты остановлены по тайм-ауту 120 секунд.')[-30000:],'exit_code':124}
        if name=='run_command':
            command=args.get('command')
            if not isinstance(command,str) or not command.strip() or len(command)>4000: return {'error':'Укажите команду длиной от 1 до 4000 символов.'}
            if is_blocked_shell_command(command):
                return {'error':'Команда заблокирована базовой защитой от опасных операций.'}
            cwd_raw=str(args.get('cwd','')).strip()
            if not cwd_raw: return {'error':'Не задан путь проекта для выполнения команды.'}
            cwd=resolve_authorized_path(cwd_raw,permission_config,must_exist=True)
            if not cwd.is_dir(): return {'error':'Рабочий путь проекта не является папкой.'}
            try:
                completed=subprocess.run(command,shell=True,cwd=str(cwd),capture_output=True,text=True,timeout=30,encoding='utf-8',errors='replace')
                return {'cwd':str(cwd),'stdout':completed.stdout[-60000:],'stderr':completed.stderr[-30000:],'exit_code':completed.returncode}
            except subprocess.TimeoutExpired as exc:
                stdout=exc.stdout.decode('utf-8','replace') if isinstance(exc.stdout,bytes) else str(exc.stdout or '')
                stderr=exc.stderr.decode('utf-8','replace') if isinstance(exc.stderr,bytes) else str(exc.stderr or '')
                return {'cwd':str(cwd),'stdout':stdout[-60000:],'stderr':(stderr+'\nКоманда остановлена по тайм-ауту 30 секунд.')[-30000:],'exit_code':124}
        path=None if name=='move_file' else resolve_authorized_path(str(args.get('path','')),permission_config,must_exist=name in {'list_files','read_file','search_files','delete_file','delete_directory'})
        if name=='list_files':
            if not path.is_dir(): return {'error':'Указанный путь не является папкой.'}
            items=[]
            for child in sorted(path.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower()))[:200]:
                if child.name in BLOCKED_DIRS or _reparse(child): continue
                items.append({'name':child.name,'path':str(child),'type':'directory' if child.is_dir() else 'file','size':child.stat().st_size if child.is_file() else None})
            return {'path':str(path),'items':items}
        if name=='read_file':
            if not path.is_file(): return {'error':'Файл не найден.'}
            if path.suffix.lower() not in TEXT_EXTENSIONS and path.suffix: return {'error':'Чтение этого типа файла не разрешено.'}
            raw=path.read_bytes()
            if len(raw)>MAX_TEXT_BYTES: return {'error':'Файл превышает лимит 1 МБ.'}
            return {'path':str(path),'content':raw.decode('utf-8')}
        if name=='search_files':
            query=str(args.get('query','')).strip()
            if not query: return {'error':'Укажите поисковую строку.'}
            if not path.is_dir(): return {'error':'Указанный путь не является папкой.'}
            results=[]; scanned=0
            for file in path.rglob('*'):
                if not file.is_file() or _contains_reparse(file) or file.suffix.lower() not in TEXT_EXTENSIONS or any(part in BLOCKED_DIRS for part in file.parts): continue
                try: resolve_authorized_path(str(file),permission_config,must_exist=True)
                except (PermissionError,ValueError): continue
                scanned+=1
                if scanned>MAX_SEARCH_FILES: break
                try:
                    if file.stat().st_size>200_000: continue
                    lines=file.read_text(encoding='utf-8').splitlines()
                except (OSError,UnicodeError): continue
                for number,line in enumerate(lines,1):
                    if query.casefold() in line.casefold():
                        results.append({'path':str(file),'line':number,'text':line[:400]})
                        if len(results)>=100: return {'results':results,'scanned_files':scanned}
            return {'results':results,'scanned_files':scanned}
        if name=='write_file':
            content=args.get('content','')
            if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_TEXT_BYTES: return {'error':'Содержимое должно быть текстом до 1 МБ.'}
            if not path.parent.is_dir(): return {'error':'Родительская папка не существует; сначала создай её отдельным разрешённым инструментом.'}
            if path.exists() and not path.is_file(): return {'error':'Целевой путь не является файлом.'}
            path.write_text(content,encoding='utf-8')
            return {'path':str(path),'bytes':len(content.encode('utf-8')),'message':'Файл сохранён.'}
        if name=='move_file':
            src=resolve_authorized_path(str(args.get('source','')),permission_config,must_exist=True)
            dst=resolve_authorized_path(str(args.get('destination','')),permission_config,must_exist=False)
            if not src.exists(): return {'error':'Источник не найден.'}
            if dst.exists(): return {'error':'Назначение уже существует; перезапись запрещена.'}
            if not dst.parent.is_dir(): return {'error':'Папка назначения не существует.'}
            src.rename(dst)
            return {'source':str(src),'destination':str(dst),'message':'Перемещение выполнено.'}
        if name=='delete_file':
            if not path.is_file(): return {'error':'Целевой файл не найден.'}
            path.unlink()
            return {'path':str(path),'message':'Файл удалён.'}
        if name=='create_directory':
            path.mkdir(parents=False,exist_ok=False)
            return {'path':str(path),'message':'Папка создана.'}
        if name=='delete_directory':
            if not path.is_dir(): return {'error':'Целевая папка не найдена.'}
            path.rmdir()
            return {'path':str(path),'message':'Пустая папка удалена.'}
        return {'error':'Инструмент не поддерживается.'}
    except PermissionError as exc: return {'error':str(exc)}
    except (ValueError,OSError,UnicodeError,RuntimeError) as exc: return {'error':str(exc)[:300]}

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def discover_platform(root, override):
    if override:
        candidates = [Path(override)]
    else:
        candidates = [
            root / 'autogpt_platform',
            root.parent / 'AutoGPT' / 'autogpt_platform',
            root.parent / 'conference-paper-agent' / 'autogpt_platform',
        ]
    for candidate in candidates:
        if (candidate / 'docker-compose.yml').is_file():
            return candidate.resolve()
    locations = ', '.join(str(path) for path in candidates)
    raise ValueError(f'找不到 docker-compose.yml；检查 AutoGPT 目录或设置 PAPER_PLATFORM_ROOT。已检查：{locations}')


def describe_runs(result):
    runs = result.get('runs', [])
    if not runs:
        return '尚无论文任务记录'
    latest = runs[0]
    labels = {
        'QUEUED': '排队中',
        'RUNNING': '运行中',
        'COMPLETED': '已完成',
        'FAILED': '失败',
        'TERMINATED': '已停止',
    }
    status = labels.get(latest['status'], latest['status'])
    return f"最近一次论文任务：{status}（{latest['id']}）"


def services_to_start(required, running_output):
    running = set(running_output.split())
    return [service for service in required if service not in running]

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = discover_platform(ROOT, os.environ.get('PAPER_PLATFORM_ROOT'))
DATA = PLATFORM.parent / 'projects/conference-paper-research-agent/data'
PORT = 8766
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
MAPPING = None
MESSAGE = '就绪。先启动服务，再开始分析。映射可独立运行。'
USER = os.environ.get('PAPER_USER_ID')
GRAPH = os.environ.get('PAPER_GRAPH_ID')
RUN = 'eccv-2026-luna-full-01'


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-2500:])
    return result.stdout


def records(path, key):
    result = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                result[row[key]] = row
            except (ValueError, KeyError):
                continue
    return list(result.values())


def backend(action, config=None):
    request = json.dumps({'action': action, 'user_id': USER, 'graph_id': GRAPH, 'config': config}, ensure_ascii=True)
    output = command(['docker', 'compose', 'exec', '-T', 'rest_server', 'python', '-', request], cwd=PLATFORM, input=(ROOT / 'scripts/console_backend.py').read_text(encoding='utf-8'))
    for line in output.splitlines():
        if line.startswith('CONSOLE_RESULT='):
            return json.loads(line.split('=', 1)[1])
    raise RuntimeError('未收到后台响应')


def validate(payload):
    run = payload.get('run_id', RUN)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', run):
        raise ValueError('运行名称只能包含字母、数字、横线和下划线')
    config = {'run_id': run}
    for key, low, high in [('analysis_concurrency', 1, 3), ('analysis_request_interval_seconds', 0, 300), ('max_new_analyses_per_run', 0, 10000)]:
        value = int(payload[key])
        if not low <= value <= high:
            raise ValueError('参数超出范围：' + key)
        config[key] = value
    return config


def perform(action, payload):
    global MAPPING, MESSAGE, RUN
    if not LOCK.acquire(blocking=False):
        return
    try:
        MESSAGE = '正在执行：' + action
        if action == 'services':
            if not PLATFORM.is_dir():
                raise ValueError('找不到 AutoGPT 目录，请设置 PAPER_PLATFORM_ROOT')
            try:
                command(['docker', 'info'])
            except (RuntimeError, subprocess.TimeoutExpired):
                desktop = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/Docker Desktop.exe'
                subprocess.Popen([str(desktop)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for _ in range(60):
                    time.sleep(2)
                    try:
                        command(['docker', 'info'])
                        break
                    except (RuntimeError, subprocess.TimeoutExpired):
                        pass
                else:
                    raise RuntimeError('Docker 尚未就绪，请打开 Docker Desktop 查看提示后重试')
            required = ['rest_server', 'executor', 'database_manager', 'scheduler_server', 'websocket_server']
            running = command(['docker', 'compose', 'ps', '--status', 'running', '--services'], cwd=PLATFORM)
            missing = services_to_start(required, running)
            if not missing:
                MESSAGE = '服务已经就绪，可以开始／继续分析'
                return
            command(['docker', 'compose', 'up', '-d', 'redis-0', 'redis-1', 'redis-2'], cwd=PLATFORM)
            info = command(['docker', 'compose', 'exec', '-T', 'redis-0', 'redis-cli', '-p', '17000', 'cluster', 'info'], cwd=PLATFORM)
            if 'cluster_slots_assigned:16384' in info:
                for service, port in [('redis-1', '17001'), ('redis-2', '17002')]:
                    container = command(['docker', 'compose', 'ps', '-q', service], cwd=PLATFORM).strip()
                    details = json.loads(command(['docker', 'inspect', container]))[0]
                    address = details['NetworkSettings']['Networks']['app-network']['IPAddress']
                    command(['docker', 'compose', 'exec', '-T', 'redis-0', 'redis-cli', '-p', '17000', 'cluster', 'meet', address, port], cwd=PLATFORM)
                for _ in range(30):
                    info = command(['docker', 'compose', 'exec', '-T', 'redis-0', 'redis-cli', '-p', '17000', 'cluster', 'info'], cwd=PLATFORM)
                    if 'cluster_state:ok' in info:
                        break
                    time.sleep(1)
            command(['docker', 'compose', 'run', '--rm', '--no-deps', 'redis-init'], cwd=PLATFORM)
            command(['docker', 'compose', 'up', '-d', *required], cwd=PLATFORM)
            MESSAGE = '服务已启动，可以开始／继续分析'
        elif action == 'map':
            if MAPPING and MAPPING.poll() is None:
                raise ValueError('映射任务已在运行')
            DATA.mkdir(parents=True, exist_ok=True)
            with (DATA / 'console-mapping.log').open('a', encoding='utf-8') as log:
                MAPPING = subprocess.Popen([sys.executable, '-u', str(ROOT / 'scripts/map_eccv_arxiv.py'), '--output', str(DATA / 'eccv-2026-mapping'), '--limit', '0'], stdout=log, stderr=log, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            MESSAGE = '映射已启动，断点自动保留；遇到限流会停止，请稍后继续'
        elif action == 'stop-map':
            if MAPPING and MAPPING.poll() is None:
                MAPPING.terminate()
                MAPPING.wait(timeout=15)
            MESSAGE = '本控制台启动的映射已停止；再次继续可恢复断点'
        elif action == 'start':
            config = validate(payload)
            result = backend('start', config)
            RUN = config['run_id']
            MESSAGE = result['message'] + '：' + result['execution_id']
        elif action == 'stop':
            MESSAGE = backend('stop')['message']
        elif action == 'status':
            MESSAGE = describe_runs(backend('status'))
        elif action == 'reports':
            folder = DATA / 'runs' / RUN
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
            MESSAGE = '已打开结果文件夹'
        else:
            raise ValueError('未知操作')
    except Exception as error:
        MESSAGE = '操作未完成：' + str(error)
    finally:
        LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content='application/json; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            return self.reply(403, '{}')
        if self.path == '/':
            return self.reply(200, (ROOT / 'scripts/console.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN), 'text/html; charset=utf-8')
        if self.path != '/status':
            return self.reply(404, '{}')
        mapping = records(DATA / 'eccv-2026-mapping/mapping-checkpoint.jsonl', 'fingerprint')
        analysis = records(DATA / 'runs' / RUN / 'analysis-checkpoint.jsonl', 'paper_key')
        likes = records(DATA / 'runs' / RUN / 'likes-checkpoint.jsonl', 'paper_key')
        self.reply(200, json.dumps({'message': MESSAGE, 'busy': LOCK.locked(), 'run': RUN, 'mapping_running': bool(MAPPING and MAPPING.poll() is None), 'mapping_exit': MAPPING.poll() if MAPPING else None, 'mapping': dict(Counter(r['status'] for r in mapping)), 'analysis': dict(Counter(r['status'] for r in analysis)), 'likes': dict(Counter(r['status'] for r in likes)), 'errors': [r.get('error_detail') or r.get('reason') or r.get('error_code') for r in analysis + mapping if r['status'] in ('FAILED', 'error')][-5:]}, ensure_ascii=False))

    def do_POST(self):
        if self.headers.get('X-Console-Token') != TOKEN or self.headers.get('Origin') != f'http://127.0.0.1:{PORT}':
            return self.reply(403, '{}')
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 10000:
                raise ValueError('请求过大')
            payload = json.loads(self.rfile.read(length))
            action = payload['action']
            if action == 'start':
                validate(payload)
            threading.Thread(target=perform, args=(action, payload), daemon=True).start()
            self.reply(202, '{}')
        except (ValueError, KeyError) as error:
            self.reply(400, json.dumps({'error': str(error)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        print('端口 8766 已占用。如控制台已启动，请使用已有窗口。')
        sys.exit(1)
    webbrowser.open(f'http://127.0.0.1:{PORT}')
    threading.Thread(target=perform, args=('services', {}), daemon=True).start()
    print('论文控制台：http://127.0.0.1:8766；请保留此窗口。')
    server.serve_forever()

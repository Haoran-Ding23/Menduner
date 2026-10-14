"""Run from the repository root using the project virtual environment.
Tests real crawler -> SQLite -> HTTP API -> Vite proxy, plus six route shells.
Uses temporary storage; does not edit the user's database or credentials.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

def get(url):
    with urlopen(url, timeout=3) as response:
        return response.status, response.read()

def ready(url, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Server stopped before readiness; check ports 8000 and 5173')
        try:
            if get(url)[0] == 200:
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f'Server did not become ready: {url}')

def main():
    processes = []
    with tempfile.TemporaryDirectory(prefix='menduner-smoke-') as temp:
        path = Path(temp)
        env = dict(os.environ, MENDUNER_DB_PATH=str(path / 'smoke.sqlite3'))
        result = subprocess.run([sys.executable, '-m', 'crawler.demo.run', '--db', env['MENDUNER_DB_PATH']], cwd=ROOT, env={k:v for k,v in env.items() if k != "MENDUNER_DB_PATH"}, check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        assert report['eventsProcessed'] == 13 and report['eventsStored'] == 11 and report['duplicatesDetected'] == 2
        print('PASS crawler V1.4 CLI: 13 raw items / 11 unique synthetic events / 3 mock sources / 2 duplicates')
        with (path / 'servers.log').open('w') as logs:
            try:
                api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT, env=env, stdout=logs, stderr=logs)
                processes.append(api)
                ready('http://127.0.0.1:8000/status', api)
                vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], cwd=ROOT / 'frontend', stdout=logs, stderr=logs)
                processes.append(vite)
                ready('http://127.0.0.1:5173/map', vite)
                data = json.loads(get('http://127.0.0.1:5173/api/dataset')[1])
                assert data['status']['eventCount'] == 11
                assert data['status']['sourceCount'] == data['status']['mockSourceCount'] == 3
                assert data['status']['verificationCounts']['Verified'] == 0
                for endpoint in ('events', 'events/demo-01', 'venues', 'evidence', 'hotels', 'districts', 'status'):
                    status, body = get('http://127.0.0.1:5173/api/' + endpoint)
                    assert status == 200
                    json.loads(body)
                print('PASS real HTTP: FastAPI + SQLite -> Vite /api proxy -> dataset and all resource endpoints')
                for route in ('map', 'calendar', 'graph', 'hotels', 'insights', 'evidence'):
                    status, html = get('http://127.0.0.1:5173/' + route)
                    assert status == 200 and b'id="root"' in html
                print('PASS six Vite route shells (not browser rendering or AMap validation)')
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

if __name__ == '__main__':
    main()

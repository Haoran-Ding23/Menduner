# Team setup validation

Baseline: `e31c682` (existing Windows launcher). Team runtime now standard Python3.14.x venv; no conda fallback or installer invocation.

## Completed checks

| Check | Result |
|---|---|
| Python3.14 environment | Created backend/.venv using Python3.14.8 on Linux; prior3.12 environment preserved separately |
| pip install -r backend/requirements.txt | Passed; pinned package versions unchanged |
| pip check | No broken requirements |
| backend pytest | 8 passed; same upstream Starlette/httpx deprecation warning |
| backend reload startup | Python3.14.8 uvicorn --reload started; /docs HTTP200 |
| fresh frontend installation | Clean source copy, npm install passed on Node24.19 |
| fresh frontend build | npm run build passed; existing large-chunk warnings |
| real HTTP smoke | Mock CLI -> temporary SQLite -> FastAPI -> Vite /api proxy passed; six route shells HTTP200 |
| script grammar | PowerShell tree-sitter parse has no ERROR/missing nodes; not a Windows interpreter run |
| batch encoding | setup/start/stop use ASCII CRLF |
| environment.yml parity | Every noncomment requirements entry appears exactly, in order, under pip dependencies |

## Windows acceptance remains pending

This environment is Linux; it cannot run cmd.exe/Windows PowerShell windows or exercise browser shell associations. A fresh Windows machine's actual setup.bat -> start.bat workflow, pip Windows wheels, terminal process stopping and browser opening have NOT been verified here.

On the target Windows machine, install standard Python3.14.x and Node22.12+, then run setup.bat. Confirm successful backend/frontend installation. Run start.bat and confirm /docs, localhost:5173, /api/dataset and automatic /map browser opening. Run stop.bat and confirm only the managed process trees stop. Repeat setup with an incompatible old venv to confirm it refuses to overwrite it.

## Scope

New: setup.bat, README_SETUP.md, environment.yml and this validation record.
Updated: existing PowerShell launcher, current environment/startup documentation, requirements Python-version comment, and ignored old-environment backup pattern.

start.bat/stop.bat retain their existing entry points; behavior changes are in their shared helper. No frontend UI/source, backend API implementation, database schema, crawler logic, application dependency versions, Docker, CI/CD, authentication or cloud configuration changes.

YAML is reference-only. SQLite remains Python's bundled sqlite3, with no new pip database package. Local environments, runtime databases, keys and package caches are excluded from source delivery.

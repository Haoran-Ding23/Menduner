# Windows launcher verification

Baseline: local environment cleanup commit `9e54f54`.

## Completed in this environment

- Parsed scripts/windows-dev.ps1 with the tree-sitter PowerShell grammar: no ERROR or missing nodes. This is a syntax check, not the Windows PowerShell interpreter.
- Confirmed start.bat and stop.bat use ASCII + CRLF, resolve the helper via `%~dp0`, and propagate the helper exit code.
- Ran the existing scripts/smoke_pipeline.py with backend/.venv Python: crawler CLI -> temporary SQLite -> actual FastAPI HTTP -> Vite /api proxy passed; all six frontend route shells returned HTTP200.
- Reviewed process ownership: stop only invokes taskkill /PID /T /F after checking the saved terminal PID, powershell.exe name, random session token and helper path. No blanket python/node/image-name or port-based termination.
- Port conflicts are rejected before startup. Vite is explicitly bound to port5173 with strictPort; API proxy configuration is unchanged.
- No changes to frontend/src, backend code/API/schema, crawler code, package manifests or dependency versions.

## Windows execution remains unverified

The available runtime is Linux, with no Windows PowerShell, cmd.exe or Windows process manager. Actual double-click execution, conda fallback, separate terminal windows, paths with spaces and process-tree termination have NOT been run on Windows. Linux HTTP smoke results do not substitute for these checks.

On the target Windows machine:

1. Install dependencies as documented, then double-click start.bat. Confirm two service windows and the three successful readiness checks.
2. Open /docs and the frontend. Confirm /api/dataset returns the current SQLite data (zero events is valid before mock ingestion).
3. Double-click stop.bat; confirm both service windows close and ports8000/5173 are released. Other Python/Node applications should remain running.
4. Repeat stop.bat (no-op), then start twice (second launch should refuse duplicates).
5. Test a preoccupied port; the launcher should report the conflict without terminating its owner.
6. On a setup without backend/.venv but with conda menduner and installed dependencies, verify conda fallback. Missing both environments should give setup guidance.

Startup failure logs: .menduner-backend.log and .menduner-frontend.log. State and logs are local-only and ignored by Git. Existing manual-launch services must be stopped from their own terminals.

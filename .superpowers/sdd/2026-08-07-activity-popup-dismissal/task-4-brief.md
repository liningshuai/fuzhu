# Task 4: Full regression, documentation, and 8787 synchronization

Run the complete offline verification after Tasks 1-3:
`\.venv\Scripts\python.exe -m unittest discover -s tests -v`
and
`\.venv\Scripts\python.exe -m compileall -q src tests`.

Ensure the activity design spec and `assets/templates/README.md` reflect the final asset names/ROI. Restart only the exact project `main.py` service using `.venv\Scripts\python.exe main.py`; do not modify `config/runtime.yaml` or start task threads. Verify `http://127.0.0.1:8787/` returns HTTP 200 and call the stop endpoint so no挂机 thread remains.

If the emulator is available, run the live startup smoke test: activity pages close one by one via `(30,500)`, purchase/relogin/system dialogs are not consumed by generic activity handling, and tasks start only after `nav_fief`. Report any external state that was not live-tested. No Git initialization or commits.

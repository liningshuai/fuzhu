# Task 7 Report — Offline verification and 8787 synchronization

Date: 2026-08-10

## Completed steps

- Warehouse-focused test suite exited 0.
- `python -B -m compileall -q src tests scripts` exited 0.
- Complete `unittest` regression exited 0.
- 8787 started from the current workspace with `python main.py`.

## Live HTTP verification

- `GET http://127.0.0.1:8787/` → HTTP 200.
- The returned page contains `warehouse-panel` and `btn-warehouse-scan`.
- `GET /api/status` → `running=false`, `device_online=false`, `game_foreground=false`, `loop_count=0`.
- `GET /api/warehouse/status` → `status=idle`, no scan ID, zero completed categories/items/low-confidence rows.

## Not completed

The first live collection attempt was performed after the emulator reported online and the game was visibly at main city.

## Live collection attempt

- Scan ID: `1dc7af1932c34692a34b018e2177a184`.
- The scanner started exactly once and stopped at category `items`, page `0`.
- Final status: `failed`.
- Reason: the project dependency is declared in `requirements.txt`, but the active `.venv` does not contain `rapidocr_onnxruntime`; the controller reported `No module named 'rapidocr_onnxruntime'`.
- Database: `data/warehouse_catalog/catalog.db`; the failed session contains `0` items and `0` observations.
- Cleanup: verified by a fresh ADB screenshot at `task7_after_scan.png` and again after regression tests at `task7_after_regression.png`; the emulator was back at main city.
- No挂机 was started.
- An attempt to install the missing package through the approved escalation path was rejected by the environment approval service. No workaround or alternate unapproved installation was used.

## Acceptance status

- Five-category completion: not verified because OCR initialization failed before the first page could be parsed.
- Item count: `0` for this failed session.
- Low-confidence count: `0` (no page reached parsing).
- Return to main city: verified after failure.
- Warehouse focused suite: `28` tests passed.
- Compile check: passed.
- Complete regression suite: `164` tests passed.

The remaining task is to install the already-declared `rapidocr_onnxruntime` dependency in the project `.venv`, then repeat exactly one manual scan while the emulator is at main city.

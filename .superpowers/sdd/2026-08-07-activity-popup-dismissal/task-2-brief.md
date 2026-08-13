# Task 2: Add activity replay assets and validate the template catalog

Create normalized `assets/screenshots/startup_activity_replay.png` from the supplied screenshot at `C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-ac5950d9-c369-46df-b686-8292b53c946b.png`, using 1080x1920 vertical dimensions. Crop a stable current activity panel into `assets/templates/startup_activity_current_poster.png` without emulator chrome, dynamic counters, or red notification dots.

Modify `tests/session/test_startup_template_assets.py` with tests that the replay is `(1920,1080)`, both files are readable, and the current template matches the replay at threshold 0.90. Add the `startup_activity_*.png` convention to `assets/templates/README.md`: templates identify the activity panel, closing always uses `(30,500)`, and future activities can add assets without changing Python branches.

TDD order: add the failing asset assertions, run `\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v`, then create the binary assets and documentation, rerun the focused tests. Use the existing capture/vision utilities and verify the template match center lies inside the activity panel.

Do not modify startup code in this task. No Git initialization or commits.

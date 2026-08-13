# Task 3: Integrate bounded multi-popup dismissal into GameStartupFlow

Modify `src/session/startup.py`, `tests/session/test_startup.py`, and `tests/session/test_startup_replay.py` as needed. Add `GameStartupFlow(..., activity_detector: ActivityPopupDetector | None = None, max_activity_dismissals: int = 8)`. When no detector is passed, construct `ActivityPopupDetector(matcher)`. Preserve existing action priority: announcement, enter game, permanent claim, known highlight; then activity detector; then nav_fief success. `GameStartupTimeout` remains the failure type.

Add TDD replay tests with a FakeDevice sequence `activity_1 -> activity_2 -> main` and FakeActivityDetector. Assert exactly two safe blank taps `(30,500)` and a fresh-screen progression. Add a max-limit test with three activity states and limit 2; assert two taps then `GameStartupTimeout` containing `2`. Add a no-match/business-popup test asserting zero activity taps.

Run focused tests before implementation:
`\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay -v`
Then implement the counter and one-action-per-screenshot loop. On activity match, if count already reached the limit, raise; otherwise tap `(30,500)`, increment, log source/score/count, and `continue` to force a fresh screenshot. Do not change business task logic or general navigation behavior.

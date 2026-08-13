from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.loader import PipelineConfigError, load_pipeline


def main() -> int:
    pipeline_dir = ROOT / "config" / "pipelines"
    paths = sorted(pipeline_dir.glob("*.yaml"))
    if not paths:
        print(f"FAIL {pipeline_dir}: no pipeline files found")
        return 1

    failed = False
    for path in paths:
        try:
            load_pipeline(path)
        except PipelineConfigError as exc:
            failed = True
            print(f"{exc}")
            print(f"FAIL {path}")
        else:
            print(f"PASS {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

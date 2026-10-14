import argparse
import json
from pathlib import Path
from backend.database import database_path
from crawler.demo.sources import SOURCES
from crawler.pipeline import run_pipeline


class SimulatedFailure:
    def __init__(self, source):
        self.source_id = source.source_id

    def collect(self):
        raise RuntimeError("Simulated source failure; no network call was attempted")


def main():
    parser = argparse.ArgumentParser(
        description="DEMO only: isolated synthetic collection for offline tests"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--simulate-failure", choices=list(SOURCES))
    args = parser.parse_args()
    if args.db.resolve() == database_path():
        parser.error("DEMO may not target the production database path")
    adapters = [
        SimulatedFailure(cls()) if name == args.simulate_failure else cls()
        for name, cls in SOURCES.items()
    ]
    report = run_pipeline(args.db, adapters, allow_demo=True)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "Success" else 2


if __name__ == "__main__":
    raise SystemExit(main())

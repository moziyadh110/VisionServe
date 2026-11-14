"""Turn Locust CSVs from run_experiments.sh into a Markdown table for the README.

For each (label, user count) it takes the median of the repeated runs, as the load
test protocol asks: one run can be skewed by thermal throttling or a background task.

    uv run python loadtest/summarize.py [loadtest/results]
"""

import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

COLUMNS = ["p50 ms", "p95 ms", "p99 ms", "req/s", "error %", "peak VRAM MiB"]


def read_run(stats_csv: Path) -> dict[str, float] | None:
    with stats_csv.open(newline="") as f:
        rows = {row["Name"]: row for row in csv.DictReader(f)}
    # "Aggregated" covers every recorded request: new + repeated images. Signups are
    # sent outside Locust's stats, so these are true percentiles of inference latency.
    total = rows.get("Aggregated")
    if not total or int(total["Request Count"]) == 0:
        return None
    requests = int(total["Request Count"])

    vram_file = stats_csv.with_name(stats_csv.name.replace("_stats.csv", "_vram.txt"))
    peak_vram = None
    if vram_file.exists():
        values = [int(v) for v in vram_file.read_text().split() if v.strip().isdigit()]
        peak_vram = max(values) if values else None

    return {
        "p50 ms": float(total["50%"]),
        "p95 ms": float(total["95%"]),
        "p99 ms": float(total["99%"]),
        "req/s": float(total["Requests/s"]),
        "error %": 100 * int(total["Failure Count"]) / requests,
        "peak VRAM MiB": peak_vram,
    }


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "loadtest/results")
    runs: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for stats_csv in sorted(root.glob("*/u*_r*_stats.csv")):
        match = re.match(r"u(\d+)_r\d+_stats\.csv", stats_csv.name)
        result = read_run(stats_csv)
        if match and result:
            runs[(stats_csv.parent.name, int(match.group(1)))].append(result)

    if not runs:
        print(f"No results under {root}. Run loadtest/run_experiments.sh first.")
        return

    print("| config | users | " + " | ".join(COLUMNS) + " |")
    print("| --- | --- | " + " | ".join("---" for _ in COLUMNS) + " |")
    for (label, users), results in sorted(runs.items()):
        cells = []
        for col in COLUMNS:
            values = [r[col] for r in results if r[col] is not None]
            if not values:
                cells.append("-")
            elif col == "error %":
                cells.append(f"{statistics.median(values):.2f}")
            else:
                cells.append(f"{statistics.median(values):.0f}")
        print(f"| {label} | {users} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

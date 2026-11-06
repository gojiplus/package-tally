"""Collect a dated download snapshot and write JSON, CSV, and Markdown."""

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from package_tally.core import Client, collect, load_packages


def markdown(report: dict) -> str:
    rows = report["packages"]
    counted = sum(r["status"] == "ok" for r in rows)
    label = "Total" if report["complete"] else "Partial subtotal"
    lines = [
        "# Package download tally",
        "",
        f"**{label}: {report['observed_downloads']:,} downloads** "
        f"across {counted}/{len(rows)} packages.",
        "",
        f"Retrieved {report['finished_at']}.",
        "",
        "Python uses Pepy's all-time counter (coverage dates unspecified; badges "
        "cached up to 12 hours). R uses the RStudio mirror from 2012-10-01 "
        "through the last complete day reported by CRAN logs. These are source "
        "counters with different coverage, not unique users or installations.",
        "",
        "| Ecosystem | Downloads observed | Packages counted |",
        "| --- | ---: | ---: |",
    ]
    for name, subtotal in report["subtotals"].items():
        lines.append(
            f"| {name} | {subtotal['observed_downloads']:,} | "
            f"{subtotal['counted']}/{subtotal['packages']} |"
        )
    lines += [
        "",
        "| Package | Ecosystem | Downloads | Through |",
        "| --- | --- | ---: | --- |",
    ]
    for row in sorted(rows, key=lambda r: (-(r["downloads"] or 0), r["name"])):
        count = f"{row['downloads']:,}" if row["status"] == "ok" else "UNAVAILABLE"
        link = f"[{row['name']}]({row['url']})" if row["url"] else row["name"]
        lines.append(
            f"| {link} | {row['ecosystem']} | {count} | "
            f"{row['coverage_end'] or 'not supplied'} |"
        )
    errors = [row for row in rows if row["status"] != "ok"]
    discovery = report.get("discovery")
    if discovery:
        lines += ["", "## Package discovery", ""]
        if discovery["complete"]:
            lines.append(f"Verified {len(discovery['added'])} new package names.")
            for package in discovery["added"]:
                lines.append(f"- {package['ecosystem']}/{package['name']}")
        else:
            lines.append(
                "Discovery failed; this snapshot covers the previous inventory. "
                "The public badge and latest report were not updated."
            )
            lines += ["", discovery["error"]]
    if errors:
        lines += ["", "## Unavailable counts", ""]
        for row in errors:
            lines.append(f"- {row['ecosystem']}/{row['name']}: {row['error']}")
    return "\n".join(lines) + "\n"


def write_report(report: dict, directory: Path) -> None:
    (directory / "summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "summary.md").write_text(markdown(report), encoding="utf-8")
    columns = [
        "ecosystem",
        "name",
        "downloads",
        "status",
        "source",
        "coverage_start",
        "coverage_end",
        "fetched_at",
        "url",
        "repository",
        "error",
    ]
    with (directory / "packages.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["packages"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=Path("packages.toml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        packages = load_packages(args.manifest)
        directory = args.output or Path("reports") / datetime.now(UTC).strftime(
            "%Y-%m-%dT%H%M%SZ"
        )
        directory.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    manifest_bytes = args.manifest.read_bytes()
    (directory / "packages.toml").write_bytes(manifest_bytes)
    report = collect(packages, Client(directory / "raw"))
    report["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    write_report(report, directory)
    label = "Total" if report["complete"] else "Partial subtotal"
    print(f"{label}: {report['observed_downloads']:,} downloads")
    print(f"Report: {directory / 'summary.md'}")
    if not report["complete"]:
        print("Some counts are unavailable; see the report.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

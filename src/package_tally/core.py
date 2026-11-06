"""Manifest validation, HTTP snapshots, source parsers, and aggregation."""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode

CRAN_START = date(2012, 10, 1)
PEPY = "https://api.pepy.tech/personalized-badge/"
CRANLOGS = "https://cranlogs.r-pkg.org/downloads/total/"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    repository: str = ""
    evidence: str = ""
    note: str = ""


def load_packages(path: Path) -> list[Package]:
    with path.open("rb") as stream:
        manifest = tomllib.load(stream)
    rows = manifest.get("packages")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Manifest must contain at least one [[packages]] entry")
    packages = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - set(Package.__dataclass_fields__):
            raise ValueError(f"Unknown package fields: {row}")
        if row.get("ecosystem") not in {"pypi", "cran"}:
            raise ValueError("ecosystem must be pypi or cran")
        name = row.get("name")
        pattern = (
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
            if row["ecosystem"] == "pypi"
            else r"[A-Za-z][A-Za-z0-9.]*"
        )
        if not isinstance(name, str) or not re.fullmatch(pattern, name):
            raise ValueError(f"Invalid package name: {name!r}")
        if row["ecosystem"] == "cran" and name == "R":
            raise ValueError("R requests interpreter downloads, not a package")
        if any(not isinstance(value, str) for value in row.values()):
            raise ValueError("Package fields must be strings")
        name = normalize(name) if row["ecosystem"] == "pypi" else name
        package = Package(**{**row, "name": name})
        key = (package.ecosystem, name)
        if key in seen:
            raise ValueError(f"Duplicate package: {key}")
        seen.add(key)
        packages.append(package)
    return sorted(packages, key=lambda p: (p.ecosystem, p.name))


class FetchError(RuntimeError):
    """A source could not provide a usable response."""


class Client:
    def __init__(self, directory: Path, *, opener=None, sleep=time.sleep):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep

    def fetch(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "package-tally/0.1 (https://github.com/gojiplus/package-tally)"
                )
            },
        )
        for attempt in range(3):
            try:
                with self.opener(request, timeout=45) as response:
                    body = response.read()
                    record = {
                        "url": url,
                        "fetched_at": timestamp(),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "content_type": response.headers.get("Content-Type"),
                        "server_date": response.headers.get("Date"),
                        "cache_age": response.headers.get("Age"),
                        "body": body.decode("utf-8"),
                    }
                filename = hashlib.sha256(url.encode()).hexdigest() + ".json"
                (self.directory / filename).write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
                return record
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise FetchError(f"HTTP {exc.code}: {url}") from exc
                retry = exc.headers.get("Retry-After", "")
                delay = int(retry) if retry.isdecimal() else 2 ** (attempt + 1)
                if delay > 60:
                    raise FetchError(
                        f"Rate limited; retry after {delay} seconds: {url}"
                    ) from exc
                self.sleep(delay)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == 2:
                    raise FetchError(f"Connection failed: {url}: {exc}") from exc
                self.sleep(2 ** (attempt + 1))
        raise AssertionError("Unreachable")


def parse_pepy(body: str) -> int:
    """Read the unrounded badge value; reject abbreviated or error badges."""
    root = ET.fromstring(body)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Pepy did not return an SVG badge")
    texts = {
        "".join(node.itertext()).strip()
        for node in root.findall(".//{http://www.w3.org/2000/svg}text")
    }
    values = texts - {"downloads"}
    if "downloads" not in texts or len(values) != 1:
        raise ValueError(f"Unexpected Pepy badge text: {sorted(texts)}")
    value = values.pop()
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"Pepy did not return an exact integer: {value!r}")
    return int(value)


def parse_cran(body: str, name: str, start: date, end: date) -> int:
    rows = json.loads(body)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Expected exactly one CRAN logs result")
    row = rows[0]
    if not isinstance(row, dict) or row.get("package") != name:
        raise ValueError("CRAN logs returned the wrong package")
    if row.get("start") != str(start) or row.get("end") != str(end):
        raise ValueError("CRAN logs returned a different date range")
    count = row.get("downloads")
    if type(count) is not int or count < 0:
        raise ValueError("CRAN downloads must be a nonnegative integer")
    return count


def cran_latest(client: Client) -> date:
    record = client.fetch(CRANLOGS + "last-day")
    rows = json.loads(record["body"])
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Invalid CRAN logs last-day response")
    row = rows[0]
    if not isinstance(row, dict) or not isinstance(row.get("end"), str):
        raise ValueError("Invalid CRAN logs last-day record")
    end = date.fromisoformat(row["end"])
    if row.get("start") != str(end) or not CRAN_START <= end < datetime.now(UTC).date():
        raise ValueError("Invalid CRAN logs last complete day")
    return end


def collect(packages: list[Package], client: Client) -> dict:
    started = timestamp()
    cran_end = None
    cran_error = None
    if any(p.ecosystem == "cran" for p in packages):
        try:
            cran_end = cran_latest(client)
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            cran_error = str(exc)
    results = []
    for package in packages:
        is_python = package.ecosystem == "pypi"
        url = (
            PEPY
            + package.name
            + "?"
            + urlencode({"period": "TOTAL", "units": "NONE", "left_text": "downloads"})
            if is_python
            else f"{CRANLOGS}{CRAN_START}:{cran_end}/{package.name}"
        )
        row = {
            **asdict(package),
            "source": "pepy" if is_python else "cranlogs",
            "url": url if is_python or cran_end else None,
            "coverage_start": None if is_python else str(CRAN_START),
            "coverage_end": None if is_python or cran_end is None else str(cran_end),
            "coverage": (
                "Pepy all-time total; exact coverage dates not supplied; "
                "badge may be cached for 12 hours"
                if is_python
                else "RStudio CRAN mirror logs"
            ),
            "downloads": None,
            "status": "error",
        }
        try:
            if not is_python and cran_error:
                raise FetchError(cran_error)
            record = client.fetch(url)
            row["fetched_at"] = record["fetched_at"]
            row["response_sha256"] = record["sha256"]
            row["downloads"] = (
                parse_pepy(record["body"])
                if is_python
                else parse_cran(record["body"], package.name, CRAN_START, cran_end)
            )
            row["status"] = "ok"
        except (FetchError, ValueError, ET.ParseError, KeyError, TypeError) as exc:
            row["error"] = str(exc)
        results.append(row)
    subtotals = {}
    for ecosystem in ("pypi", "cran"):
        selected = [r for r in results if r["ecosystem"] == ecosystem]
        good = [r for r in selected if r["status"] == "ok"]
        subtotals[ecosystem] = {
            "packages": len(selected),
            "counted": len(good),
            "complete": len(good) == len(selected),
            "observed_downloads": sum(r["downloads"] for r in good),
        }
    complete = all(r["status"] == "ok" for r in results)
    observed = sum(s["observed_downloads"] for s in subtotals.values())
    return {
        "started_at": started,
        "finished_at": timestamp(),
        "complete": complete,
        "total_downloads": observed if complete else None,
        "observed_downloads": observed,
        "subtotals": subtotals,
        "packages": results,
    }

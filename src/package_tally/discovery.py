"""Find new registry packages while preserving the curated historical inventory."""

import json
import re
import time
import tomllib
import xmlrpc.client
from dataclasses import asdict
from pathlib import Path

from package_tally.core import Package, normalize

PYPI_RPC = "https://pypi.org/pypi"
CRAN_SEARCH = "https://search.r-pkg.org/package/_search"


def read_config(path: Path) -> dict:
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    required = {"author", "emails", "pypi_owner", "pypi_collaborators"}
    if set(config) != required:
        raise ValueError(f"Discovery config must specify {sorted(required)}")
    for key in ("author", "pypi_owner"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    for key in ("emails", "pypi_collaborators"):
        if not isinstance(config[key], list) or any(
            not isinstance(value, str) or not value.strip() for value in config[key]
        ):
            raise ValueError(f"{key} must be a list of nonempty strings")
    return config


def matches_identity(text: str, config: dict) -> bool:
    text = " ".join(text.casefold().split())
    values = [config["author"], *config["emails"]]
    return any(
        re.search(
            r"(?<!\w)" + re.escape(" ".join(v.casefold().split())) + r"(?!\w)", text
        )
        for v in values
    )


def pypi_names(client, username: str) -> set[str]:
    data = xmlrpc.client.dumps((username,), methodname="user_packages").encode()
    record = client.fetch(PYPI_RPC, data=data, content_type="text/xml")
    values, _ = xmlrpc.client.loads(record["body"])
    if len(values) != 1 or not isinstance(values[0], (list, tuple)):
        raise ValueError("Invalid PyPI ownership response")
    names = set()
    for row in values[0]:
        if (
            not isinstance(row, (list, tuple))
            or len(row) != 2
            or row[0] not in {"Owner", "Maintainer"}
            or not isinstance(row[1], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", row[1])
        ):
            raise ValueError("Invalid PyPI ownership record")
        names.add(normalize(row[1]))
    return names


def cran_records(client, author: str):
    data = json.dumps(
        {
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"Author": author}},
                        {"match_phrase": {"Maintainer": author}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        }
    ).encode()
    offset = 0
    while True:
        record = client.fetch(
            f"{CRAN_SEARCH}?from={offset}&size=100",
            data=data,
            content_type="application/json",
        )
        result = json.loads(record["body"])
        if result.get("timed_out") or result.get("_shards", {}).get("failed", 0):
            raise ValueError("CRAN search returned incomplete results")
        total = result["hits"]["total"]
        if isinstance(total, dict):
            if total.get("relation") != "eq":
                raise ValueError("CRAN search did not report an exact result count")
            total = total["value"]
        hits = result["hits"]["hits"]
        if type(total) is not int or total < 0 or not isinstance(hits, list):
            raise ValueError("Invalid CRAN search result")
        if not hits and offset < total:
            raise ValueError("CRAN search pagination ended early")
        for hit in hits:
            yield hit["_id"], hit["_source"]
        offset += len(hits)
        if offset >= total:
            return


def discover(packages: list[Package], config: dict, client, *, sleep=time.sleep):
    known = {(p.ecosystem, p.name): p for p in packages}
    additions = []
    rejected = []
    owner = config["pypi_owner"]
    users = list(dict.fromkeys([owner, *config["pypi_collaborators"]]))
    candidates = {}
    for index, user in enumerate(users):
        if index:
            sleep(1)
        for name in pypi_names(client, user):
            candidates.setdefault(name, set()).add(user)
    for name, accounts in sorted(candidates.items()):
        if ("pypi", name) in known:
            continue
        url = f"https://pypi.org/pypi/{name}/json"
        info = json.loads(client.fetch(url)["body"])["info"]
        if normalize(info["name"]) != name:
            raise ValueError(f"PyPI returned the wrong project for {name}")
        authors = " ".join(
            str(info.get(key) or "")
            for key in ("author", "author_email", "maintainer", "maintainer_email")
        )
        if owner not in accounts and not matches_identity(authors, config):
            rejected.append(
                {"ecosystem": "pypi", "name": name, "reason": "Identity mismatch"}
            )
            continue
        urls = info.get("project_urls") or {}
        repository = next(
            (
                value
                for key, value in urls.items()
                if key.lower() in {"repository", "source", "homepage"}
            ),
            "",
        )
        package = Package(
            "pypi",
            name,
            repository,
            url,
            f"Discovered via PyPI accounts: {', '.join(sorted(accounts))}; "
            + (
                f"maintained by {owner}."
                if owner in accounts
                else "author identity matched."
            ),
        )
        known[("pypi", name)] = package
        additions.append(asdict(package))
    for name, info in cran_records(client, config["author"]):
        if ("cran", name) in known:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.]*", name) or name == "R":
            raise ValueError("Invalid CRAN package name")
        authors = str(info.get("Author", "")) + " " + str(info.get("Maintainer", ""))
        if not matches_identity(authors, config):
            rejected.append(
                {"ecosystem": "cran", "name": name, "reason": "Identity mismatch"}
            )
            continue
        match = re.search(r"https://github.com/[^,\s]+", str(info.get("URL", "")))
        package = Package(
            "cran",
            name,
            match[0] if match else "",
            f"https://cran.r-project.org/web/packages/{name}/index.html",
            "Discovered through CRAN author/maintainer search; identity matched.",
        )
        known[("cran", name)] = package
        additions.append(asdict(package))
    return sorted(known.values(), key=lambda p: (p.ecosystem, p.name)), {
        "complete": True,
        "added": additions,
        "rejected": rejected,
        "pypi_accounts": users,
    }


def manifest_text(packages: list[Package]) -> str:
    lines = ["# Curated inventory plus verified discoveries; see inventory/README.md."]
    for package in packages:
        lines.extend(["", "[[packages]]"])
        lines.extend(
            f"{key} = {json.dumps(value, ensure_ascii=False)}"
            for key, value in asdict(package).items()
            if value
        )
    return "\n".join(lines) + "\n"

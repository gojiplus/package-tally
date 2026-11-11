import hashlib
import json
import xmlrpc.client
from dataclasses import asdict

import pytest

from package_tally import refresh
from package_tally.core import Client, FetchError, Package, load_packages
from package_tally.discovery import (
    CRAN_SEARCH,
    PYPI_RPC,
    cran_records,
    discover,
    manifest_text,
    matches_identity,
    pypi_names,
    read_config,
)

CONFIG = {
    "author": "Gaurav Sood",
    "emails": ["contact@gsood.com"],
    "pypi_owner": "soodoku",
    "pypi_collaborators": ["collaborator"],
}


def rpc(names):
    return xmlrpc.client.dumps(([["Owner", n] for n in names],), methodresponse=True)


class DiscoveryClient:
    def __init__(self):
        self.calls = []

    def fetch(self, url, *, data=None, content_type=None):
        self.calls.append((url, data))
        if url == PYPI_RPC:
            params, method = xmlrpc.client.loads(data)
            assert method == "user_packages"
            assert content_type == "text/xml"
            names = (
                ["old", "own_new", "shared"]
                if params[0] == "soodoku"
                else ["shared", "coauthored", "unrelated"]
            )
            return {"body": rpc(names)}
        if url.startswith(CRAN_SEARCH):
            return {
                "body": json.dumps(
                    {
                        "hits": {
                            "total": 2,
                            "hits": [
                                {
                                    "_id": "newR",
                                    "_source": {
                                        "Author": "Gaurav Sood [aut]",
                                        "URL": "https://github.com/example/newR",
                                    },
                                },
                                {
                                    "_id": "falseHit",
                                    "_source": {"Author": "Someone Else"},
                                },
                            ],
                        }
                    }
                )
            }
        name = url.split("/")[-2]
        assert name != "old"
        info = {"name": name, "author": "Someone Else", "project_urls": {}}
        if name == "coauthored":
            info["author_email"] = "Gaurav Sood <contact@gsood.com>"
        return {"body": json.dumps({"info": info})}


def test_discovery_adds_verified_packages_and_keeps_history():
    old = [
        Package("pypi", "old"),
        Package("pypi", "deleted"),
        Package("cran", "archived"),
    ]
    packages, audit = discover(old, CONFIG, DiscoveryClient(), sleep=lambda _: None)
    assert {(p.ecosystem, p.name) for p in packages} == {
        ("pypi", "old"),
        ("pypi", "deleted"),
        ("cran", "archived"),
        ("pypi", "own-new"),
        ("pypi", "shared"),
        ("pypi", "coauthored"),
        ("cran", "newR"),
    }
    assert len(audit["added"]) == 4
    assert {r["name"] for r in audit["rejected"]} == {"unrelated", "falseHit"}


def test_manifest_round_trip(tmp_path):
    packages, _ = discover(
        [Package("pypi", "old")], CONFIG, DiscoveryClient(), sleep=lambda _: None
    )
    path = tmp_path / "packages.toml"
    path.write_text(manifest_text(packages))
    assert load_packages(path) == packages


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Gaurav   SOOD [aut]", True),
        ("Name <contact@gsood.com>", True),
        ("Gaurav Soodish", False),
        ("notcontact@gsood.com", False),
        ("Another Sood", False),
    ],
)
def test_identity_boundaries(text, expected):
    assert bool(matches_identity(text, CONFIG)) is expected


def test_cran_pagination():
    class Pages:
        def fetch(self, url, **kwargs):
            offset = int(url.split("from=")[1].split("&")[0])
            count = 100 if offset == 0 else 1
            hits = [
                {"_id": str(i), "_source": {}} for i in range(offset, offset + count)
            ]
            return {
                "body": json.dumps(
                    {"hits": {"total": {"value": 101, "relation": "eq"}, "hits": hits}}
                )
            }

    assert len(list(cran_records(Pages(), "Gaurav Sood"))) == 101


@pytest.mark.parametrize(
    "result",
    [
        {"timed_out": True},
        {"_shards": {"failed": 1}},
        {"hits": {"total": 5, "hits": []}},
        {"hits": {"total": {"value": 5, "relation": "gte"}, "hits": []}},
    ],
)
def test_incomplete_cran_search_is_rejected(result):
    class Bad:
        def fetch(self, *args, **kwargs):
            return {"body": json.dumps(result)}

    with pytest.raises(ValueError):
        list(cran_records(Bad(), "Gaurav Sood"))


def test_rpc_rejects_bad_rows():
    class Bad:
        def fetch(self, *args, **kwargs):
            return {
                "body": xmlrpc.client.dumps(
                    ([["Owner", "../oops"]],), methodresponse=True
                )
            }

    with pytest.raises(ValueError):
        pypi_names(Bad(), "soodoku")


def test_config_and_shipped_manifest(tmp_path):
    path = tmp_path / "discovery.toml"
    path.write_text('author = "Gaurav Sood"')
    with pytest.raises(ValueError):
        read_config(path)


def report(complete=True):
    return {
        "complete": complete,
        "total_downloads": 1234567 if complete else None,
        "observed_downloads": 1234567,
        "packages": [],
        "subtotals": {},
        "finished_at": "2026-11-06T00:00:00Z",
        "discovery": {"complete": True, "added": []},
    }


@pytest.mark.parametrize("failure", ["discovery", "counts", None])
def test_refresh_only_publishes_complete_runs(tmp_path, monkeypatch, failure):
    manifest = tmp_path / "packages.toml"
    manifest.write_text('[[packages]]\necosystem="pypi"\nname="old"\n')
    original = manifest.read_bytes()
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "badge.json").write_text("previous badge")
    (reports / "latest.json").write_text("previous report")
    new = Package("pypi", "new")

    def discovery(packages, config, client):
        if failure == "discovery":
            raise FetchError("source offline")
        return [*packages, new], {"complete": True, "added": [asdict(new)]}

    monkeypatch.setattr(refresh, "read_config", lambda _: CONFIG)
    monkeypatch.setattr(refresh, "discover", discovery)
    monkeypatch.setattr(refresh, "collect", lambda *args: report(failure != "counts"))
    config = tmp_path / "discovery.toml"
    config.write_text("test")
    code = refresh.main(
        [
            "--manifest",
            str(manifest),
            "--config",
            str(config),
            "--reports",
            str(reports),
        ]
    )
    assert code == (1 if failure else 0)
    if failure:
        assert (reports / "badge.json").read_text() == "previous badge"
        assert (reports / "latest.json").read_text() == "previous report"
        assert manifest.read_bytes() == original
    else:
        assert json.loads((reports / "badge.json").read_text())["message"] == "1.2M"
        assert len(load_packages(manifest)) == 2
        latest = json.loads((reports / "latest.json").read_text())
        assert (
            latest["manifest_sha256"]
            == hashlib.sha256(manifest.read_bytes()).hexdigest()
        )


def test_post_requests_have_distinct_snapshots(tmp_path):
    import io

    class Response(io.BytesIO):
        headers = {}

    requests = []

    def opener(request, timeout):
        requests.append(request)
        return Response(b"<response/>")

    client = Client(tmp_path, opener=opener)
    client.fetch(PYPI_RPC, data=b"one", content_type="text/xml")
    client.fetch(PYPI_RPC, data=b"two", content_type="text/xml")
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert requests[0].get_method() == "POST"
    assert requests[0].get_header("Content-type") == "text/xml"


@pytest.mark.parametrize(
    "value, text",
    [
        (0, "0"),
        (999, "999"),
        (1_000, "1.0K"),
        (9_999, "9.9K"),
        (121_372, "121K"),
        (999_999, "999K"),
        (2_185_140, "2.1M"),
        (2_199_999, "2.1M"),
        (12_345_678, "12M"),
        (3_400_000_000, "3.4B"),
    ],
)
def test_badge_value_is_truncated_never_rounded_up(value, text):
    assert refresh.compact(value) == text

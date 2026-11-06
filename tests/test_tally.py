import csv
import hashlib
import io
import json
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from package_tally import cli
from package_tally.core import (
    CRAN_START,
    CRANLOGS,
    Client,
    FetchError,
    Package,
    collect,
    load_packages,
    parse_cran,
    parse_pepy,
)


def badge(value):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg"><g>'
        "<text>downloads</text><text>downloads</text>"
        f"<text>{value}</text><text>{value}</text></g></svg>"
    )


def manifest(tmp_path, text):
    path = tmp_path / "input.toml"
    path.write_text(text)
    return path


def test_manifest_normalizes_names_and_preserves_cran_case(tmp_path):
    path = manifest(
        tmp_path,
        """
[[packages]]
ecosystem = "pypi"
name = "Some_Package.Name"
[[packages]]
ecosystem = "cran"
name = "abbyyR"
""",
    )
    assert [(p.ecosystem, p.name) for p in load_packages(path)] == [
        ("cran", "abbyyR"),
        ("pypi", "some-package-name"),
    ]


def test_manifest_rejects_alias_duplicates(tmp_path):
    path = manifest(
        tmp_path,
        """
[[packages]]
ecosystem = "pypi"
name = "Some_Package"
[[packages]]
ecosystem = "pypi"
name = "some.package"
""",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_packages(path)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "packages = []",
        '[[packages]]\necosystem="npm"\nname="foo"',
        '[[packages]]\necosystem="pypi"\nname="../foo"',
        '[[packages]]\necosystem="pypi"\nname="foo,bar"',
        '[[packages]]\necosystem="cran"\nname="R"',
        '[[packages]]\necosystem="cran"\nname="some_package"',
        '[[packages]]\necosystem="pypi"\nname="foo"\nnotes="typo"',
        '[[packages]]\necosystem="pypi"\nname="foo"\nnote=3',
    ],
)
def test_manifest_rejects_invalid_input(tmp_path, text):
    with pytest.raises(ValueError):
        load_packages(manifest(tmp_path, text))


@pytest.mark.parametrize("value", ["0", "737083", "999999999999999999"])
def test_pepy_exact_integer(value):
    assert parse_pepy(badge(value)) == int(value)


@pytest.mark.parametrize("value", ["1.2M", "n/a", "-1", "12.0", "1,000", ""])
def test_pepy_rejects_inexact_or_missing_counts(value):
    with pytest.raises(ValueError):
        parse_pepy(badge(value))


def test_pepy_rejects_unexpected_content():
    with pytest.raises(ValueError):
        parse_pepy("<html>Cloudflare</html>")
    with pytest.raises(ValueError):
        parse_pepy(badge("32").replace("downloads", "downloads/month"))


def cran_body(**updates):
    return json.dumps(
        [
            {
                "package": "tuber",
                "start": str(CRAN_START),
                "end": "2026-11-04",
                "downloads": 1234,
                **updates,
            }
        ]
    )


def test_cran_exact_integer():
    assert parse_cran(cran_body(), "tuber", CRAN_START, date(2026, 11, 4)) == 1234
    assert (
        parse_cran(cran_body(downloads=0), "tuber", CRAN_START, date(2026, 11, 4)) == 0
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"package": "other"},
        {"start": "2020-01-01"},
        {"end": "2026-11-03"},
        {"downloads": -1},
        {"downloads": True},
        {"downloads": "123"},
        {"downloads": None},
        {"downloads": 1.5},
    ],
)
def test_cran_rejects_invalid_responses(updates):
    with pytest.raises(ValueError):
        parse_cran(cran_body(**updates), "tuber", CRAN_START, date(2026, 11, 4))


@pytest.mark.parametrize("body", ["[]", "{}", "[null]", "[{}, {}]"])
def test_cran_rejects_wrong_response_shape(body):
    with pytest.raises(ValueError):
        parse_cran(body, "tuber", CRAN_START, date(2026, 11, 4))


class Response(io.BytesIO):
    headers = {"Content-Type": "image/svg+xml", "Date": "Fri, 06 Nov 2026"}


def test_client_retries_and_preserves_response(tmp_path):
    attempts = []
    sleeps = []

    def opener(request, timeout):
        attempts.append(request)
        assert timeout == 45
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "", {"Retry-After": "3"}, None
            )
        return Response(badge("123").encode())

    client = Client(tmp_path, opener=opener, sleep=sleeps.append)
    record = client.fetch("https://example.test/count")
    assert sleeps == [3]
    assert len(attempts) == 2
    assert record["sha256"] == hashlib.sha256(record["body"].encode()).hexdigest()
    assert json.loads(next(tmp_path.glob("*.json")).read_text()) == record
    assert attempts[0].get_header("User-agent").startswith("package-tally/")


@pytest.mark.parametrize(
    "code,retry,calls", [(404, None, 1), (429, "3600", 1), (503, None, 3)]
)
def test_client_bounds_retries(tmp_path, code, retry, calls):
    attempts = []

    def opener(request, timeout):
        attempts.append(request)
        raise urllib.error.HTTPError(
            request.full_url, code, "", {"Retry-After": retry or ""}, None
        )

    with pytest.raises(FetchError):
        Client(tmp_path, opener=opener, sleep=lambda _: None).fetch(
            "https://example.test"
        )
    assert len(attempts) == calls


def test_client_retries_connection_errors(tmp_path):
    attempts = []

    def opener(request, timeout):
        attempts.append(request)
        raise urllib.error.URLError("offline")

    with pytest.raises(FetchError):
        Client(tmp_path, opener=opener, sleep=lambda _: None).fetch(
            "https://example.test"
        )
    assert len(attempts) == 3


class FakeClient:
    def __init__(self, fail=False, latest_fail=False):
        self.fail = fail
        self.latest_fail = latest_fail
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        if self.fail and "/personalized-badge/" in url:
            raise FetchError("HTTP 404")
        if url == CRANLOGS + "last-day":
            if self.latest_fail:
                raise FetchError("offline")
            body = json.dumps([{"start": "2026-11-04", "end": "2026-11-04"}])
        elif "/personalized-badge/" in url:
            assert "period=TOTAL&units=NONE&left_text=downloads" in url
            body = badge("2000")
        else:
            assert "2012-10-01:2026-11-04/tuber" in url
            body = cran_body()
        return {
            "body": body,
            "fetched_at": "2026-11-06T00:00:00+00:00",
            "sha256": "test",
        }


def test_collect_subtotals_and_service_cutoff():
    report = collect(
        [Package("pypi", "ethnicolr"), Package("cran", "tuber")], FakeClient()
    )
    assert report["total_downloads"] == 3234
    assert report["subtotals"]["pypi"]["observed_downloads"] == 2000
    assert report["subtotals"]["cran"]["observed_downloads"] == 1234
    assert report["packages"][0]["coverage_start"] is None
    assert report["packages"][1]["coverage_end"] == "2026-11-04"


def test_missing_counts_do_not_become_zero():
    report = collect(
        [Package("pypi", "ethnicolr"), Package("cran", "tuber")], FakeClient(fail=True)
    )
    assert report["total_downloads"] is None
    assert report["observed_downloads"] == 1234
    assert report["complete"] is False
    assert report["packages"][0]["downloads"] is None
    assert "Partial subtotal" in cli.markdown(report)
    assert "UNAVAILABLE" in cli.markdown(report)


def test_failed_cran_cutoff_does_not_block_python():
    client = FakeClient(latest_fail=True)
    report = collect([Package("pypi", "ethnicolr"), Package("cran", "tuber")], client)
    assert report["observed_downloads"] == 2000
    assert report["packages"][1]["url"] is None
    assert len(client.urls) == 2


def test_python_only_does_not_query_cran():
    client = FakeClient()
    assert collect([Package("pypi", "ethnicolr")], client)["complete"]
    assert len(client.urls) == 1


@pytest.mark.parametrize("fail,exit_code", [(False, 0), (True, 1)])
def test_cli_writes_consistent_reports(tmp_path, monkeypatch, fail, exit_code):
    monkeypatch.setattr(cli, "Client", lambda _: FakeClient(fail=fail))
    path = manifest(tmp_path, '[[packages]]\necosystem="pypi"\nname="ethnicolr"\n')
    output = tmp_path / "report"
    assert cli.main([str(path), "--output", str(output)]) == exit_code
    report = json.loads((output / "summary.json").read_text())
    with (output / "packages.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["downloads"] == ("" if fail else "2000")
    assert report["total_downloads"] == (None if fail else 2000)
    assert (output / "packages.toml").read_bytes() == path.read_bytes()
    assert report["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(SystemExit) as exc:
        cli.main([str(path), "--output", str(output)])
    assert exc.value.code == 2


def test_shipped_manifest_is_valid():
    packages = load_packages(Path(__file__).parents[1] / "packages.toml")
    assert {p.ecosystem for p in packages} == {"pypi", "cran"}


@pytest.mark.parametrize("body", ["[null]", "[1]", "[{}]", "[]", "{}"])
def test_malformed_cran_cutoff_is_reported_as_unavailable(body):
    class MalformedClient(FakeClient):
        def fetch(self, url):
            if url == CRANLOGS + "last-day":
                return {"body": body}
            return super().fetch(url)

    report = collect(
        [Package("pypi", "ethnicolr"), Package("cran", "tuber")], MalformedClient()
    )
    assert report["observed_downloads"] == 2000
    assert report["complete"] is False
    assert report["packages"][1]["status"] == "error"

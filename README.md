# package-tally

[![Package downloads](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fgojiplus%2Fpackage-tally%2Fmain%2Freports%2Fbadge.json)](reports/latest.md)

Count downloads across a list of Python and R packages. Produces per-package
counts, ecosystem subtotals, and a combined tally, with the original responses
saved alongside the report. The included inventory covers Gaurav Sood's published
and historically published packages; see [the inventory audit](inventory/README.md).

[View the latest tally](reports/latest.md), or browse the dated snapshots in
[reports](reports). The badge always represents the latest successful refresh.

## Run

Requires Python 3.11 or newer. No runtime dependencies or API keys.

```sh
python -m pip install -e .
package-tally packages.toml
```

Each run creates a new timestamped directory under `reports/` containing
`summary.md`, `summary.json`, `packages.csv`, a copy of the input manifest, and
`raw/` response snapshots. To select the destination:

```sh
package-tally packages.toml --output reports/my-snapshot
```

The destination must not exist, preventing accidental replacement of a previous
snapshot. A failed lookup stays unavailable, never zero. The command still writes
the partial report but exits with status 1; its JSON `total_downloads` is null and
`observed_downloads` is the subtotal of successful lookups. Invalid input exits 2.

## Weekly updates and package discovery

The **Tally** GitHub Actions workflow runs every Monday at **08:17 UTC**, or on
demand using **Actions → Tally → Run workflow**. It discovers new packages,
collects totals, and commits the updated inventory, dated snapshot, and badge to
this repository. It needs no credentials beyond GitHub's built-in workflow token.

To switch to monthly runs, replace the cron expression in
[the workflow](.github/workflows/tally.yml) with `17 8 1 * *` (the first day of
each month at 08:17 UTC). GitHub may delay scheduled jobs.

Run the same refresh locally with:

```sh
package-tally-refresh
```

[discovery.toml](discovery.toml) defines the identity and PyPI accounts to check:

- New packages owned or maintained by `soodoku` are included.
- Packages from the configured collaborator accounts (`suriyan`, `rajashekar`)
  are included only when PyPI author/maintainer metadata matches the configured
  name or email addresses.
- CRAN's author/maintainer search supplies additional R packages, with identity
  checks on each result.
- Existing curated entries, including archived and deleted packages, are kept.
  Discovery adds entries; it does not silently delete package history.

Extend the collaborator list if you release through another account. Packages
not reachable through these accounts or the CRAN author search can be added
manually to `packages.toml`. No heuristic can guarantee exhaustive discovery.

Discovery uses PyPI's documented `user_packages` XML-RPC method, which is
**deprecated but still available**; PyPI does not offer an equivalent JSON
ownership lookup. If it is removed or any source fails, the refresh exits with an
error and preserves the last successful public count. Each dated snapshot saves
the discovery requests/responses and the additions/rejections in its summary.
Failed workflow runs still upload their reports for diagnosis.

`reports/latest.md`, `latest.json`, `latest.csv`, and `badge.json` update only after
both discovery and every download lookup succeed. Dated snapshots retain the raw
responses and the exact inventory used. A larger inventory may increase the
cumulative total by a new package's entire historical count; differences between
snapshots are not necessarily downloads during the intervening week.

## Your own packages

Edit `packages.toml`, or supply another TOML file:

```toml
[[packages]]
ecosystem = "pypi"
name = "ethnicolr"

[[packages]]
ecosystem = "cran"
name = "tuber"
```

Optional fields are `repository`, `evidence`, and `note`. PyPI names are normalized
according to PEP 503; duplicate names within an ecosystem are rejected. CRAN names
retain their case. The list is explicit: verify authorship before adding names,
since a local project can share its name with an unrelated registry package.

## What is counted

- **Python:** [Pepy's documented public personalized badge](https://pepy.tech/pepy-api),
  with `period=TOTAL&units=NONE`. The SVG contains an unrounded integer. Pepy does
  not supply exact start/end dates through this endpoint, and badges can be cached
  for 12 hours. The program rejects abbreviated values and error badges.
- **R:** [CRAN logs](https://github.com/r-hub/cranlogs.app#web-api-docs), using the
  RStudio mirror from October 1, 2012 through the service's latest complete day.
  This includes archived packages when their historical counters are available.
  These are one mirror's counts, not downloads across every CRAN mirror.

The combined number sums these source counters across packages and versions. It
is not a count of people, unique installations, or common-window downloads. Old
and new package names count separately when they have separate registry counters.
Nothing extrapolates missing history or rescales CRAN to all mirrors. A zero from
CRAN logs does not prove that a package exists; registry membership is established
by the inventory audit, not the download endpoint.

Each response snapshot records its URL, retrieval time, SHA-256, server date,
cache age when supplied, and body. The summary also records the manifest hash.
Transient connection errors and HTTP 429/5xx responses receive bounded retries.

## Development

```sh
python -m pip install -e '.[dev]'
make ci
make ci-docker
```

`make ci` runs Black, isort, Flake8, pytest, and a package build. Docker uses the
standard `python:3.14-slim` image. CI runs the same checks on Python 3.11 and 3.14.
The **Tally** workflow fetches live counts and uploads reports as an artifact,
including partial reports if a source is unavailable.

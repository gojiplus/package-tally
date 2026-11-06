# package-tally

Count downloads across a list of Python and R packages. Produces per-package
counts, ecosystem subtotals, and a combined tally, with the original responses
saved alongside the report. The included inventory covers Gaurav Sood's published
and historically published packages; see [the inventory audit](inventory/README.md).

[View the initial tally](reports/2026-11-06/summary.md): **2,181,721 downloads**
across 64 package names, retrieved November 6, 2026 UTC.

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
The manually triggered **Tally** workflow fetches live counts and uploads the
reports as an artifact, including partial reports if a source is unavailable.

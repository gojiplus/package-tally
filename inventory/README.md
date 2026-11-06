# Inventory audit

Verified November 6, 2026 UTC (November 5 in California): **55 Python package names
and 9 R package names**. The editable list is [packages.toml](../packages.toml).
This counts authored, coauthored, and maintained packages; it does not claim sole
authorship or allocate downloads between collaborators.

## Discovery and inclusion

1. Read package names from top-level `pyproject.toml`, `setup.py`, and `DESCRIPTION`
   files in the local GitHub checkouts, including appeler, finite-sample,
   geosensing, gojiplus, in-rolls, notnews, outside-edge, recite, soodoku, themains,
   and cloudyr. Local metadata supplied candidates, not proof of publication.
2. Compared candidates with the public [PyPI JSON API](https://docs.pypi.org/api/json/).
   Included records whose author or maintainer fields identify Gaurav Sood and
   checked their repository links. See [registry evidence](pypi-evidence.json).
3. Cross-checked the [soodoku profile](https://pypi.org/user/soodoku/) (41 projects)
   and [suriyan profile](https://pypi.org/user/suriyan/). This found `repaper`,
   `kahipwrapper`, `savitr`, and the historical `pydomains` name. `repaper` and
   `savitr` are included on the explicit basis of the soodoku maintainer profile.
4. Searched the [CRAN database](https://crandb.r-pkg.org/-/all) for author and
   maintainer matches across versions. This snapshot contained 25,648 active
   packages and no archived records. The five matching active packages are
   `guess`, `rdomains`, `tuber`, `tubern`, and `virustotal`;
   [extracted evidence](cran-evidence.json) records their authors and URLs.
5. Checked local R package names against CRAN's source archives, then searched
   archived GitHub repositories in soodoku, gojiplus, themains, appeler, notnews,
   and finite-sample. This added `aws.alexa`, `abbyyR`, `captr`, and `clarifai`.
   Their CRAN removal pages and GitHub DESCRIPTION files confirm the identity.
   The archived-repository search also recovered `pydomains`.

## Historical names

- [pydomains](https://github.com/themains/pydomains/blob/master/setup.py) names
  Suriyan Laohaprapanon and Gaurav Sood as authors. Its PyPI JSON endpoint returns
  404, but Pepy still serves its historical total. `piedomains` is a distinct
  distribution; both counters are included exactly once.
- [aws.alexa](https://cran.r-project.org/web/packages/aws.alexa/index.html),
  [abbyyR](https://cran.r-project.org/web/packages/abbyyR/index.html),
  [captr](https://cran.r-project.org/web/packages/captr/index.html), and
  [clarifai](https://cran.r-project.org/web/packages/clarifai/index.html) are
  archived on CRAN. Their old downloads remain part of the tally.

## Exclusions and name collisions

Local checkouts alone would have overcounted substantially. The audit excludes
upstream packages such as `scikit-learn`, `linearmodels`, `DoubleML`, `pylint`,
`yamllint`, `mlsynth`, `maketables`, `Synth`, and `hal9001`. Contributions or a
local fork do not make their entire download history part of this inventory.

Published names `devclean`, `sortition`, `simcheck`, `sourcerer`, `covered`, `dct`,
`replay`, `streetscope`, `carrier-pigeon`, `adjacent`, and `wayback` resolve to
other authors/projects. The generic `act` record provides no matching authorship.
These are excluded. Likewise CRAN's `dann` belongs to Greg McMahan, unlike the
local Trevor Hastie/Gaurav Sood project of that name.

GitHub-only tools and research replication packages without a verified PyPI or
CRAN release are outside these download sources. In particular, `namesexdata`,
`bloomjoin`, and `rd2sphinx` did not have active or archived CRAN entries. No zero
count is fabricated for them. This is a verified inventory from the sources above,
not a guarantee that every historical package on every account has been found.

## Updating

Add a `[[packages]]` entry after verifying the registry name and authorship, with
an `evidence` URL and a note for archived or renamed distributions. Normalize PyPI
aliases into one entry; preserve CRAN capitalization. Re-run `package-tally` to
create a fresh snapshot. Existing reports keep their original manifest and counts.

## Automatic additions after the initial audit

Weekly refreshes use `discovery.toml` and keep the original curated entries.
New entries record discovery evidence in `packages.toml`; each new snapshot's
`summary.json` records added and rejected candidates. The initial evidence files
above remain a record of the November 6 audit, not a manually synchronized index.
See the [refresh documentation](../README.md#weekly-updates-and-package-discovery).

API references: [PyPI ownership lookup](https://dev.pypi.org/api-reference/xml-rpc/#user-packages-user),
[CRAN advanced search](https://r-hub.github.io/pkgsearch/reference/advanced_search.html),
and the [official CRAN search client](https://github.com/r-hub/pkgsearch/blob/main/R/api.R).

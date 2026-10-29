# khmd 0.0.5 — private code repository

Jinhyeok Jang <jedjang1@gmail.com> · author and maintainer (`aut`, `cre`).

**Software: MIT. Author-held aggregate-data and independent-document contributions:
CC BY 4.0.** Original public data and third-party components retain their own terms
and attribution. These licenses permit commercial as well as noncommercial reuse
within their respective grants; the author's CC BY4.0 is not a relicensing of
government raw data. Earlier noncommercial proposals are not applied here.
See [LICENSE.txt](LICENSE.txt), [LICENSE_SCOPE.csv](LICENSE_SCOPE.csv) and
[DATA_SOURCES.txt](DATA_SOURCES.txt).

## Current distribution status

This [GitHub repository](https://github.com/jedjang1/khmd) remains **Private**.
The user has replaced the aggregate ZIP in the existing Zenodo draft, selected
CC BY4.0 and completed **Save draft**. Zenodo is **not published**. DOI
`10.5281/zenodo.23762471` is reserved; it is not presented as a published record
or working public download. This status is user-reported; this sync does not
inspect or modify Zenodo. No public transition or Release/tag is performed.

## What is provided

- `code/khmd/` and `code/khmd_0.0.5.tar.gz`: unchanged validated R source/archive.
- `construction/`: both basev0_1 and connectionv0_2 and required internal modules.
- `example_data/`: fabricated examples, not observed transactions or parcels.
- `tools/`: existing query, integrity and synthetic regeneration tools.
- Separate Zenodo ZIP: grid count/price panels, query-region quality and provenance.
  The actual `data/` files are **absent from this checkout**.

No raw CSVs, cadastral geometry, real PNU/representative-point datasets,
individual-observation stores, Windows binary ZIPs or internal logs are added.
Basic panel queries need only the aggregate ZIP. Individual-observation functions
require separately prepared stores that are not included in that ZIP.

## Install and query

[README.txt](README.txt) contains the existing source-install instructions and
actual function examples. Dependencies (including `digest`) are external packages,
not bundled/relicensed under the author's MIT notice. With khmd0.0.5 already
installed and the separate ZIP extracted with its relative paths intact:

```r
library(khmd)
stopifnot(as.character(packageVersion("khmd")) == "0.0.5")
B <- normalizePath("path/to/extracted-data", winslash="/", mustWork=TRUE)
p <- khmd_open_panel(file.path(B,"data/count/release_manifest.json"))
khmd_panel_collect(p,quarter="2025Q1",family="SALE",limit=2)
khmd_panel_quality(p,quarter="2025Q1",family="RENT",limit=2)
q <- khmd_open_price_panel(file.path(B,"data/price/release_manifest.json"))
khmd_price_collect(q,metric="sale_amount_m2",family="SALE",limit=2)
khmd_price_stream(q,function(x){print(x);FALSE},metric="deposit",chunk_size=7L)
```

`library(khmd)` loads code, not the full data release into memory. Keep both
`data/count/release_manifest.json` and `data/price/release_manifest.json` at their
original relative paths. These are reused examples, not a new runtime test.

## Validation and limits

The original khmd0.0.5 source build/install, Windows binary and actual queries
passed. R CMD check on Windows11/R4.5.2 was OK with0ERROR/0WARNING/0NOTE using
`--no-manual --no-build-vignettes`; it was not CRAN or another-OS validation.
The full user check was outside the single-worker guard. Its memory is not
represented by preflight-worker measurements.

The nationwide data construction completed previously. The separate construction
candidate has limited synthetic input-binding, connection, restart and relocation
tests; it has not independently reproduced the nation from a newly supplied
external input set. See `construction/README.txt` and its INPUT_CONTRACTS.

Counts preserve occurrences, not unique transactions; sparse absence is not zero.
RENT ALL overlaps subtypes. Cancellation policy,2026reference parcels and existing
Seoul PILOT_PARTIAL/Cheongju PARTIAL_MATCH findings remain. Population completeness,
historical positions, legal suitability and EPB acceptance are not guaranteed.
Separate database-maker-rights and transaction-guidance interpretation issues
remain as documented; no agency approval or blanket extra-permission requirement.

## Inventories and historical records

`GITHUB_FILES.csv` is the current checkout inventory (excluding itself).
`LICENSE_SCOPE.csv` identifies covered contributions and distribution presence.
`DISTRIBUTION_FILES.csv`, `FILE_INVENTORY.json/.sha256`, `UPLOAD_LIST.csv`,
`SOURCE_MAP.csv` and `metadata/*` retain historical combined-candidate/evidence
records. They neither describe the current GitHub file set nor imply that the
large data files are uploaded here. Root status documents take precedence over
build-time package-internal statements about then-unissued identifiers.
See [Availability](DATA_AND_CODE_AVAILABILITY.txt) and [citation](CITATION.txt).

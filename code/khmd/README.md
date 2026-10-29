# khmd 0.0.5 — local release candidate

Author and maintainer: Jinhyeok Jang <jedjang1@gmail.com>, aut and cre.
Metadata-only release: author, MIT code licence and source attribution updated.
All R functions, exports, statistics and existing tests are unchanged from 0.0.4.
No public repository or DOI is issued. No affiliation or ORCID is asserted.

Project-authored code: MIT + file LICENSE. Data rights are separate; MIT is not
a licence over the transaction or spatial source data or the entire panel bundle.
See inst/DATA_SOURCES.txt for actual source attribution and remaining interpretations.

Requirements: R >=4.2; DBI, RSQLite >=2.2.17, jsonlite, digest; testthat for tests.
No dependencies or data are downloaded automatically. Large data stays outside R's
package installation. The aggregate bundle does not include individual-row stores.

With an installed version 0.0.5 and the candidate data directory B:
```r
library(khmd)
p <- khmd_open_panel(file.path(B,"data/count/release_manifest.json"))
khmd_panel_collect(p, quarter="2025Q1", family="SALE", limit=5)
khmd_panel_quality(p, quarter="2025Q1", family="RENT", limit=3)
q <- khmd_open_price_panel(file.path(B,"data/price/release_manifest.json"))
khmd_price_collect(q, metric="sale_amount_m2", family="SALE", limit=5)
khmd_price_stream(q, function(x) { print(x); FALSE }, metric="deposit", chunk_size=7)
```
Use the bundled guarded example for bounded verification; paths are user arguments.
n_obs counts repeated observation occurrences, not unique transactions. Sparse absent
groups are not zeros. RENT ALL overlaps its subtypes and must not be added to them.
Cancellation-date-displayed sales are retained; nominal descriptive prices are not
quality-adjusted indices. 2026 reference-parcel linkage is not historical validation.
Seoul PILOT_PARTIAL, Cheongju PARTIAL_MATCH and unproven completeness remain.

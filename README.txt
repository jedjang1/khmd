KHMD 0.0.5 / public aggregate dataset v1 — first-user guide

START HERE: README.md and examples/consumer_quickstart.R.
The English README gives complete copyable blocks; the R example runs top-to-bottom.
Neither requires existing R objects or any developer computer path.

1. Install the R package independently of the data.
   R >= 4.2.0; CRAN https://cloud.r-project.org.
   Installation helper: remotes. Actual Imports: DBI, RSQLite >=2.2.17, jsonlite,
   digest. The script installs missing dependencies and, only if khmd is absent:
   remotes::install_github("jedjang1/khmd",
     ref="fc5be58cb39100b5e4bd76bc56294c4feb5fdbd4", subdir="code/khmd",
     upgrade="never", dependencies=NA).
   Normal installed 0.0.5 is reused; another version stops without automatic
   deletion/overwrite. Confirm packageVersion("khmd") == "0.0.5". An in-use or
   skipped installation is not success: start a new R session when needed.

2. Define uppercase B in each new R session:
   B <- file.path(path.expand("~"), "KHMD", "v1")
   B contains data/, not code/ or the package library. To reuse a complete existing
   extraction, set B to that directory instead (e.g. "D:/KHMD/v1").
   The R example accepts B as its first Rscript argument too.
   Public file:
   https://zenodo.org/api/records/23762471/files/khmd_grid_panels_2011_2025_cc_by_4_0.zip/content
   Size: 94,066,474 bytes. SHA256:
   651d8709d9e82750533cb0c9146a3fcd0e33d884343f9d7a889e660b7be71fbe
   Binary download, sufficient timeout, checked temporary-file promotion and
   preserved ZIP paths are in the example. Good extracted data are reused.
   Failed downloads, bad checksums, missing files and overwrite conflicts stop.

3. Use the actual functions in the example:
   khmd_open_panel(..., expected_sha256=...) then khmd_panel_collect(...),
   khmd_open_price_panel(..., expected_sha256=...) then khmd_price_collect(...).
   Count manifest SHA:
   ba46ebc140e1ba396986d0533fb07ec1672a63db64b3a37e985872889fa92cfc
   Price manifest SHA:
   ed557dee0e763b2cca3d055fcdafe1e8417244bc09c50e32f8b6c0d2b40228a1
   First five 2025Q1 SALE grids are reused for total and per-m2 price queries.
   The annual RENT example queries 2025Q1..Q4 for grid1000:1660 and reports
   quarters_present plus the sum of returned occurrences, without new/renewal
   contract classification. Missing quarters are not zero; no rows give NA sum.

TROUBLESHOOTING
object B not found: rerun the B/data block. RSQLite missing: dependency block.
Package in use: fresh R session before necessary installation; never force-delete
a live library. Manifest absent: check B/data/count and B/data/price.
Public 0.0.5 performs full pre/post database integrity checks; price opening and
small queries may take tens of seconds, depending on the machine. No GC candidate
is applied. library(khmd) does not load the complete data into memory.

MEANING AND SCOPE
Prices: nominal10,000 KRW; per-m2 metric:10,000 KRW/m2 per observation first.
n_valid is the metric denominator; q25/median/q75 are exact type-7 quartiles,
returned as character strings to preserve precision. Preserve original strings
if converting a copy to numeric. Counts preserve occurrences, not unique deals.
RENT ALL overlaps subtypes. Sparse absence is not zero; no completeness claim.
Only aggregate panels/quality/provenance are distributed. Raw CSV, parcels,
PNU/representative-point datasets and individual-observation stores are excluded.
Raw-row APIs require separately prepared stores. No contract-type filter is
offered by this public aggregate panel.

VALIDATION AND PUBLICATION
Dataset v1, published2026-10-30: https://zenodo.org/records/23762471
Version DOI: https://doi.org/10.5281/zenodo.23762471
Software0.0.5: https://github.com/jedjang1/khmd
Existing Windows11/R4.5.2 install/check/query success and the48-item consumer
acceptance are prior records, not repeated here. This new example is smoke-tested
in a separate fresh R session with verified installation/public data reuse.
Full user installation/check subprocess trees are outside the single-worker guard.
Existing tools/quickstart.R remains a separate supervised tool, unchanged.
The construction candidate's limited synthetic tests are not independent national
reproduction. 2026 reference parcels do not verify historical positions.
Seoul PILOT_PARTIAL / Cheongju PARTIAL_MATCH and completeness limitations remain.

Jinhyeok Jang / jedjang1@gmail.com / aut,cre.
Own code MIT; author-held aggregate data/independent documents CC BY4.0; upstream
and third-party conditions separate. See LICENSE.txt, DATA_SOURCES.txt,
LICENSE_SCOPE.csv, CITATION.txt and DATA_AND_CODE_AVAILABILITY.txt.
No source-rights interpretation question is resolved by this guide.
GITHUB_FILES.csv is current; older combined inventories and metadata remain
historical. Package0.0.5, data, frozen manifests and guard are unchanged.

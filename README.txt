KHMD 0.0.5 — PRIVATE CODE / SAVED, UNPUBLISHED ZENODO DRAFT

Author and maintainer: Jinhyeok Jang <jedjang1@gmail.com> (aut, cre).
Author-owned software remains MIT. Author-owned aggregate-data compilation and
independent documentation contributions are CC BY 4.0. Third-party and source
terms remain separate (LICENSE.txt, LICENSE_SCOPE.csv, DATA_SOURCES.txt).
Commercial and noncommercial reuse is permitted within these respective grants.
GitHub https://github.com/jedjang1/khmd is Private. Reserved Zenodo DOI
10.5281/zenodo.23762471 is reserved, not an available public record. The user
reports replacement ZIP upload, CC BY4.0 selection and Save draft complete; the
record is still unpublished. This sync does not independently inspect Zenodo.
This candidate uses the unchanged validated 0.0.5, not the NC 0.0.5.9001 branch.
Package-internal build-time statements are retained byte-for-byte; root documents
give the current status. No package-internal file was changed or rebuilt.

THREE SEPARATE COMPONENTS
code/khmd and code/khmd_0.0.5.tar.gz: unchanged validated R package/source archive.
data/: sparse count and price panels, aggregate quality tables, required manifests.
construction/: actual construction-code base v0_1 AND connection overlay v0_2.
example_data/ and tools/make_demo.py: small fabricated example and regeneration.
The data/ subtree is NOT in this GitHub checkout; obtain the separate matching
Zenodo ZIP only with draft access until publication, and supply it locally.
Windows ZIP is deliberately excluded from this first public candidate. The verified
binary remains a local artifact; it was not rebuilt or repackaged for publication.
Original CSVs, parcel data, PNU/representative-point datasets, individual-observation
stores and internal diagnostic logs are not included. Synthetic fixtures are not
source observations and PNU-shaped test strings are not actual cadastral records.

INSTALL THE PACKAGE SEPARATELY FROM DATA
Use an existing local R4.5.2 user library with DBI, RSQLite>=2.2.17, jsonlite, digest
and their dependencies. No dependency binaries or installers are bundled. A source
installation can be run by a user without downloading a package from a repository:

  B <- normalizePath("path/to/public_candidate", winslash="/", mustWork=TRUE)
  L <- normalizePath("path/to/user-library", winslash="/", mustWork=TRUE)
  install.packages(file.path(B,"code/khmd_0.0.5.tar.gz"),repos=NULL,type="source",lib=L)
  .libPaths(c(L,.Library));library(khmd,lib.loc=L)
  stopifnot(as.character(getNamespaceVersion("khmd"))=="0.0.5")

Source build/install/check previously passed in an ordinary-user Windows session.
R CMD check options were --no-manual --no-build-vignettes, with 0 ERROR/0 WARNING/
0 NOTE. This was not CRAN submission checking or testing another OS. Source install
and the full user check were outside the single-worker construction guard because
they use child processes. We did not rerun them or claim guard coverage for them.
The included guarded query/demo tool keeps the existing single-worker child policy;
it no longer offers the excluded binary-install mode. No guard override is provided.

DATA LOCATION AND REAL QUERIES
library(khmd) loads code, not the complete data release into memory. Place data/
beside the other folders in a separate local working copy as below; metadata
paths inside its manifests are relative. Do not commit data/ into this repository.
Manifest opening verifies bound data blocks without loading all rows into memory.

  p <- khmd_open_panel(file.path(B,"data/count/release_manifest.json"))
  khmd_panel_metadata(p)
  n <- khmd_panel_collect(p,quarter="2025Q1",family="SALE",limit=2)
  q <- khmd_panel_quality(p,quarter="2025Q1",family="RENT",limit=2)
  grid <- n$grid_id[1]
  prices <- khmd_open_price_panel(file.path(B,"data/price/release_manifest.json"))
  khmd_price_collect(prices,grid_id=grid,quarter="2025Q1",family="SALE",
      metric=c("sale_amount","sale_amount_m2"),limit=2)
  khmd_price_collect(prices,quarter="2025Q1",family="RENT",rent_subtype="ALL",
      metric=c("deposit","monthly_rent"),limit=4)
  khmd_price_quality(prices,family="RENT",rent_subtype=c("ALL","JEONSE","MONTHLY_RENT","UNKNOWN"))
  khmd_price_stream(prices,function(x){write.csv(x,"price_chunk.csv",row.names=FALSE);FALSE},
      quarter="2025Q1",family="RENT",metric="deposit",rent_subtype="JEONSE",chunk_size=7L)

tools/quickstart.R contains the existing full small-query/stream example. The latest
staging check reused an installed0.0.5 and performed only count/quality/price small
queries. Earlier stream/install/check success is historical evidence, not a new run.
Panel/price/quality queries need only this aggregate bundle. khmd_open_release,
khmd_collect, khmd_stream, khmd_count and raw-field access require a separately
prepared individual-observation CSV release/store, which is NOT included.

DATA INTERPRETATION
20,916,100 selected observation occurrences;20,403,079 assigned and513,021 unassigned.
Count panel:571,310 observed grid-quarter-family groups; quality table:1,920 query-
region-quarter-family rows; price:2,158,314 metric/level statistical rows.
n_obs preserves repeated occurrences; it is not a unique transaction ID/count.
Sparse missing combinations are not automatically zero. Query regions are acquisition
units, not invariant historical jurisdictions. Quality denominators are source-region
denominators, not spatial accuracy or grid completeness. No unlocated row is assigned
to a guessed grid. Nominal10,000KRW units, exact HF7(type7) Q25/median/Q75 and field-
specific valid N/excluded N apply. SALE price/m2 is computed per observation first.
RENT ALL overlaps its JEONSE/MONTHLY_RENT/UNKNOWN subtypes: never sum these levels.
163,177 cancellation-date-displayed SALE observations remain included.458 explicitly
monthly-rent rows with monthly amount0 remain unreclassified. This is descriptive
reported-value statistics, not an official transaction total or quality-adjusted index.
Grid KHMD_UTMK_1KM_V1: EPSG5179, x=easting/y=northing, origin(0,0), floor indices,
projected1000m squares.2026-09-08 reference parcels do not establish historical
contract-time location. Seoul PILOT_PARTIAL/Cheongju PARTIAL_MATCH and unproven
population completeness remain. Small groups are retained; complete anonymization
or inability to reconstruct values is not asserted.

CONSTRUCTION, INPUTS AND VALIDATION
construction/README.txt gives actual module order. INPUT_CONTRACTS.txt and the base
CSV contracts identify separate source CSVs, normalized stores, cadastral/master/
historical code inputs and pinned stage/runtime records. No real external input set
was newly bound here and no independent national replay was performed. This does
not reopen the completed construction tasks. The candidate is not self-contained.
During earlier publication staging, only relocation-affected existing synthetic
tests ran, using copied actual modules. They were not rerun for this document sync.
Loaded-module paths were checked so old experiment code could not supply a PASS.
Unchanged119537664-byte worker supervision and child policy were used for new tests.

FILE SETS AND PUBLICATION
GITHUB_FILES.csv is the current inventory of this checkout, excluding itself to
avoid a circular self-hash. LICENSE_SCOPE.csv is the current file-license map,
including whether a combined-candidate file belongs here or to the separate ZIP.
Inherited DISTRIBUTION_FILES.csv, FILE_INVENTORY.json/.sha256 and UPLOAD_LIST.csv
are preserved HISTORICAL whole-candidate snapshots from the initial preparation;
they are not current GitHub inventories and do not assert data/ is present here.
SOURCE_MAP.csv and metadata/* are preserved historical source/validation evidence.
Their original checks are not new checks of the updated repository documents.
The root README.md/.txt, LICENSE.txt, DATA_SOURCES.txt, CITATION.txt,
DATA_AND_CODE_AVAILABILITY.txt and PUBLICATION_STATUS.txt state the current policy
and status. Package-internal historical documents remain byte-identical to0.0.5.

GitHub supplies code/docs/synthetic examples; the Zenodo draft supplies the
aggregate-data ZIP. The user completed replacement upload, CC BY4.0 selection and
Save draft; it is not published. Reserved DOI10.5281/zenodo.23762471 is not a
public download. This documentation commit does not alter Zenodo, make GitHub
Public, issue a Release/tag or resolve the two source-rights interpretations.

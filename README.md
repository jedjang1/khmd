# khmd: start with the public package and data

**Install the R package from GitHub; download the aggregate data separately from
Zenodo.** You do not need a developer folder, saved R objects, or the original
transaction/parcel data to query these panels. `library(khmd)` loads code, not
the full data release into memory.

- R package: **khmd 0.0.5**, R >= 4.2.0.
- Dataset: **v1**, published **2026-10-30** on [Zenodo](https://zenodo.org/records/23762471).
- Dataset version DOI: [10.5281/zenodo.23762471](https://doi.org/10.5281/zenodo.23762471).
- Author/maintainer: Jinhyeok Jang <jedjang1@gmail.com> (`aut`, `cre`).

Run the blocks below in order, preferably in a new R session. The complete,
equivalent script is [examples/consumer_quickstart.R](examples/consumer_quickstart.R).
It has no dependency on `tools/quickstart.R`, which is a separate supervised
validation tool. You may download the example file and run it top-to-bottom;
cloning this repository is not required for package installation.

## 1. Install missing dependencies and khmd

The package Imports are DBI, RSQLite (>= 2.2.17), jsonlite and digest. `remotes`
is needed for GitHub installation. Missing packages are obtained from
https://cloud.r-project.org; no dependency code is bundled or relicensed here.
The pinned commit contains the validated 0.0.5 package even as these root docs
evolve. A normal installed 0.0.5 is reused. A different installed/loaded version
causes a clear stop, not automatic deletion, forced replacement or false success.

```r
options(repos = c(CRAN = "https://cloud.r-project.org"),
        timeout = max(600, getOption("timeout", 60)))
khmd_ref <- "fc5be58cb39100b5e4bd76bc56294c4feb5fdbd4"
if ("khmd" %in% loadedNamespaces() &&
    as.character(getNamespaceVersion("khmd")) != "0.0.5") {
  stop("Another khmd version is loaded. Start a new R session; no library was changed.")
}
installed_khmd <- find.package("khmd", quiet = TRUE)
if (length(installed_khmd) && as.character(packageVersion("khmd")) != "0.0.5") {
  stop("Another khmd version is installed. Use a separate user library in a new R session; this example will not overwrite it.")
}
required <- c("remotes", "DBI", "RSQLite", "jsonlite", "digest")
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) || !length(installed_khmd)) {
  # A writable user library; no administrator access or global R settings needed.
  user_lib <- Sys.getenv("R_LIBS_USER")
  if (!nzchar(user_lib)) user_lib <- file.path(path.expand("~"), "R", "khmd-library")
  user_lib <- path.expand(strsplit(user_lib, .Platform$path.sep, fixed = TRUE)[[1]][1])
  dir.create(user_lib, recursive = TRUE, showWarnings = FALSE)
  .libPaths(c(user_lib, .libPaths()))
  if (length(missing)) install.packages(missing, lib = user_lib)
}
if (!all(vapply(required, requireNamespace, logical(1), quietly = TRUE))) {
  stop("Required dependency installation failed. Check the install log, especially RSQLite.")
}
if (packageVersion("RSQLite") < "2.2.17") {
  stop("RSQLite >= 2.2.17 is required. Update it in a new R session before continuing.")
}
if (!length(installed_khmd)) {
  remotes::install_github("jedjang1/khmd", ref = khmd_ref, subdir = "code/khmd",
                         upgrade = "never", dependencies = NA, lib = user_lib,
                         build_vignettes = FALSE, build_manual = FALSE)
  if (!length(find.package("khmd", quiet = TRUE))) {
    stop("khmd was not installed. An in-use package or failed installation is not success.")
  }
  if (!identical(packageDescription("khmd")$RemoteSha, khmd_ref)) {
    stop("The new installation does not identify the requested GitHub commit.")
  }
} else {
  message("Reusing installed khmd 0.0.5; no reinstallation requested.")
}
library(khmd)
stopifnot(as.character(packageVersion("khmd")) == "0.0.5",
          as.character(getNamespaceVersion("khmd")) == "0.0.5")
print(packageVersion("khmd"))

```

## 2. Prepare the data and define uppercase `B`

**`B` is the top-level extraction folder that contains `data/`. It is not an R
object loaded by the package, the package library, or the GitHub code folder.**
Define it again in each new R session. Normal extracted data are reused and are
not downloaded again. To use a folder you already prepared, change the first line
below to, for example, `B <- "D:/KHMD/v1"` (use your actual extraction root).

The [public ZIP](https://zenodo.org/api/records/23762471/files/khmd_grid_panels_2011_2025_cc_by_4_0.zip/content)
is **94,066,474 bytes**, SHA-256
`651d8709d9e82750533cb0c9146a3fcd0e33d884343f9d7a889e660b7be71fbe`.
The code uses binary download, a 600-second-or-longer timeout, a temporary `.part`
file, size/SHA verification before cache promotion, and preserved ZIP paths.
Incomplete extraction, a bad checksum or a conflicting destination stops clearly;
no existing data are silently overwritten. A failed `.part` is not a valid cache.

Expected layout (code may live somewhere entirely different):

```text
B/
  data/count/release_manifest.json
  data/count/panel.sqlite
  data/price/release_manifest.json
  data/price/price.sqlite
  data/provenance/...
  data/quality/...
```

```r
B <- file.path(path.expand("~"), "KHMD", "v1")
# Edit B above to reuse an existing extraction. Rscript users may supply it as
# the first argument, e.g. Rscript consumer_quickstart.R "/path/to/KHMD/v1".
if (!interactive()) {
  data_args <- commandArgs(trailingOnly = TRUE)
  if (length(data_args)) B <- data_args[1]
}
count_sha <- "ba46ebc140e1ba396986d0533fb07ec1672a63db64b3a37e985872889fa92cfc"
price_sha <- "ed557dee0e763b2cca3d055fcdafe1e8417244bc09c50e32f8b6c0d2b40228a1"
zip_sha <- "651d8709d9e82750533cb0c9146a3fcd0e33d884343f9d7a889e660b7be71fbe"
zip_url <- "https://zenodo.org/api/records/23762471/files/khmd_grid_panels_2011_2025_cc_by_4_0.zip/content"
required_files <- c("data/count/release_manifest.json", "data/count/panel.sqlite",
                    "data/price/release_manifest.json", "data/price/price.sqlite",
                    "data/provenance/source_release.json", "data/provenance/spatial_manifest.json")
present <- file.exists(file.path(B, required_files))
if (any(present) && !all(present)) {
  stop("Incomplete data folder B. Missing: ", paste(required_files[!present], collapse = ", "),
       ". Use a complete extraction or a new empty B; existing files will not be overwritten.")
}
if (!all(present)) {
  dir.create(B, recursive = TRUE, showWarnings = FALSE)
  zip_path <- file.path(B, "khmd_grid_panels_2011_2025_cc_by_4_0.zip")
  valid_zip <- function(path) {
    file.exists(path) && isTRUE(file.info(path)$size == 94066474) &&
      identical(digest::digest(file = path, algo = "sha256", serialize = FALSE), zip_sha)
  }
  if (file.exists(zip_path) && !valid_zip(zip_path)) {
    stop("Existing ZIP has the wrong size or SHA-256: ", zip_path,
         ". It was not accepted or replaced. Inspect it or choose a new B.")
  }
  if (!file.exists(zip_path)) {
    part <- tempfile("khmd-download-", tmpdir = B, fileext = ".part")
    status <- tryCatch(download.file(zip_url, part, mode = "wb", quiet = FALSE),
                       error = function(e) stop("Download failed: ", conditionMessage(e),
                                                ". Partial file, if any: ", part))
    if (status != 0 || !valid_zip(part)) {
      stop("Download failed or ZIP size/SHA-256 mismatch. Not promoted to cache: ", part)
    }
    if (!file.rename(part, zip_path)) stop("Could not finalize verified ZIP: ", part)
  }
  members <- unzip(zip_path, list = TRUE)$Name
  normalized_members <- gsub("\\", "/", members, fixed = TRUE)
  unsafe <- startsWith(normalized_members, "/") | grepl("^[A-Za-z]:", normalized_members) |
    vapply(strsplit(normalized_members, "/", fixed = TRUE), function(x) any(x == ".."), logical(1))
  if (any(unsafe)) stop("Unsafe ZIP member path; extraction refused.")
  if (any(file.exists(file.path(B, members)))) {
    stop("Extraction would overwrite existing files. Use a new empty B; original files are preserved.")
  }
  withCallingHandlers(unzip(zip_path, exdir = B),
                      warning = function(w) stop("Extraction warning: ", conditionMessage(w)))
}
missing_files <- required_files[!file.exists(file.path(B, required_files))]
if (length(missing_files)) stop("Missing required files below B: ", paste(missing_files, collapse = ", "))
B <- normalizePath(B, winslash = "/", mustWork = TRUE)
if (!identical(digest::digest(file = file.path(B, required_files[1]), algo = "sha256", serialize = FALSE), count_sha)) {
  stop("Count manifest SHA-256 mismatch below B; this is not the pinned data v1 manifest.")
}
if (!identical(digest::digest(file = file.path(B, required_files[3]), algo = "sha256", serialize = FALSE), price_sha)) {
  stop("Price manifest SHA-256 mismatch below B; this is not the pinned data v1 manifest.")
}
message("Data root B: ", B)

```

## 3. Query five SALE grids, then their prices

Both manifests are opened with their pinned SHA-256 values. The price query uses
the exact five grid IDs returned by the count query, for the same quarter/family.

```r
count_panel <- khmd_open_panel(file.path(B, "data/count/release_manifest.json"),
                               expected_sha256 = count_sha)
sale_counts <- khmd_panel_collect(count_panel, quarter = "2025Q1", family = "SALE", limit = 5L)
print(sale_counts)
if (!nrow(sale_counts)) stop("No SALE example grids returned; price query not attempted.")
price_panel <- khmd_open_price_panel(file.path(B, "data/price/release_manifest.json"),
                                     expected_sha256 = price_sha)
sale_prices <- khmd_price_collect(price_panel, grid_id = sale_counts$grid_id,
                                  quarter = "2025Q1", family = "SALE",
                                  metric = c("sale_amount", "sale_amount_m2"), limit = 10L)
print(sale_prices)
if (interactive()) View(sale_prices)

```

`sale_amount` is nominal **10,000 KRW**; `sale_amount_m2` is **10,000 KRW/m2**.
The latter summarizes prices divided by area **per observation**, not a ratio of
two medians. `n_obs` counts observations, `n_valid` is the metric's valid denominator,
and `n_excluded` counts its excluded values. `q25`, `median`, `q75` are exact type-7
quartiles. Price statistics are returned as **character strings to preserve
decimal precision**; converting a copy with `as.numeric()` may lose precision.
The original strings should be retained for reproducible work.

## 4. Inspect annual RENT observations, with the observed quarters shown

```r
requested_quarters <- paste0("2025Q", 1:4)
rent_2025 <- khmd_panel_collect(count_panel,
                               grid_id = "KHMD_UTMK_1KM_V1:1000:1660",
                               quarter = requested_quarters, family = "RENT", limit = 4L)
print(rent_2025)
quarters_present <- sort(unique(rent_2025$quarter))
annual_rent <- data.frame(grid_id = "KHMD_UTMK_1KM_V1:1000:1660", year = 2025L,
                          quarters_present = paste(quarters_present, collapse = ", "),
                          n_quarters_present = length(quarters_present),
                          n_obs_observed = if (nrow(rent_2025)) sum(rent_2025$n_obs) else NA_real_)
print(annual_rent)
# The annual number sums returned observations only, without a new/renewal split.
# Absent quarters are NOT filled with zero, and this does not prove completeness.
```

This sums all returned RENT observations for that grid/year **without a
new-versus-renewal contract distinction**. That contract-type filter is not in
the public panel API. `quarters_present` and `n_quarters_present` tell you what
was actually returned. Missing quarters are not zero-filled. If no rows are
returned, the example reports `NA` for the observed sum rather than asserting
a complete annual zero. Even four returned quarters do not prove population
completeness. Repeated occurrences are preserved: `n_obs` is **not a unique
transaction count or an official transaction total**.

## Troubleshooting and performance

| Symptom | Action |
|---|---|
| `object 'B' not found` | Run the data-folder block first; redefine uppercase `B` in every new session. |
| RSQLite missing | Complete the dependency-installation block; RSQLite >= 2.2.17 is required. |
| `package is in use` / skipped installation | Start a new R session and retry only the needed installation. A skipped/failed install is not a successful version change. Do not delete a live library. |
| Manifest missing | Check that `B/data/count` and `B/data/price` exist, not `B/B/data` or a code/library folder. |
| Checksum mismatch / partial extraction | Do not treat the files as valid. Inspect the reported path or choose a new empty `B`; the script preserves existing files. |
| Price opening/query appears slow | Public **0.0.5 verifies the complete database before and after reads**. Opening or even a small query may take tens of seconds; time depends on hardware, filesystem and R environment. Keep verification enabled. |

Use `Rscript consumer_quickstart.R "/your/data/root"` for noninteractive execution.
`View()` is called only in interactive R. Ordinary installation can spawn child
processes; it is distinct from the project's supervised single-worker query tests.
The example does not install any GC performance candidate or claim its timings
for public 0.0.5.

## Scope, validation and licenses

The deposit provides sparse grid-quarter counts, descriptive price/rental
distributions, quality denominators and provenance. It excludes raw transaction
rows, parcel boundaries, real PNU/representative-point datasets and individual-row
stores. Raw-observation functions such as `khmd_open_release()` require separate
stores not in the public ZIP. RENT ALL and its subtypes overlap; do not add these
levels together. Cancellation-marked sales remain under the documented policy.
See [README.txt](README.txt), [data sources](DATA_SOURCES.txt) and [citation](CITATION.txt).

Earlier Windows 11/R 4.5.2 source installation/check and real queries passed for
0.0.5 (`--no-manual --no-build-vignettes`, 0 ERROR/WARNING/NOTE). The later
consumer acceptance run passed 48 targeted checks; this documentation update
does not repeat that suite or claim a new full check. Its new example has a
separate fresh-session smoke test using the validated installation and public data.
Other operating systems and a dependency-empty PC have not been certified.
The separate construction candidate has limited synthetic connection tests,
not independent nationwide reproduction using a newly supplied input set.

The grid is KHMD_UTMK_1KM_V1, EPSG:5179, 1,000-m projected squares. Assignment to
2026 reference parcels is not validation of contract-time positions. Seoul
PILOT_PARTIAL, Cheongju PARTIAL_MATCH and unproven population completeness remain.
Publication is not agency endorsement, legal suitability or EPB acceptance.
The two previously documented source-rights interpretation issues remain.

Own software (including this executable example) is **MIT**. Author-held aggregate
data and independent-document contributions are **CC BY 4.0**. Original public
data and third-party components retain their terms and attribution; the author
does not relicense government raw data. Earlier noncommercial proposals are not
applied. See [LICENSE.txt](LICENSE.txt) and [LICENSE_SCOPE.csv](LICENSE_SCOPE.csv).

`GITHUB_FILES.csv` is the current checkout inventory, excluding itself.
`DISTRIBUTION_FILES.csv`, `FILE_INVENTORY.json/.sha256`, `UPLOAD_LIST.csv`,
`SOURCE_MAP.csv` and `metadata/*` are preserved historical combined-candidate or
validation records; they are not a current GitHub inventory. Frozen ZIP/package
documents can retain their preparation-time state. Current publication status is
in root [PUBLICATION_STATUS.txt](PUBLICATION_STATUS.txt) and
[Availability](DATA_AND_CODE_AVAILABILITY.txt).

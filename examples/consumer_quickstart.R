# KHMD first-user example: public package 0.0.5 + public dataset v1.
# Own example code: MIT; see repository LICENSE.txt and DATA_SOURCES.txt.
# Run top-to-bottom in R >= 4.2.0. No developer folder or saved R objects needed.

# ---- 1. Install only what is missing ----
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

# ---- 2. Set B: the extracted data root, NOT the code/library folder ----
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

# ---- 3. Observation counts and prices for the same five grids ----
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

# ---- 4. Observed RENT counts across the four quarters of 2025 ----
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

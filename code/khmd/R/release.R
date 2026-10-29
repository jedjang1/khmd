.khmd_stop <- function(message) stop(paste0("KHMD: ", message), call. = FALSE)
.khmd_need <- function(ok, message) if (!isTRUE(ok)) .khmd_stop(message)
.khmd_scalar <- function(x) is.character(x) && length(x) == 1L && !is.na(x) && nzchar(x)
.khmd_json <- function(x) jsonlite::fromJSON(x, simplifyVector = FALSE)
.khmd_hash <- function(path) {
  # Hash actual bytes. Windows access() heuristics can reject a readable file in
  # a restricted session; an actual read must still succeed and retain its size.
  size <- file.info(path)$size
  .khmd_need(length(size) == 1L && is.finite(size) && size >= 0 && size <= 16 * 1024^2, "manifest missing or exceeds 16 MiB")
  con <- file(path, "rb"); on.exit(close(con), add = TRUE)
  bytes <- readBin(con, what = "raw", n = size)
  .khmd_need(length(bytes) == size && file.info(path)$size == size, "manifest changed during read")
  digest::digest(bytes, algo = "sha256", serialize = FALSE)
}
.khmd_date <- function(x, name) {
  if (is.null(x)) return(NULL)
  if (inherits(x, "Date")) x <- as.character(x)
  .khmd_need(.khmd_scalar(x) && grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", x), paste(name, "must be one ISO date"))
  parsed <- tryCatch(as.Date(x), error = function(e) NA)
  .khmd_need(!is.na(parsed) && as.character(parsed) == x, paste(name, "is invalid"))
  x
}
.khmd_path <- function(path, base, path_map) {
  .khmd_need(.khmd_scalar(path), "invalid store path")
  path <- gsub("\\", "/", path, fixed = TRUE)
  if (length(path_map)) {
    .khmd_need(is.character(path_map) && !is.null(names(path_map)) &&
      all(nzchar(names(path_map))) && !anyNA(path_map) && !anyDuplicated(names(path_map)), "invalid path_map")
    from <- sub("/+$", "", gsub("\\", "/", names(path_map), fixed = TRUE))
    order_from <- order(nchar(from), decreasing = TRUE)
    for (i in order_from) if (path == from[i] || startsWith(path, paste0(from[i], "/"))) {
      path <- paste0(sub("/+$", "", gsub("\\", "/", path_map[[i]], fixed = TRUE)), substring(path, nchar(from[i]) + 1L))
      break
    }
  }
  if (!grepl("^(/|[A-Za-z]:/)", path)) path <- file.path(base, path)
  .khmd_need(file.exists(path) && !dir.exists(path), paste("store missing:", path))
  normalizePath(path, winslash = "/", mustWork = TRUE)
}
.khmd_with_store <- function(path, fun) {
  .khmd_need(file.exists(path) && !dir.exists(path), paste("store missing:", path))
  con <- DBI::dbConnect(RSQLite::SQLite(), dbname = path, flags = RSQLite::SQLITE_RO)
  on.exit(DBI::dbDisconnect(con), add = TRUE)
  DBI::dbExecute(con, "PRAGMA query_only=ON")
  DBI::dbExecute(con, "PRAGMA cache_size=-4096")
  DBI::dbExecute(con, "PRAGMA mmap_size=0")
  DBI::dbExecute(con, "PRAGMA temp_store=FILE")
  fun(con)
}
.khmd_query <- function(q) {
  .khmd_need(is.list(q) && all(c("family", "province", "district", "date_from", "date_to") %in% names(q)), "incomplete query scope")
  .khmd_need(q$family %in% c("SALE", "RENT") && .khmd_scalar(q$province) && .khmd_scalar(q$district), "invalid query scope")
  q$date_from <- .khmd_date(q$date_from, "date_from")
  q$date_to <- .khmd_date(q$date_to, "date_to")
  .khmd_need(!is.null(q$date_from) && !is.null(q$date_to) && q$date_from <= q$date_to, "invalid query period")
  q[c("family", "province", "district", "date_from", "date_to")]
}
.khmd_overlap <- function(a, b) {
  a$family == b$family && a$province == b$province &&
    (a$district == "\uC804\uCCB4" || b$district == "\uC804\uCCB4" || a$district == b$district) &&
    max(a$date_from, b$date_from) <= min(a$date_to, b$date_to)
}
.khmd_registry <- function(con, entry) {
  .khmd_need(all(c("files", "observations") %in% DBI::dbListTables(con)), "unsupported store schema")
  required <- c("obs_id", "file_sha", "ordinal", "byte_start", "byte_end", "raw_values", "states", "derived", "row_status")
  .khmd_need(all(required %in% DBI::dbListFields(con, "observations")), "unsupported observation schema")
  f <- DBI::dbGetQuery(con, "SELECT metadata,input_rows,good_rows,error_rows FROM files WHERE sha=?", params = list(entry$file_sha256))
  .khmd_need(nrow(f) == 1L, "selected SHA missing from store")
  m <- .khmd_json(f$metadata[[1]])
  .khmd_need(identical(m$sha256, entry$file_sha256) && identical(.khmd_query(m$query), entry$query), "registry SHA/query binding mismatch")
  .khmd_need(f$error_rows[[1]] == 0 && f$input_rows[[1]] == f$good_rows[[1]] &&
    m$input_rows == f$input_rows[[1]] && m$good_rows == f$good_rows[[1]], "selected file is not clean/conserved")
  .khmd_need(length(m$columns) > 0L && !anyDuplicated(unlist(m$columns)), "invalid stored column schema")
  m
}
.khmd_assert_release <- function(release) {
  .khmd_need(inherits(release, "khmd_release"), "expected a khmd_release")
  .khmd_need(file.exists(release$manifest) && .khmd_hash(release$manifest) == release$sha256, "release manifest changed; reopen explicitly")
  .khmd_need(identical(digest::digest(release$entries, algo = "sha256"), release$entries_digest), "release selection object changed")
  invisible(TRUE)
}

#' Open a CSV-only observation release
#' @export
khmd_open_release <- function(manifest, expected_sha256 = NULL, path_map = NULL) {
  .khmd_need(.khmd_scalar(manifest) && file.exists(manifest) && !dir.exists(manifest), "manifest missing")
  manifest <- normalizePath(manifest, winslash = "/", mustWork = TRUE)
  hash <- .khmd_hash(manifest)
  if (!is.null(expected_sha256)) .khmd_need(.khmd_scalar(expected_sha256) && hash == tolower(expected_sha256), "manifest SHA mismatch")
  doc <- .khmd_json(paste(readLines(manifest, encoding = "UTF-8", warn = FALSE), collapse = "\n"))
  .khmd_need(is.list(doc$active_files) && length(doc$active_files) > 0L, "active_files must be an explicit nonempty list")
  entries <- lapply(doc$active_files, function(e) {
    .khmd_need(is.list(e) && isTRUE(e$selected) && .khmd_scalar(e$file_sha256) &&
      grepl("^[a-f0-9]{64}$", e$file_sha256), "invalid selected entry/SHA")
    e$query <- .khmd_query(e$query)
    e$store <- .khmd_path(e$store, dirname(manifest), path_map)
    e
  })
  hashes <- vapply(entries, function(e) e$file_sha256, character(1))
  .khmd_need(!anyDuplicated(hashes), "duplicate selected SHA")
  for (i in seq_along(entries)) if (i > 1L) for (j in seq_len(i - 1L))
    .khmd_need(!.khmd_overlap(entries[[i]]$query, entries[[j]]$query), "selected query scopes overlap")
  meta <- vector("list", length(entries))
  stores <- vapply(entries, function(e) e$store, character(1))
  for (store in unique(stores)) .khmd_with_store(store, function(con) {
    for (i in which(stores == store)) meta[[i]] <<- .khmd_registry(con, entries[[i]])
  })
  rows <- sum(vapply(meta, function(m) as.numeric(m$good_rows), numeric(1)))
  if (!is.null(doc$active_file_count)) .khmd_need(doc$active_file_count == length(entries), "manifest file count mismatch")
  if (!is.null(doc$active_rows)) .khmd_need(doc$active_rows == rows, "manifest row count mismatch")
  structure(list(manifest = manifest, sha256 = hash, entries = entries, metadata = meta,
    entries_digest = digest::digest(entries, algo = "sha256"), rows = rows,
    validation = "Manifest selection/SHA (if supplied), registry scope, clean counts and schema checked; raw CSV and all database rows were NOT rehashed.",
    unit = "CSV observation occurrences, not unique transactions; query geography is not historical jurisdiction."), class = "khmd_release")
}

#' Inspect selected files and source provenance
#' @export
khmd_files <- function(release) {
  .khmd_assert_release(release)
  scalar <- function(x) if (is.null(x)) NA_character_ else as.character(x)
  rows <- lapply(seq_along(release$entries), function(i) {
    e <- release$entries[[i]]; m <- release$metadata[[i]]; q <- e$query
    data.frame(file_sha256 = e$file_sha256, family = q$family, query_province = q$province,
      query_district = q$district, date_from = q$date_from, date_to = q$date_to,
      observations = as.numeric(m$good_rows), store = e$store, source_path = scalar(m$path),
      snapshot_path = scalar(m$snapshot_path), source_url = scalar(m$source_url),
      download_started_at = scalar(m$download_started_at), download_completed_at = scalar(m$download_completed_at),
      acquisition_time_status = scalar(m$acquisition_time_status), encoding = scalar(m$encoding),
      query_conditions_json = as.character(jsonlite::toJSON(m$conditions, auto_unbox = TRUE, null = "null")),
      stringsAsFactors = FALSE)
  })
  do.call(rbind, rows)
}

print.khmd_release <- function(x, ...) {
  cat("<khmd_release> ", length(x$entries), " selected CSV files; ", format(x$rows, scientific = FALSE), " observation occurrences\n", sep = "")
  cat("Manifest SHA256: ", x$sha256, "\n", x$unit, "\n", sep = "")
  invisible(x)
}

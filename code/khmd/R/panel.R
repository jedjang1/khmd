.khmd_panel_blocks <- function(path, spec) {
  .khmd_need(is.list(spec) && identical(spec$algorithm, "sha256") &&
    is.numeric(spec$chunk_bytes) && spec$chunk_bytes >= 1 && spec$chunk_bytes <= 1048576 &&
    length(spec$chunk_sha256) == ceiling(spec$bytes / spec$chunk_bytes), "invalid panel block binding")
  .khmd_need(isTRUE(file.info(path)$size == spec$bytes), "panel database size mismatch")
  con <- file(path, "rb"); on.exit(close(con), add = TRUE)
  total <- 0
  gc(verbose = FALSE)
  for (expected in spec$chunk_sha256) {
    bytes <- readBin(con, "raw", n = spec$chunk_bytes)
    .khmd_need(digest::digest(bytes, algo = "sha256", serialize = FALSE) == expected,
      "panel database SHA block mismatch")
    total <- total + length(bytes)
    # Each verified block has no later use. Do not accumulate raw/digest
    # temporaries until R's much larger default heap collection threshold.
    rm(bytes)
    gc(verbose = FALSE)
  }
  .khmd_need(total == spec$bytes && length(readBin(con, "raw", n = 1L)) == 0L,
    "panel database length changed")
  invisible(TRUE)
}
.khmd_panel_binding <- function(panel) {
  .khmd_need(inherits(panel, "khmd_panel"), "expected a khmd_panel")
  .khmd_need(.khmd_hash(panel$manifest) == panel$sha256, "panel manifest changed; reopen explicitly")
  .khmd_need(identical(digest::digest(panel$document, algo = "sha256"), panel$document_digest),
    "panel metadata object changed")
  for (name in c("source_release", "spatial_result")) {
    .khmd_need(.khmd_hash(panel$references[[name]]) == panel$document[[name]]$sha256,
      paste(name, "SHA mismatch"))
  }
  .khmd_panel_blocks(panel$database, panel$document$database_integrity)
}
.khmd_panel_with <- function(panel, fun) {
  .khmd_panel_binding(panel)
  result <- .khmd_with_store(panel$database, function(con) {
    .khmd_need(all(c("panel", "quality", "metadata") %in% DBI::dbListTables(con)), "panel tables missing")
    m <- DBI::dbGetQuery(con, "SELECT key,value FROM metadata")
    .khmd_need(!anyDuplicated(m$key), "duplicate panel metadata")
    values <- stats::setNames(as.list(m$value), m$key)
    for (key in c("schema", "grid_version", "source_release_sha256", "spatial_manifest_sha256", "unit", "sparse")) {
      .khmd_need(identical(values[[key]], panel$document[[key]]), paste("mixed panel binding:", key))
    }
    fun(con)
  })
  # Bounded full-byte verification, not an mtime-only immutability claim.
  .khmd_panel_binding(panel)
  result
}

khmd_open_panel <- function(manifest, expected_sha256 = NULL, path_map = NULL) {
  .khmd_need(.khmd_scalar(manifest) && file.exists(manifest), "panel manifest missing")
  manifest <- normalizePath(manifest, winslash = "/", mustWork = TRUE)
  hash <- .khmd_hash(manifest)
  if (!is.null(expected_sha256)) .khmd_need(.khmd_scalar(expected_sha256) &&
    hash == tolower(expected_sha256), "panel manifest SHA mismatch")
  doc <- .khmd_json(paste(readLines(manifest, encoding = "UTF-8", warn = FALSE), collapse = "\n"))
  .khmd_need(identical(doc$schema, "KHMD_OBSERVATION_PANEL_V1") &&
    identical(doc$unit, "observation_occurrence") && identical(doc$sparse, "true"), "unsupported panel semantics")
  .khmd_need(.khmd_scalar(doc$grid_version) && identical(doc$grid$version, doc$grid_version), "mixed grid version")
  .khmd_need(identical(doc$source_release_sha256, doc$source_release$sha256) &&
    identical(doc$spatial_manifest_sha256, doc$spatial_result$sha256), "mixed source/spatial release")
  database <- .khmd_path(doc$database, dirname(manifest), path_map)
  references <- lapply(doc[c("source_release", "spatial_result")], function(x)
    .khmd_path(x$path, dirname(manifest), path_map))
  result <- structure(list(manifest = manifest, sha256 = hash, database = database,
    references = references, document = doc,
    document_digest = digest::digest(doc, algo = "sha256")), class = "khmd_panel")
  .khmd_panel_with(result, function(con) {
    .khmd_need(all(c("grid_id", "quarter", "transaction_family", "n_obs") %in%
      DBI::dbListFields(con, "panel")), "panel schema mismatch")
    invisible(TRUE)
  })
  result
}

khmd_panel_metadata <- function(panel) {
  .khmd_panel_with(panel, function(con) panel$document)
}
.khmd_panel_filter <- function(panel, grid_id, quarter, family, query_region, quality) {
  parts <- character(); params <- list()
  add <- function(values, column, max_n = 400L) {
    if (is.null(values)) return(invisible(NULL))
    .khmd_need(is.character(values) && length(values) > 0L && length(values) <= max_n &&
      !anyNA(values) && all(nzchar(values)), paste("invalid", column, "filter"))
    parts <<- c(parts, paste0(column, " IN (", paste(rep("?", length(values)), collapse = ","), ")"))
    params <<- c(params, as.list(values))
  }
  if (!is.null(grid_id)) {
    .khmd_need(!quality && is.character(grid_id) && !anyNA(grid_id) &&
      all(startsWith(grid_id, paste0(panel$document$grid_version, ":"))), "grid filter has wrong version or table")
  }
  if (!is.null(quarter)) .khmd_need(is.character(quarter) && !anyNA(quarter) &&
    all(grepl("^[0-9]{4}Q[1-4]$", quarter)), "quarter must use YYYYQ1..Q4")
  if (!is.null(family)) .khmd_need(is.character(family) && !anyNA(family) &&
    all(family %in% c("SALE", "RENT")), "invalid family")
  .khmd_need(quality || is.null(query_region), "query-region denominators are separate from grid counts")
  add(grid_id, "grid_id"); add(quarter, "quarter"); add(family, "transaction_family", 2L)
  add(query_region, "query_region", 50L)
  list(where = if (length(parts)) paste("WHERE", paste(parts, collapse = " AND ")) else "", params = params)
}
.khmd_panel_select <- function(panel, grid_id, quarter, family, query_region, quality,
                               limit, offset) {
  limit <- .khmd_bound(limit, "limit")
  .khmd_need(length(offset) == 1L && is.numeric(offset) && is.finite(offset) &&
    offset >= 0 && offset == floor(offset), "offset must be a nonnegative integer")
  f <- .khmd_panel_filter(panel, grid_id, quarter, family, query_region, quality)
  table <- if (quality) "quality" else "panel"
  order <- if (quality) "query_region,quarter,transaction_family" else "grid_id,quarter,transaction_family"
  .khmd_panel_with(panel, function(con) DBI::dbGetQuery(con,
    paste("SELECT * FROM", table, f$where, "ORDER BY", order, "LIMIT ? OFFSET ?"),
    params = c(f$params, list(limit, offset))))
}
khmd_panel_collect <- function(panel, grid_id = NULL, quarter = NULL, family = NULL,
                               limit = 1000L, offset = 0L) {
  .khmd_panel_select(panel, grid_id, quarter, family, NULL, FALSE, limit, offset)
}
khmd_panel_quality <- function(panel, query_region = NULL, quarter = NULL, family = NULL,
                               limit = 1000L, offset = 0L) {
  .khmd_panel_select(panel, NULL, quarter, family, query_region, TRUE, limit, offset)
}
khmd_panel_stream <- function(panel, callback, dataset = c("panel", "quality"),
                              grid_id = NULL, quarter = NULL, family = NULL,
                              query_region = NULL, chunk_size = 1000L) {
  dataset <- match.arg(dataset); chunk_size <- .khmd_bound(chunk_size, "chunk_size")
  .khmd_need(is.function(callback), "callback must be a function")
  f <- .khmd_panel_filter(panel, grid_id, quarter, family, query_region, dataset == "quality")
  order <- if (dataset == "quality") "query_region,quarter,transaction_family" else "grid_id,quarter,transaction_family"
  .khmd_panel_with(panel, function(con) {
    res <- DBI::dbSendQuery(con, paste("SELECT * FROM", dataset, f$where, "ORDER BY", order))
    on.exit(DBI::dbClearResult(res), add = TRUE)
    if (length(f$params)) DBI::dbBind(res, f$params)
    rows <- 0; chunks <- 0; stopped <- FALSE
    repeat {
      batch <- DBI::dbFetch(res, n = chunk_size)
      if (!nrow(batch)) break
      rows <- rows + nrow(batch); chunks <- chunks + 1L
      if (identical(callback(batch), FALSE)) { stopped <- TRUE; break }
    }
    invisible(list(rows = rows, chunks = chunks, stopped_by_callback = stopped))
  })
}
khmd_panel_totals <- function(panel) {
  .khmd_panel_with(panel, function(con) {
    a <- DBI::dbGetQuery(con, "SELECT COUNT(*) AS panel_groups,SUM(n_obs) AS assigned_n FROM panel")
    q <- DBI::dbGetQuery(con, "SELECT SUM(input_n) AS input_n,SUM(assigned_n) AS quality_assigned_n,SUM(unassigned_n) AS unassigned_n FROM quality")
    .khmd_need(a$assigned_n == q$quality_assigned_n && q$input_n == q$quality_assigned_n + q$unassigned_n &&
      a$assigned_n == panel$document$assigned && q$input_n == panel$document$input_occurrences &&
      q$unassigned_n == panel$document$unassigned && a$panel_groups == panel$document$panel_groups,
      "panel/quality conservation mismatch")
    cbind(a, q)
  })
}

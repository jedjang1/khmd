.khmd_filters <- function(release, family, province, start, end, region) {
  .khmd_assert_release(release)
  valid <- function(x) is.null(x) || (is.character(x) && length(x) > 0L && !anyNA(x) && all(nzchar(x)))
  .khmd_need(valid(family) && valid(province) && valid(region), "filters must be nonempty character vectors or NULL")
  .khmd_need(is.null(family) || all(family %in% c("SALE", "RENT")), "family must be SALE/RENT")
  start <- .khmd_date(start, "start"); end <- .khmd_date(end, "end")
  .khmd_need(is.null(start) || is.null(end) || start <= end, "start is after end")
  ids <- which(vapply(release$entries, function(e) {
    q <- e$query
    (is.null(family) || q$family %in% family) && (is.null(province) || q$province %in% province) &&
      (is.null(start) || q$date_to >= start) && (is.null(end) || q$date_from <= end)
  }, logical(1)))
  list(ids = ids, start = start, end = end, region = region)
}
.khmd_where <- function(entry, filters) {
  sql <- "o.file_sha=? AND o.row_status='PARSED'"; params <- list(entry$file_sha256)
  if (!is.null(filters$start)) { sql <- paste0(sql, " AND json_extract(o.derived,'$.contract_date')>=?"); params <- c(params, list(filters$start)) }
  if (!is.null(filters$end)) { sql <- paste0(sql, " AND json_extract(o.derived,'$.contract_date')<=?"); params <- c(params, list(filters$end)) }
  if (!is.null(filters$region)) {
    # Exact or whitespace-boundary prefix of the stored CSV label; no geography inference.
    term <- "(json_extract(o.derived,'$.csv_region_literal')=? OR substr(json_extract(o.derived,'$.csv_region_literal'),1,length(?)+1)=?||' ')"
    sql <- paste0(sql, " AND (", paste(rep(term, length(filters$region)), collapse = " OR "), ")")
    for (label in filters$region) params <- c(params, list(label, label, label))
  }
  list(sql = sql, params = params)
}
.khmd_bound <- function(n, name, max = 10000) {
  .khmd_need(is.numeric(n) && length(n) == 1L && is.finite(n) && n >= 1 && n <= max && n == floor(n), paste(name, "must be an integer from 1 to", max))
  as.integer(n)
}
.khmd_enrich <- function(rows, entry, metadata) {
  q <- entry$query; n <- nrow(rows)
  text <- function(v) rep(if (is.null(v)) NA_character_ else as.character(v), n)
  rows$family <- text(q$family); rows$query_province <- text(q$province); rows$query_district <- text(q$district)
  rows$query_date_from <- text(q$date_from); rows$query_date_to <- text(q$date_to)
  rows$columns_json <- text(jsonlite::toJSON(metadata$columns, auto_unbox = FALSE))
  for (field in c("source_url", "acquisition_time_status", "download_started_at", "download_completed_at")) rows[[field]] <- text(metadata[[field]])
  rows$source_path <- text(metadata$path); rows$snapshot_path <- text(metadata$snapshot_path)
  rows
}
.khmd_empty <- function() {
  data.frame(obs_id = character(), file_sha = character(), ordinal = integer(), physical_line_start = integer(),
    physical_line_end = integer(), byte_start = numeric(), byte_end = numeric(), raw_values = character(), states = character(),
    derived = character(), raw_content_digest = character(), row_status = character(), error = character(),
    family = character(), query_province = character(), query_district = character(), query_date_from = character(), query_date_to = character(),
    columns_json = character(), source_url = character(), acquisition_time_status = character(), download_started_at = character(),
    download_completed_at = character(), source_path = character(), snapshot_path = character(), stringsAsFactors = FALSE)
}

#' Read a bounded page of selected observations
#' @export
khmd_collect <- function(release, family = NULL, province = NULL, start = NULL, end = NULL,
                         region = NULL, limit = 1000L, offset = 0) {
  filters <- .khmd_filters(release, family, province, start, end, region)
  limit <- .khmd_bound(limit, "limit")
  .khmd_need(is.numeric(offset) && length(offset) == 1L && is.finite(offset) && offset >= 0 && offset == floor(offset), "invalid offset")
  pieces <- list(); left <- limit; skip <- offset
  for (i in filters$ids) {
    e <- release$entries[[i]]; w <- .khmd_where(e, filters)
    got <- .khmd_with_store(e$store, function(con) {
      m <- .khmd_registry(con, e)
      if (skip > 0) {
        n <- DBI::dbGetQuery(con, paste0("SELECT COUNT(*) AS n FROM observations o WHERE ", w$sql), params = w$params)$n[[1]]
        if (skip >= n) { skip <<- skip - n; return(NULL) }
      }
      df <- DBI::dbGetQuery(con, paste0("SELECT o.* FROM observations o WHERE ", w$sql, " ORDER BY o.ordinal LIMIT ? OFFSET ?"), params = c(w$params, list(left, skip)))
      skip <<- 0
      .khmd_enrich(df, e, m)
    })
    if (!is.null(got) && nrow(got)) { pieces[[length(pieces) + 1L]] <- got; left <- left - nrow(got) }
    if (left == 0L) break
  }
  ans <- if (length(pieces)) do.call(rbind, pieces) else .khmd_empty()
  rownames(ans) <- NULL
  attr(ans, "unit") <- "observation occurrences; bounded result, not unique transactions"
  ans
}

#' Stream selected observations without accumulating them
#' @export
khmd_stream <- function(release, callback, family = NULL, province = NULL, start = NULL, end = NULL,
                        region = NULL, chunk_size = 1000L) {
  filters <- .khmd_filters(release, family, province, start, end, region)
  .khmd_need(is.function(callback), "callback must be a function")
  chunk_size <- .khmd_bound(chunk_size, "chunk_size"); total <- 0
  for (i in filters$ids) {
    e <- release$entries[[i]]; w <- .khmd_where(e, filters)
    .khmd_with_store(e$store, function(con) {
      m <- .khmd_registry(con, e)
      rs <- DBI::dbSendQuery(con, paste0("SELECT o.* FROM observations o WHERE ", w$sql, " ORDER BY o.ordinal"))
      on.exit(DBI::dbClearResult(rs), add = TRUE)
      DBI::dbBind(rs, w$params)
      repeat {
        df <- DBI::dbFetch(rs, n = chunk_size)
        if (!nrow(df)) break
        callback(.khmd_enrich(df, e, m))
        total <<- total + nrow(df)
      }
    })
  }
  invisible(total)
}

#' Count observation occurrences by reported region, month and family
#' @export
khmd_count <- function(release, family = NULL, province = NULL, start = NULL, end = NULL, region = NULL) {
  filters <- .khmd_filters(release, family, province, start, end, region); pieces <- list()
  for (i in filters$ids) {
    e <- release$entries[[i]]; w <- .khmd_where(e, filters)
    df <- .khmd_with_store(e$store, function(con) {
      .khmd_registry(con, e)
      DBI::dbGetQuery(con, paste0("SELECT json_extract(o.derived,'$.csv_region_literal') AS region, ",
        "substr(json_extract(o.derived,'$.contract_date'),1,7) AS year_month, COUNT(*) AS occurrences ",
        "FROM observations o WHERE ", w$sql, " GROUP BY region,year_month ORDER BY region,year_month"), params = w$params)
    })
    if (nrow(df)) { df$family <- e$query$family; df$query_province <- e$query$province; pieces[[length(pieces) + 1L]] <- df }
  }
  if (!length(pieces)) return(data.frame(family = character(), query_province = character(), region = character(), year_month = character(), occurrences = numeric()))
  combined <- do.call(rbind, pieces)
  .khmd_need(!anyNA(combined$region) && !anyNA(combined$year_month), "missing stored derived group key")
  ans <- stats::aggregate(combined$occurrences, combined[c("family", "query_province", "region", "year_month")], sum)
  names(ans)[5] <- "occurrences"
  ans <- ans[order(ans$family, ans$query_province, ans$region, ans$year_month), , drop = FALSE]; rownames(ans) <- NULL
  attr(ans, "unit") <- "observation occurrences; region is the stored CSV label, not a historical boundary"
  ans
}

#' Extract one raw field without normalizing its observability
#' @export
khmd_field <- function(rows, field) {
  .khmd_need(is.data.frame(rows) && all(c("obs_id", "columns_json", "raw_values", "states") %in% names(rows)) && .khmd_scalar(field), "expected observation rows and one field name")
  out <- data.frame(obs_id = rows$obs_id, value = rep(NA_character_, nrow(rows)), state = rep("ABSENT", nrow(rows)), stringsAsFactors = FALSE)
  for (i in seq_len(nrow(rows))) {
    cols <- unlist(.khmd_json(rows$columns_json[[i]]), use.names = FALSE)
    values <- unlist(.khmd_json(rows$raw_values[[i]]), use.names = FALSE)
    states <- unlist(.khmd_json(rows$states[[i]]), use.names = FALSE)
    .khmd_need(length(cols) == length(values) && length(cols) == length(states), "stored raw/schema/state length mismatch")
    j <- match(field, cols)
    if (!is.na(j)) { out$value[[i]] <- values[[j]]; out$state[[i]] <- states[[j]] }
  }
  out
}

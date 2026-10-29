fixture_release <- function() {
  root <- tempfile("khmd-fixture-"); dir.create(root)
  db <- file.path(root, "observations.sqlite")
  con <- DBI::dbConnect(RSQLite::SQLite(), db); on.exit(DBI::dbDisconnect(con))
  DBI::dbExecute(con, "CREATE TABLE files(sha TEXT PRIMARY KEY,metadata TEXT,input_rows INTEGER,good_rows INTEGER,error_rows INTEGER)")
  DBI::dbExecute(con, paste("CREATE TABLE observations(obs_id TEXT PRIMARY KEY,file_sha TEXT,ordinal INTEGER,",
    "physical_line_start INTEGER,physical_line_end INTEGER,byte_start INTEGER,byte_end INTEGER,",
    "raw_values TEXT,states TEXT,derived TEXT,raw_content_digest TEXT,row_status TEXT,error TEXT)"))
  DBI::dbExecute(con, "CREATE UNIQUE INDEX file_ordinal ON observations(file_sha,ordinal)")
  hashes <- vapply(c("a", "b", "c"), function(x) paste(rep(x, 64), collapse = ""), character(1))
  scopes <- list(list(family = "RENT", province = "서울특별시", district = "전체", date_from = "2011-01-01", date_to = "2011-12-31"),
                 list(family = "RENT", province = "서울특별시", district = "종로구", date_from = "2011-01-01", date_to = "2011-01-31"),
                 list(family = "SALE", province = "부산광역시", district = "전체", date_from = "2011-01-01", date_to = "2011-12-31"))
  counts <- c(3L, 1L, 1L)
  entries <- list()
  for (i in seq_along(hashes)) {
    cols <- if (i == 3L) c("NO", "price") else c("NO", "monthly", "optional")
    m <- list(sha256 = hashes[[i]], query = scopes[[i]], input_rows = counts[[i]], good_rows = counts[[i]], error_rows = 0L,
      columns = cols, path = "SYNTHETIC_NOT_A_SOURCE_CSV", snapshot_path = NULL, source_url = "https://example.invalid/synthetic",
      encoding = "cp949", conditions = list(fixture = "synthetic"), acquisition_time_status = "UNKNOWN", download_started_at = NULL, download_completed_at = NULL)
    DBI::dbExecute(con, "INSERT INTO files VALUES(?,?,?,?,?)", params = list(hashes[[i]], as.character(jsonlite::toJSON(m, auto_unbox = TRUE, null = "null")), counts[[i]], counts[[i]], 0L))
    entries[[i]] <- list(file_sha256 = hashes[[i]], selected = TRUE, store = "observations.sqlite", query = scopes[[i]])
    for (j in seq_len(counts[[i]])) {
      values <- if (i == 3L) c(as.character(j), "100") else if (i == 2L) c(as.character(j), "EXCLUDED", "-") else if (j == 1L) c("1", " ", "") else c(as.character(j), "0", "-")
      states <- if (i == 3L) c("VALUE", "VALUE") else if (i == 2L) c("VALUE", "VALUE", "DISPLAY_DASH") else if (j == 1L) c("VALUE", "WHITESPACE", "EMPTY") else c("VALUE", "EXPLICIT_ZERO", "DISPLAY_DASH")
      day <- if (j == 1L) "2011-02-01" else "2011-01-02"
      d <- list(contract_date = day, contract_month = gsub("-", "", substr(day, 1, 7)),
        csv_region_literal = if (i == 3L) "부산광역시 중구 중앙동" else "서울특별시 종로구 숭인동", numeric = list())
      vals <- list(paste0("fixture-", i, "-", j), hashes[[i]], j, j+10L, j+10L, j*100L, j*100L+99L,
        as.character(jsonlite::toJSON(values)), as.character(jsonlite::toJSON(states)), as.character(jsonlite::toJSON(d, auto_unbox = TRUE)),
        if (i == 1L && j > 1L) "repeated-content-without-NO" else "other-content", "PARSED", NA_character_)
      DBI::dbExecute(con, "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", params = vals)
    }
  }
  doc <- list(version = "SYNTHETIC_TEST_ONLY", active_files = entries[c(1,3)], active_file_count = 2L, active_rows = 4L,
    excluded_prior_files = list(entries[[2]]), production_authority = FALSE)
  path <- file.path(root, "release.json")
  jsonlite::write_json(doc, path, auto_unbox = TRUE, pretty = TRUE, null = "null")
  list(root = root, db = db, manifest = path, doc = doc, entries = entries, hashes = hashes)
}
write_fixture_manifest <- function(f, doc) {
  jsonlite::write_json(doc, f$manifest, auto_unbox = TRUE, pretty = TRUE, null = "null")
}

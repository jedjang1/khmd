test_that("only selected snapshots enter queries and repeated occurrences remain", {
  f <- fixture_release(); r <- khmd_open_release(f$manifest)
  expect_equal(nrow(khmd_files(r)), 2L)
  expect_equal(r$rows, 4)
  rows <- khmd_collect(r)
  expect_equal(nrow(rows), 4L)
  expect_false(any(rows$file_sha == f$hashes[[2]]))
  expect_equal(sum(rows$raw_content_digest == "repeated-content-without-NO"), 2L)
  expect_equal(length(unique(rows$obs_id)), 4L)
  expect_true(all(is.na(khmd_files(r)$download_completed_at)))
})

test_that("raw whitespace, zero, empty, dash and absence remain separate", {
  r <- khmd_open_release(fixture_release()$manifest); rows <- khmd_collect(r)
  m <- khmd_field(rows, "monthly")
  expect_identical(m$value, c(" ", "0", "0", NA_character_))
  expect_identical(m$state, c("WHITESPACE", "EXPLICIT_ZERO", "EXPLICIT_ZERO", "ABSENT"))
  expect_identical(khmd_field(rows, "optional")$state, c("EMPTY", "DISPLAY_DASH", "DISPLAY_DASH", "ABSENT"))
  expect_true(all(khmd_field(rows, "not_in_schema")$state == "ABSENT"))
})

test_that("bounded filters, offset and grouped counts agree", {
  r <- khmd_open_release(fixture_release()$manifest)
  x <- khmd_collect(r, family = "RENT", province = "서울특별시", start = "2011-01-01", end = "2011-01-31", region = "서울특별시 종로구", limit = 1)
  expect_identical(x$obs_id, "fixture-1-2")
  expect_identical(khmd_collect(r, family = "RENT", start = "2011-01-01", end = "2011-01-31", limit = 1, offset = 1)$obs_id, "fixture-1-3")
  expect_equal(sum(khmd_count(r, family = "RENT")$occurrences), 3)
  expect_equal(sum(khmd_count(r, region = "서울특별시 종로구", start = "2011-01-01", end = "2011-01-31")$occurrences), 2)
  expect_equal(nrow(khmd_collect(r, region = "서울특별시 종로")), 0L)
  expect_equal(nrow(khmd_collect(r, region = "서울특별시%' OR 1=1 --")), 0L)
  expect_equal(nrow(khmd_collect(r, start = "2020-01-01")), 0L)
  expect_equal(nrow(khmd_collect(r, offset = 100)), 0L)
  expect_error(khmd_collect(r, limit = Inf), "limit")
  expect_error(khmd_collect(r, limit = 10001), "limit")
  expect_error(khmd_count(r, start = "2011-02-30"), "invalid")
  expect_error(khmd_count(r, family = "API"), "family")
})

test_that("streaming is chunked and callback errors propagate", {
  r <- khmd_open_release(fixture_release()$manifest); sizes <- integer(); ids <- character()
  n <- khmd_stream(r, function(chunk) { sizes <<- c(sizes, nrow(chunk)); ids <<- c(ids, chunk$obs_id) }, chunk_size = 2)
  expect_equal(n, 4)
  expect_true(all(sizes <= 2))
  expect_identical(ids, khmd_collect(r)$obs_id)
  expect_error(khmd_stream(r, function(x) stop("CALLBACK_SENTINEL")), "CALLBACK_SENTINEL")
  expect_equal(nrow(khmd_collect(r)), 4L)
})

test_that("missing paths, SHA drift and selection drift fail closed", {
  f <- fixture_release()
  expect_error(khmd_open_release(file.path(f$root, "missing.json")), "manifest missing")
  expect_error(khmd_open_release(f$manifest, expected_sha256 = strrep("0",64)), "SHA mismatch")
  doc <- f$doc; doc$active_files[[1]]$store <- "missing.sqlite"; write_fixture_manifest(f, doc)
  expect_error(khmd_open_release(f$manifest), "store missing")
  write_fixture_manifest(f, f$doc); r <- khmd_open_release(f$manifest)
  cat("\n", file = f$manifest, append = TRUE)
  expect_error(khmd_collect(r), "manifest changed")
  write_fixture_manifest(f, f$doc); r <- khmd_open_release(f$manifest)
  r$entries[[1]]$file_sha256 <- f$hashes[[2]]
  expect_error(khmd_collect(r), "selection object changed")
})

test_that("registry mismatches and ambiguous releases are rejected", {
  f <- fixture_release(); doc <- f$doc; doc$active_files[[1]]$file_sha256 <- strrep("d",64)
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "selected SHA missing")
  doc <- f$doc; doc$active_files[[2]] <- f$entries[[2]]
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "scopes overlap")
  doc <- f$doc; doc$active_files[[2]] <- f$entries[[1]]
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "duplicate selected SHA")
  doc <- f$doc; doc$active_files[[1]]$selected <- FALSE
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "selected entry")
  doc <- f$doc; doc$active_rows <- 99L
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "row count mismatch")
  doc <- f$doc; doc$active_files[[1]]$query$date_to <- "2011-11-30"
  write_fixture_manifest(f, doc); expect_error(khmd_open_release(f$manifest), "binding mismatch")
})

test_that("relocation is explicit and connections cannot write source stores", {
  f <- fixture_release(); doc <- f$doc
  for (i in seq_along(doc$active_files)) doc$active_files[[i]]$store <- "OLD_ROOT/observations.sqlite"
  write_fixture_manifest(f, doc)
  r <- khmd_open_release(f$manifest, path_map = c(OLD_ROOT = f$root))
  expect_equal(r$rows, 4)
  expect_error(khmd:::.khmd_with_store(f$db, function(c) DBI::dbExecute(c, "DELETE FROM observations")), "readonly|read.only")
  expect_equal(nrow(khmd_collect(r)), 4L)
  file.rename(f$db, paste0(f$db,".moved"))
  expect_error(khmd_collect(r), "store missing")
})

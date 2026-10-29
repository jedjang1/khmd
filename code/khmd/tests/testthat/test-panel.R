panel_fixture <- function() {
  root <- tempfile("khmd-panel-"); dir.create(root)
  source <- file.path(root, "source.json"); spatial <- file.path(root, "spatial.json")
  writeLines('{"synthetic_source":true}', source)
  writeLines('{"synthetic_spatial":true}', spatial)
  hash <- khmd:::.khmd_hash
  version <- "KHMD_UTMK_1KM_V1"
  doc <- list(schema="KHMD_OBSERVATION_PANEL_V1", grid_version=version,
    grid=list(version=version), source_release_sha256=hash(source),
    spatial_manifest_sha256=hash(spatial), unit="observation_occurrence", sparse="true",
    source_release=list(path="source.json",sha256=hash(source)),
    spatial_result=list(path="spatial.json",sha256=hash(spatial)), database="panel.sqlite",
    assigned=7L,unassigned=2L,input_occurrences=9L,panel_groups=3L)
  path <- file.path(root,"panel.sqlite")
  con <- DBI::dbConnect(RSQLite::SQLite(),path)
  DBI::dbExecute(con,"CREATE TABLE panel(grid_id TEXT,quarter TEXT,transaction_family TEXT,n_obs INTEGER,PRIMARY KEY(grid_id,quarter,transaction_family))")
  DBI::dbExecute(con,"CREATE TABLE quality(query_region TEXT,quarter TEXT,transaction_family TEXT,input_n INTEGER,assigned_n INTEGER,unassigned_n INTEGER,ambiguous_n INTEGER,assignment_rate REAL)")
  DBI::dbExecute(con,"CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
  for(k in c("schema","grid_version","source_release_sha256","spatial_manifest_sha256","unit","sparse"))
    DBI::dbExecute(con,"INSERT INTO metadata VALUES(?,?)",params=list(k,doc[[k]]))
  for(row in list(list(paste0(version,":1:2"),"2025Q1","RENT",3L),
                  list(paste0(version,":1:2"),"2025Q1","SALE",2L),
                  list(paste0(version,":2:2"),"2025Q2","RENT",2L)))
    DBI::dbExecute(con,"INSERT INTO panel VALUES(?,?,?,?)",params=row)
  DBI::dbExecute(con,"INSERT INTO quality VALUES('Region A','2025Q1','RENT',5,3,2,2,0.6)")
  DBI::dbExecute(con,"INSERT INTO quality VALUES('Region A','2025Q1','SALE',2,2,0,0,1)")
  DBI::dbExecute(con,"INSERT INTO quality VALUES('Region B','2025Q2','RENT',2,2,0,0,1)")
  DBI::dbDisconnect(con)
  f <- list(root=root,db=path,manifest=file.path(root,"panel.json"),doc=doc)
  panel_reseal(f)
}
panel_reseal <- function(f) {
  size <- file.info(f$db)$size; con <- file(f$db,"rb"); on.exit(close(con))
  blocks <- list()
  repeat {
    bytes <- readBin(con,"raw",n=4096L); if(!length(bytes)) break
    blocks[[length(blocks)+1L]] <- digest::digest(bytes,algo="sha256",serialize=FALSE)
  }
  f$doc$database_integrity <- list(algorithm="sha256",bytes=size,chunk_bytes=4096L,chunk_sha256=blocks)
  jsonlite::write_json(f$doc,f$manifest,auto_unbox=TRUE,pretty=TRUE)
  f
}
test_that("sparse panel counts and quality retain distinct denominators", {
  f <- panel_fixture(); p <- khmd_open_panel(f$manifest)
  expect_s3_class(p,"khmd_panel")
  expect_equal(khmd_panel_metadata(p)$unit,"observation_occurrence")
  expect_equal(khmd_panel_collect(p,quarter="2025Q1",family="RENT")$n_obs,3L)
  expect_equal(nrow(khmd_panel_collect(p,quarter="2024Q1")),0L)
  expect_equal(khmd_panel_collect(p,grid_id="KHMD_UTMK_1KM_V1:1:2")$n_obs,c(3L,2L))
  q <- khmd_panel_quality(p,query_region="Region A",quarter="2025Q1",family="RENT")
  expect_equal(q$input_n,5L); expect_equal(q$ambiguous_n,2L)
  expect_equal(q$assignment_rate,0.6)
  expect_equal(khmd_panel_totals(p)$input_n,9L)
  expect_equal(khmd_panel_totals(p)$assigned_n,7L)
  expect_error(khmd_panel_collect(p,grid_id="OLD:1:2"),"wrong version")
  expect_error(khmd_panel_collect(p,quarter="2025Q5"),"quarter")
  expect_error(khmd_panel_collect(p,family="SQL' OR 1=1"),"family")
  expect_error(khmd_panel_collect(p,limit=10001),"limit")
  expect_error(khmd_panel_stream(p,identity,query_region="Region A"),"separate")
})
test_that("chunking preserves counts and supports bounded early stop", {
  p <- khmd_open_panel(panel_fixture()$manifest)
  batches <- list()
  r <- khmd_panel_stream(p,function(x) { batches[[length(batches)+1L]] <<- x },chunk_size=2L)
  expect_equal(r$rows,3L); expect_equal(r$chunks,2L)
  expect_equal(sum(vapply(batches,function(x)sum(x$n_obs),numeric(1))),7)
  expect_lte(max(vapply(batches,nrow,integer(1))),2L)
  r <- khmd_panel_stream(p,function(x) FALSE,chunk_size=1L)
  expect_equal(r$rows,1L); expect_true(r$stopped_by_callback)
  r <- khmd_panel_stream(p,function(x) NULL,dataset="quality",query_region="Region A",chunk_size=1L)
  expect_equal(r$rows,2L)
})
test_that("source, grid, byte and manifest drift are rejected", {
  f <- panel_fixture()
  expect_error(khmd_open_panel(f$manifest,expected_sha256=paste(rep("0",64),collapse="")),"SHA")
  p <- khmd_open_panel(f$manifest); p$document$grid_version <- "OTHER"
  expect_error(khmd_panel_collect(p),"object changed")
  f$doc$grid$version <- "OTHER"; f <- panel_reseal(f)
  expect_error(khmd_open_panel(f$manifest),"mixed grid")
  f <- panel_fixture(); con <- DBI::dbConnect(RSQLite::SQLite(),f$db)
  DBI::dbExecute(con,"UPDATE metadata SET value='OTHER_SOURCE' WHERE key='source_release_sha256'")
  DBI::dbDisconnect(con); f <- panel_reseal(f)
  expect_error(khmd_open_panel(f$manifest),"mixed panel binding")
  f <- panel_fixture(); p <- khmd_open_panel(f$manifest)
  con <- DBI::dbConnect(RSQLite::SQLite(),f$db); DBI::dbExecute(con,"UPDATE panel SET n_obs=99"); DBI::dbDisconnect(con)
  expect_error(khmd_panel_collect(p),"SHA block")
  f <- panel_fixture(); p <- khmd_open_panel(f$manifest)
  writeLines('{"changed":true}',file.path(f$root,"source.json"))
  expect_error(khmd_panel_quality(p),"source_release SHA")
  f <- panel_fixture(); f$doc$database <- "missing.sqlite"; f <- panel_reseal(f)
  expect_error(khmd_open_panel(f$manifest),"missing")
})

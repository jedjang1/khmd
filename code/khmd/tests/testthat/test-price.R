price_fixture <- function() {
  root <- tempfile("price-fixture-");dir.create(root)
  for(n in c("source","spatial","count")) writeLines(paste0('{"fixture":"',n,'"}'),file.path(root,paste0(n,".json")))
  hash <- khmd:::.khmd_hash;ver <- "KHMD_UTMK_1KM_V1"
  doc <- list(schema="KHMD_PRICE_PANEL_V1",unit="reported_observation_value_statistics",grid_version=ver,grid=list(version=ver),database="price.sqlite")
  for(pair in list(c("source_release","source"),c("spatial_result","spatial"),c("count_release","count")))
    doc[[pair[1]]] <- list(path=paste0(pair[2],".json"),sha256=hash(file.path(root,paste0(pair[2],".json"))))
  doc$source_release_sha256 <- doc$source_release$sha256;doc$spatial_manifest_sha256 <- doc$spatial_result$sha256;doc$count_release_sha256 <- doc$count_release$sha256
  con <- DBI::dbConnect(RSQLite::SQLite(),file.path(root,"price.sqlite"))
  DBI::dbExecute(con,"CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
  for(k in c("schema","unit","grid_version","source_release_sha256","spatial_manifest_sha256","count_release_sha256")) DBI::dbExecute(con,"INSERT INTO metadata VALUES(?,?)",params=list(k,doc[[k]]))
  d <- data.frame(grid_id=paste0(ver,":1:2"),quarter="2025Q1",transaction_family="RENT",rent_subtype=c("ALL","JEONSE","MONTHLY_RENT","UNKNOWN"),metric="monthly_rent",n_obs=c(4L,1L,2L,1L),n_valid=c(3L,1L,2L,0L),n_excluded=c(1L,0L,0L,1L),q25=c("0","0","7.5",NA),median=c("0","0","15",NA),q75=c("15","0","22.5",NA))
  DBI::dbWriteTable(con,"statistics",d);DBI::dbWriteTable(con,"metric_totals",d[c("transaction_family","rent_subtype","metric","n_obs","n_valid","n_excluded")]);DBI::dbDisconnect(con)
  f <- list(root=root,db=file.path(root,"price.sqlite"),manifest=file.path(root,"release.json"),doc=doc);price_reseal(f)
}
price_reseal <- function(f) {
  con <- file(f$db,"rb");on.exit(close(con));blocks <- list()
  repeat { b <- readBin(con,"raw",n=4096L);if(!length(b)) break;blocks[[length(blocks)+1L]] <- digest::digest(b,algo="sha256",serialize=FALSE) }
  f$doc$database_integrity <- list(algorithm="sha256",bytes=file.info(f$db)$size,chunk_bytes=4096L,chunk_sha256=blocks)
  jsonlite::write_json(f$doc,f$manifest,auto_unbox=TRUE,pretty=TRUE);f
}
test_that("price default pooled level cannot silently sum subtypes", {
  f <- price_fixture();p <- khmd_open_price_panel(f$manifest)
  expect_s3_class(p,"khmd_price_panel")
  x <- khmd_price_collect(p,metric="monthly_rent",quarter="2025Q1",family="RENT")
  expect_equal(nrow(x),1L);expect_equal(x$n_obs,4L);expect_identical(x$median,"0")
  y <- khmd_price_collect(p,rent_subtype=c("JEONSE","MONTHLY_RENT","UNKNOWN"))
  expect_equal(sum(y$n_obs),4L);expect_true(is.na(y$median[y$rent_subtype=="UNKNOWN"]))
  expect_equal(khmd_price_quality(p,rent_subtype="MONTHLY_RENT")$n_valid,2L)
  expect_equal(khmd_price_metadata(p)$unit,"reported_observation_value_statistics")
  expect_equal(nrow(khmd_price_collect(p,quarter="2011Q1")),0L)
})
test_that("price chunks preserve explicit levels and enforce filters", {
  p <- khmd_open_price_panel(price_fixture()$manifest);sizes <- integer()
  s <- khmd_price_stream(p,function(x) { sizes <<- c(sizes,nrow(x));FALSE },rent_subtype=c("JEONSE","MONTHLY_RENT","UNKNOWN"),chunk_size=2L)
  expect_equal(sizes,2L);expect_equal(s$rows,2L);expect_true(s$stopped_by_callback)
  expect_error(khmd_price_collect(p,metric="not-a-metric"),"metric")
  expect_error(khmd_price_collect(p,rent_subtype=NULL),"subtype")
  expect_error(khmd_price_collect(p,grid_id="OLD:1:2"),"wrong version")
  expect_error(khmd_price_collect(p,quarter="2025Q5"),"quarter")
  expect_error(khmd_price_collect(p,limit=10001),"limit")
})
test_that("price reference mixing and byte corruption are refused", {
  f <- price_fixture();p <- khmd_open_price_panel(f$manifest)
  expect_error(khmd_open_price_panel(f$manifest,expected_sha256=paste(rep("0",64),collapse="")),"SHA")
  altered <- p;altered$document$grid_version <- "OTHER"
  expect_error(khmd_price_collect(altered),"metadata changed")
  writeLines('changed',file.path(f$root,"source.json"));expect_error(khmd_price_collect(p),"SHA mismatch")
  f <- price_fixture();f$doc$grid$version <- "OLD";price_reseal(f)
  expect_error(khmd_open_price_panel(f$manifest),"mixed grid")
  f <- price_fixture();con <- file(f$db,"r+b");seek(con,where=100);writeBin(as.raw(0),con);close(con)
  expect_error(khmd_open_price_panel(f$manifest),"SHA block")
})

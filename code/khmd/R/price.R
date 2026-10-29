.khmd_price_binding <- function(panel) {
  .khmd_need(inherits(panel, "khmd_price_panel"), "expected a khmd_price_panel")
  .khmd_need(.khmd_hash(panel$manifest) == panel$sha256, "price manifest changed")
  .khmd_need(identical(digest::digest(panel$document, algo="sha256"),panel$document_digest), "price metadata changed")
  for (name in c("source_release","spatial_result","count_release"))
    .khmd_need(.khmd_hash(panel$references[[name]]) == panel$document[[name]]$sha256,paste(name,"SHA mismatch"))
  .khmd_panel_blocks(panel$database,panel$document$database_integrity)
}
.khmd_price_with <- function(panel,fun) {
  .khmd_price_binding(panel)
  result <- .khmd_with_store(panel$database,function(con) {
    .khmd_need(all(c("statistics","metric_totals","metadata") %in% DBI::dbListTables(con)),"price tables missing")
    m <- DBI::dbGetQuery(con,"SELECT key,value FROM metadata")
    .khmd_need(!anyDuplicated(m$key),"duplicate price metadata")
    v <- stats::setNames(as.list(m$value),m$key)
    for (k in c("schema","grid_version","source_release_sha256","spatial_manifest_sha256","count_release_sha256","unit"))
      .khmd_need(identical(v[[k]],panel$document[[k]]),paste("mixed price binding",k))
    fun(con)
  })
  .khmd_price_binding(panel);result
}
khmd_open_price_panel <- function(manifest,expected_sha256=NULL,path_map=NULL) {
  .khmd_need(.khmd_scalar(manifest)&&file.exists(manifest),"price manifest missing")
  manifest <- normalizePath(manifest,winslash="/",mustWork=TRUE);hash <- .khmd_hash(manifest)
  if(!is.null(expected_sha256)) .khmd_need(.khmd_scalar(expected_sha256)&&hash==tolower(expected_sha256),"price manifest SHA mismatch")
  doc <- .khmd_json(paste(readLines(manifest,encoding="UTF-8",warn=FALSE),collapse="\n"))
  .khmd_need(identical(doc$schema,"KHMD_PRICE_PANEL_V1")&&identical(doc$unit,"reported_observation_value_statistics"),"unsupported price semantics")
  .khmd_need(identical(doc$grid_version,doc$grid$version),"mixed grid version")
  for(pair in list(c("source_release_sha256","source_release"),c("spatial_manifest_sha256","spatial_result"),c("count_release_sha256","count_release")))
    .khmd_need(identical(doc[[pair[1]]],doc[[pair[2]]]$sha256),"mixed reference release")
  refs <- lapply(doc[c("source_release","spatial_result","count_release")],function(x) .khmd_path(x$path,dirname(manifest),path_map))
  p <- structure(list(manifest=manifest,sha256=hash,document=doc,document_digest=digest::digest(doc,algo="sha256"),references=refs,database=.khmd_path(doc$database,dirname(manifest),path_map)),class="khmd_price_panel")
  .khmd_price_with(p,function(con) {
    .khmd_need(all(c("grid_id","quarter","transaction_family","rent_subtype","metric","n_obs","n_valid","n_excluded","q25","median","q75") %in% DBI::dbListFields(con,"statistics")),"price schema mismatch")
    invisible(TRUE)
  });p
}
khmd_price_metadata <- function(panel) .khmd_price_with(panel,function(con) panel$document)
.khmd_price_filter <- function(panel,metric,grid_id,quarter,family,rent_subtype,quality=FALSE) {
  .khmd_need(!quality || (is.null(grid_id)&&is.null(quarter)),"national metric quality has no grid/quarter filter")
  f <- .khmd_panel_filter(panel,grid_id,quarter,family,NULL,FALSE)
  .khmd_need(is.null(metric)||(is.character(metric)&&length(metric)>0L&&!anyNA(metric)&&all(metric %in% c("sale_amount","sale_amount_m2","deposit","monthly_rent"))),"invalid metric")
  .khmd_need(is.character(rent_subtype)&&length(rent_subtype)>0L&&!anyNA(rent_subtype)&&all(rent_subtype %in% c("ALL","JEONSE","MONTHLY_RENT","UNKNOWN")),"explicit rent_subtype required")
  for (item in list(list(metric,"metric"),list(rent_subtype,"rent_subtype"))) {
    if(is.null(item[[1]])) next
    clause <- paste0(item[[2]]," IN (",paste(rep("?",length(item[[1]])),collapse=","),")")
    f$where <- paste(f$where,if(nzchar(f$where)) "AND" else "WHERE",clause)
    f$params <- c(f$params,as.list(item[[1]]))
  };f
}
khmd_price_collect <- function(panel,metric=NULL,grid_id=NULL,quarter=NULL,family=NULL,rent_subtype="ALL",limit=1000L,offset=0L) {
  limit <- .khmd_bound(limit,"limit")
  .khmd_need(length(offset)==1L&&is.numeric(offset)&&is.finite(offset)&&offset>=0&&offset==floor(offset),"invalid offset")
  f <- .khmd_price_filter(panel,metric,grid_id,quarter,family,rent_subtype)
  .khmd_price_with(panel,function(con) DBI::dbGetQuery(con,paste("SELECT * FROM statistics",f$where,"ORDER BY grid_id,quarter,transaction_family,rent_subtype,metric LIMIT ? OFFSET ?"),params=c(f$params,list(limit,offset))))
}
khmd_price_quality <- function(panel,metric=NULL,family=NULL,rent_subtype="ALL") {
  f <- .khmd_price_filter(panel,metric,NULL,NULL,family,rent_subtype,TRUE)
  .khmd_price_with(panel,function(con) DBI::dbGetQuery(con,paste("SELECT * FROM metric_totals",f$where,"ORDER BY transaction_family,rent_subtype,metric"),params=f$params))
}
khmd_price_stream <- function(panel,callback,metric=NULL,grid_id=NULL,quarter=NULL,family=NULL,rent_subtype="ALL",chunk_size=1000L) {
  .khmd_need(is.function(callback),"callback must be a function");chunk_size <- .khmd_bound(chunk_size,"chunk_size")
  f <- .khmd_price_filter(panel,metric,grid_id,quarter,family,rent_subtype)
  .khmd_price_with(panel,function(con) {
    res <- DBI::dbSendQuery(con,paste("SELECT * FROM statistics",f$where,"ORDER BY grid_id,quarter,transaction_family,rent_subtype,metric"))
    on.exit(DBI::dbClearResult(res),add=TRUE)
    if(length(f$params)) DBI::dbBind(res,f$params)
    rows <- chunks <- 0;stopped <- FALSE
    repeat {
      batch <- DBI::dbFetch(res,n=chunk_size);if(!nrow(batch)) break
      rows <- rows+nrow(batch);chunks <- chunks+1L
      if(identical(callback(batch),FALSE)) { stopped <- TRUE;break }
    }
    invisible(list(rows=rows,chunks=chunks,stopped_by_callback=stopped))
  })
}

\name{khmd_price_panel}
\alias{khmd_open_price_panel}
\alias{khmd_price_metadata}
\alias{khmd_price_collect}
\alias{khmd_price_quality}
\alias{khmd_price_stream}
\title{Read explicitly bound price and rent descriptive statistics}
\usage{
khmd_open_price_panel(manifest, expected_sha256 = NULL, path_map = NULL)
khmd_price_metadata(panel)
khmd_price_collect(panel, metric = NULL, grid_id = NULL, quarter = NULL,
  family = NULL, rent_subtype = "ALL", limit = 1000L, offset = 0L)
khmd_price_quality(panel, metric = NULL, family = NULL, rent_subtype = "ALL")
khmd_price_stream(panel, callback, metric = NULL, grid_id = NULL,
  quarter = NULL, family = NULL, rent_subtype = "ALL", chunk_size = 1000L)
}
\arguments{
\item{manifest}{External price release JSON path.}
\item{expected_sha256}{Optional exact manifest SHA-256.}
\item{path_map}{Optional named character vector of path prefix remappings.}
\item{panel}{An opened price panel.}
\item{metric}{NULL or sale_amount, sale_amount_m2, deposit, monthly_rent.}
\item{grid_id}{NULL or grid IDs including the bound grid version.}
\item{quarter}{NULL or contract quarters such as 2025Q1.}
\item{family}{NULL, SALE or RENT.}
\item{rent_subtype}{Explicit levels: ALL (default pooled), JEONSE, MONTHLY_RENT, UNKNOWN. ALL and subtypes overlap and must not be added together. SALE uses ALL.}
\item{limit}{Maximum returned rows, at most 10000.}
\item{offset}{Nonnegative row offset.}
\item{callback}{Function receiving each bounded data frame; FALSE stops.}
\item{chunk_size}{Rows per chunk, at most 10000.}
}
\value{An external panel handle, metadata list, data frame, or invisible stream summary. Quantiles are decimal text (or NA), preserving the 50-digit serialization. Counts are observation occurrences, not unique transactions.}
\description{Reads sparse descriptive statistics and metric-specific valid denominators without raw reparsing. Retains explicit zero, repeated occurrences and the recorded cancellation policy. Verifies manifest, source/spatial/count references and database SHA blocks before and after reads. No synthetic zero groups or price index interpretation is introduced.}
\details{Monetary values are nominal KRW 10000; sale_amount_m2 is per square metre, monthly_rent is per month. Type-7 quantiles use exact rational interpolation before Decimal50 rounding. Converting returned decimal text to R doubles is a caller choice that loses precision. Missing/invalid counts are separate from explicit zero. National metric_totals are alternative denominators for each metric and level; never sum them as a population count. Linkage to 2026 reference parcels does not certify contract-time locations.}
\examples{
\dontrun{
p <- khmd_open_price_panel("price/release_manifest.json")
x <- khmd_price_collect(p, metric = "sale_amount_m2", quarter = "2025Q1",
  family = "SALE", limit = 5)
q <- khmd_price_quality(p, metric = "monthly_rent", rent_subtype = "MONTHLY_RENT")
khmd_price_stream(p, function(x) { print(head(x)); FALSE }, chunk_size = 7)
}
}

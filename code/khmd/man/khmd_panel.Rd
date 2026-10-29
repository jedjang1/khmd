\name{khmd_panel}
\alias{khmd_open_panel}
\alias{khmd_panel_metadata}
\alias{khmd_panel_collect}
\alias{khmd_panel_quality}
\alias{khmd_panel_stream}
\alias{khmd_panel_totals}
\title{Read a SHA-bound sparse observation-count panel}
\description{Reads an external grid-quarter-family panel and separate acquisition-region
assignment denominators. Counts retain repeated observations, not unique transactions.
No absent combination is filled with zero. No price or historical-location inference is made.}
\usage{
khmd_open_panel(manifest, expected_sha256 = NULL, path_map = NULL)
khmd_panel_metadata(panel)
khmd_panel_collect(panel, grid_id = NULL, quarter = NULL, family = NULL,
                   limit = 1000L, offset = 0L)
khmd_panel_quality(panel, query_region = NULL, quarter = NULL, family = NULL,
                   limit = 1000L, offset = 0L)
khmd_panel_stream(panel, callback, dataset = c("panel", "quality"),
                  grid_id = NULL, quarter = NULL, family = NULL,
                  query_region = NULL, chunk_size = 1000L)
khmd_panel_totals(panel)
}
\arguments{
\item{manifest}{External panel release JSON path.}
\item{expected_sha256}{Optional exact manifest SHA-256 pin.}
\item{path_map}{Named character prefix mappings for moved external data.}
\item{panel}{Object returned by \code{khmd_open_panel}.}
\item{grid_id}{Character vector of exact versioned grid identifiers.}
\item{quarter}{Character vector using YYYYQ1 through YYYYQ4.}
\item{family}{SALE or RENT, or both.}
\item{query_region}{Acquisition-region labels, not historical boundaries.}
\item{limit}{Maximum returned groups, from 1 to 10000.}
\item{offset}{Nonnegative number of groups to skip in stable key order.}
\item{callback}{Receives a data frame per chunk. Return exactly FALSE to stop.}
\item{dataset}{Panel groups or region quality rows.}
\item{chunk_size}{Rows per chunk, from 1 to 10000.}
}
\details{The manifest, upstream manifests and bounded SHA-256 blocks of the database
are checked before and after each read. Database metadata must agree with the source,
spatial release and grid version. The published whole-file SHA is also supplied for
external verification. Data remain outside the package. Grid counts omit unassigned
observations; quality rows retain all input denominators. Region assignment rates are
not grid completeness rates. Reference parcels describe their stated snapshot, not
necessarily contract-time locations. Filters use bound SQL parameters.
\code{khmd_panel_totals} sums the already aggregated panel, not the original observations.}
\value{An external-release object, metadata list, bounded data frame, aggregate totals,
or an invisible streaming receipt with rows, chunks and early-stop status.}
\examples{
\dontrun{
p <- khmd_open_panel("/data/panel/release_manifest.json")
khmd_panel_collect(p, quarter = "2025Q1", family = "RENT", limit = 5)
khmd_panel_quality(p, quarter = "2025Q1", family = "RENT", limit = 50)
khmd_panel_stream(p, function(x) { print(x); FALSE }, chunk_size = 7)
khmd_panel_totals(p)
}
}

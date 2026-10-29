\name{khmd_open_release}
\alias{khmd_open_release}
\alias{khmd_files}
\alias{khmd_collect}
\alias{khmd_stream}
\alias{khmd_count}
\alias{khmd_field}
\alias{print.khmd_release}
\title{Read an Explicit CSV Observation Release}
\description{Read external, existing SQLite observation stores using exact selected file SHA bindings. No CSV reparsing, transaction deduplication, API merging or spatial assignment is performed.}
\usage{
khmd_open_release(manifest, expected_sha256 = NULL, path_map = NULL)
khmd_files(release)
khmd_collect(release, family = NULL, province = NULL, start = NULL,
  end = NULL, region = NULL, limit = 1000L, offset = 0)
khmd_stream(release, callback, family = NULL, province = NULL,
  start = NULL, end = NULL, region = NULL, chunk_size = 1000L)
khmd_count(release, family = NULL, province = NULL, start = NULL,
  end = NULL, region = NULL)
khmd_field(rows, field)
\method{print}{khmd_release}(x, ...)
}
\arguments{
\item{manifest}{Path to a UTF-8 JSON manifest with an explicit \code{active_files} list.}
\item{expected_sha256}{Optional independently recorded SHA-256 of the manifest. Recommended for a pinned release.}
\item{path_map}{Optional named character vector mapping old directory prefixes to new locations. Relative store paths resolve against the manifest directory. No directory is downloaded or created.}
\item{release, x}{A \code{khmd_release} object. Treat it as immutable and reopen to change releases.}
\item{family}{NULL or a character vector containing SALE and/or RENT.}
\item{province}{NULL or exact collection query province labels. This is not a claim about historical jurisdiction.}
\item{start, end}{Inclusive ISO contract dates or Date scalars. NULL means no bound.}
\item{region}{NULL or stored CSV region labels. Matches an exact label or its whitespace-delimited descendants, for example a full province and district prefix. No geocoding or historical boundary inference occurs.}
\item{limit}{Maximum collected rows, an integer from 1 to 10000. Results are intentionally bounded.}
\item{offset}{Nonnegative row offset after filters, in manifest file order then source ordinal order. Large offsets may require scanning; use streaming instead.}
\item{callback}{A function receiving one data frame chunk. Return values are ignored. Errors stop and propagate. Retaining chunks in the callback can consume memory.}
\item{chunk_size}{Rows per streaming callback, from 1 to 10000. Default 1000.}
\item{rows}{Observation rows returned by collect or stream.}
\item{field}{One original field name. No imputation or normalization is performed.}
\item{...}{Reserved print arguments.}
}
\value{Open returns a release object. Files returns selected file provenance, query scope, encoding and acquisition-time status. Collect returns a bounded data frame with source IDs, row/byte positions, unchanged JSON raw values/states/derived values and provenance. Stream invisibly returns the number of rows delivered. Count returns family, query province, reported region, year-month and occurrence counts. Field returns observation ID, original character value and stored state; a missing schema field has NA value and ABSENT state.}
\details{
Counts are observation occurrences, not unique transactions. Repeated original occurrences are preserved. Observation IDs are source row identifiers, not transaction IDs. Query geography and reported labels do not establish historical spatial boundaries.

Connections are read-only and query-only with bounded SQLite page cache and file-backed temporary storage. Filtering and aggregation occur in SQLite, one selected file at a time. No national database conversion is required. Aggregation can scan selected files without loading their observation rows into R. Very broad groupings can still produce many output groups.

Only active manifest entries are read. Query overlaps, duplicate selected SHA, missing files, registry binding mismatches and dirty selected files are rejected. Opening checks manifest identity, schema, stored registry scope and row totals; it does not rehash raw CSV files or all SQLite rows. It is not a substitute for source ingestion or a cryptographic proof that a mutable database has not changed. Keep processed stores immutable and do not write concurrently. A manifest SHA verifies the manifest bytes, not every external database byte.

The package has no bundled housing data. UNKNOWN acquisition timestamps, empty strings, whitespace, explicit zero, display dashes and absent fields remain distinct. No automatic source correction, current-address substitution or API population merge is provided.
}
\examples{
\dontrun{
library(khmd)
r <- khmd_open_release(Sys.getenv("KHMD_RELEASE_MANIFEST"),
                       expected_sha256 = Sys.getenv("KHMD_RELEASE_SHA256"))
khmd_files(r)
x <- khmd_collect(r, family = "RENT", start = "2014-06-01",
                  end = "2014-06-30", limit = 5)
khmd_count(r, family = "RENT", start = "2014-06-01", end = "2014-06-30")
khmd_stream(r, function(chunk) cat(nrow(chunk), "rows\n"),
            family = "RENT", start = "2014-06-01", end = "2014-06-30")
}
}

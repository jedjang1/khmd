"""Offline metric design audit and synthetic arithmetic; no grid-quarter execution.

The arithmetic helpers are reference tests only. Their existence does not approve
an input field, an economic-event universe, a rental classification, or execution.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

SALE = "MOLIT_APT_SALE_DETAIL"
RENT = "MOLIT_APT_RENT"
TYPED_PATHS = {
    SALE: "data/interim/production_typed_v0_1/sales_items_typed.csv",
    RENT: "data/interim/production_typed_v0_1/rent_items_typed.csv",
}
SALE_SPEC = "metadata/khmd_grid_quarter_sale_metric_spec_v0_1.csv"
RENT_SPEC = "metadata/khmd_grid_quarter_rent_metric_spec_v0_1.csv"
QUANTILE_CONTRACT = "metadata/khmd_aggregation_quantile_contract_v0_1.json"
EVIDENCE = "metadata/khmd_aggregation_metric_semantic_evidence_v0_1.json"
ARTIFACT_PATHS = (SALE_SPEC, RENT_SPEC, QUANTILE_CONTRACT, EVIDENCE)
PRECISION = 50
SUPPORTED_TYPES = ("JEONSE", "MONTHLY_RENT")
UNKNOWN_TYPE = "UNKNOWN"
SMALL_N_THRESHOLD = 5
SPEC_COLUMNS = (
    "metric_name", "source_id", "metric_class", "inclusion_status",
    "source_columns", "formula", "unit", "unit_evidence_status",
    "denominator", "validity_policy", "null_policy", "interpretation_limit",
    "evidence_reference", "production_executable", "definition",
    "aggregation_function", "quantile_method", "public_interpretation",
)


def _decimal(value: object) -> Decimal | None:
    """Read explicit NULL or finite Decimal-compatible synthetic inputs only."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("Binary floats and booleans are not decimal metric inputs")
    if not isinstance(value, (str, int, Decimal)):
        raise TypeError("Expected Decimal, decimal text, integer, or NULL")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Metric input must be finite")
    return result


def _decimal_fraction(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = PRECISION
        context.rounding = ROUND_HALF_EVEN
        return Decimal(value.numerator) / Decimal(value.denominator)


def _quantile_fraction(values: Iterable[Fraction], probability: Decimal) -> Fraction | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = Fraction(len(ordered) - 1) * Fraction(probability)
    lower = index.numerator // index.denominator
    weight = index - lower
    if lower == len(ordered) - 1:
        return ordered[lower]
    return ordered[lower] + weight * (ordered[lower + 1] - ordered[lower])


def quantile_type7(values: Iterable[object], probability: object) -> Decimal | None:
    """Synthetic Hyndman-Fan type 7, exact rational interpolation, Decimal output.

    Only explicit NULLs are excluded. Invalid/nonfinite values raise rather than
    silently changing the denominator. The result is rounded once to 50 significant
    decimal digits, ties to even. This never reads production tables.
    """
    p = _decimal(probability)
    if p is None or not Decimal(0) <= p <= Decimal(1):
        raise ValueError("Probability must be in [0, 1]")
    parsed = (_decimal(value) for value in values)
    answer = _quantile_fraction((Fraction(value) for value in parsed if value is not None), p)
    return None if answer is None else _decimal_fraction(answer)


def synthetic_unit_price(amount: object, area: object) -> Decimal | None:
    """Synthetic amount/positive-area arithmetic; not an approval of m2 units."""
    numerator, denominator = _decimal(amount), _decimal(area)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _decimal_fraction(Fraction(numerator) / Fraction(denominator))


def synthetic_unit_price_quantile(pairs: Iterable[tuple[object, object]], probability: object) -> Decimal | None:
    """Quantile of exact row ratios, never ratio of separately computed medians."""
    p = _decimal(probability)
    if p is None or not Decimal(0) <= p <= Decimal(1):
        raise ValueError("Probability must be in [0, 1]")
    ratios = []
    for amount, area in pairs:
        numerator, denominator = _decimal(amount), _decimal(area)
        if numerator is not None and denominator is not None and denominator > 0:
            ratios.append(Fraction(numerator) / Fraction(denominator))
    answer = _quantile_fraction(ratios, p)
    return None if answer is None else _decimal_fraction(answer)


def classify_lease_type(row: Mapping[str, object]) -> str:
    """The current source has no approved JEONSE/MONTHLY_RENT mapping."""
    return UNKNOWN_TYPE


def synthetic_supported_type_shares(labels: Iterable[str]) -> dict:
    """Test denominator arithmetic with explicitly supplied synthetic labels.

    This does not invoke classify_lease_type or infer labels from money/status.
    A future source classification needs separate evidence and version approval.
    """
    counts = Counter(labels)
    if set(counts) - set((*SUPPORTED_TYPES, UNKNOWN_TYPE)):
        raise ValueError("Unsupported synthetic rental-type label")
    total = sum(counts.values())
    known = sum(counts[label] for label in SUPPORTED_TYPES)
    return {
        "n_eligible_rent_records": total,
        "n_known_supported_lease_type": known,
        "n_unknown_lease_type": counts[UNKNOWN_TYPE],
        "known_type_shares": {
            label: _decimal_fraction(Fraction(counts[label], known)) if known else None
            for label in SUPPORTED_TYPES
        },
        "unknown_type_record_share": _decimal_fraction(Fraction(counts[UNKNOWN_TYPE], total)) if total else None,
    }


def metric_small_n_status(n_valid_metric: int) -> str:
    if isinstance(n_valid_metric, bool) or not isinstance(n_valid_metric, int) or n_valid_metric < 0:
        raise ValueError("Metric denominator must be a nonnegative integer")
    if n_valid_metric == 0:
        return "NO_VALID_VALUE"
    if n_valid_metric == 1:
        return "SINGLE_VALID_RECORD"
    return "FEW_VALID_RECORDS_REVIEW" if n_valid_metric < SMALL_N_THRESHOLD else "FIVE_OR_MORE_VALID_RECORDS"


def quantile_contract() -> dict:
    return {
        "contract_version": "0.1", "status": "SYNTHETIC_REFERENCE_ONLY_PENDING_SEMANTIC_GATES",
        "production_executable": False,
        "library": "Python standard library decimal.Decimal and fractions.Fraction; explicit implementation",
        "algorithm": "Hyndman-Fan type 7; zero-based h=(n-1)*p; j=floor(h); Q=x[j]+(h-j)*(x[j+1]-x[j]); p=1 returns max",
        "probabilities": {"q25": "0.25", "median": "0.5", "q75": "0.75"},
        "numeric_type": "Finite decimal text/Decimal/integer converted exactly to rational; interpolation and row ratios exact; final Decimal",
        "binary_float_permitted": False,
        "decimal_output_precision_significant_digits": PRECISION,
        "decimal_output_rounding": "ROUND_HALF_EVEN once at final serialization/result",
        "input_missing_policy": "Exclude explicit None or empty typed cell only after source parse-status validation; never replace with zero",
        "invalid_input_policy": "Reject nonfinite, malformed or binary-float arithmetic inputs; source unavailable parse slots excluded with reason",
        "n_zero": "NULL statistic and n_valid_metric=0", "n_one": "All three quantiles equal sole finite valid value",
        "ties": "Retain every eligible record occurrence, including ties; no deduplication",
        "sale_amount_unit": "KRW_10K; nominal reported amount, no inflation conversion",
        "sale_unit_price_formula_candidate": "For each eligible record with finite amount and area>0 form exact amount/area ratio; take type7 quantiles of ratios",
        "sale_unit_price_unit_candidate": "KRW_10K/m2",
        "sale_unit_price_status": "BLOCKED_AREA_UNIT_NOT_EXPLICITLY_CONFIRMED",
        "ratio_of_medians_permitted_as_unit_price": False,
        "rent_type_classification_status": "BLOCKED_NO_APPROVED_LEASE_TYPE_MAPPING",
        "rent_type_current_output": "UNKNOWN for every source record; no monetary-value inference",
        "lease_type_candidate_vocabulary": ["JEONSE", "MONTHLY_RENT", "UNKNOWN"],
        "other_lease_type_policy": "OTHER requires a future separately approved extension; no present mapping",
        "type_share_candidate_denominator": "Spatially assigned, aggregation-eligible RENT source record occurrences with an explicitly supported known lease type in the cell-quarter; not households, residents or housing stock",
        "unknown_type_policy": "Exclude UNKNOWN from known-type share denominator; separately retain unknown count and unknown/all-eligible-record share; no known types => NULL known-type shares",
        "type_share_activation": "Blocked until approved classification and economic-event/record universe closure; helper accepts synthetic labels only",
        "small_n_convention_version": "market_metric_reporting_v0_1",
        "small_n_threshold": SMALL_N_THRESHOLD,
        "small_n_policy": "n=0 => NO_VALID_VALUE and NULL; n=1 => SINGLE_VALID_RECORD; 2<=n<5 => FEW_VALID_RECORDS_REVIEW; n>=5 => FIVE_OR_MORE_VALID_RECORDS; values unsuppressed, no adequacy claim",
        "small_n_basis": "Metric-specific valid denominator; reporting convention independent of prior coverage <30; not privacy or significance threshold",
        "actual_grid_quarter_rows": 0,
    }


def metric_specs(source: str) -> list[dict[str, str]]:
    if source not in (SALE, RENT):
        raise ValueError("Unknown source")
    rows = []
    assigned = "Spatially assigned source record occurrences in the candidate cell-quarter"
    eligible = "Spatially assigned aggregation-universe record occurrences under a separately closed eligibility policy"
    closure = "metadata/core_semantics_closure_v0_1.csv"

    def add(name, category, status, columns, formula, unit="record", unit_status="not_applicable", denominator=eligible,
            validity="Pending event eligibility closure; no actual computation", null="0 for a count only in an existing observed row", limit="Record count is not a unique economic-transaction count", evidence=closure):
        if name.startswith(("median_", "q25_", "q75_")):
            function, quantile = "quantile of finite valid eligible record values", "Hyndman-Fan type7; exact rational interpolation; final Decimal precision50 ROUND_HALF_EVEN"
        elif name == "n_distinct_parcels":
            function, quantile = "COUNT DISTINCT frozen non-null parcel_reference_pnu", "not_applicable"
        elif name.startswith("n_"):
            function, quantile = "COUNT source record occurrences satisfying explicit formula predicate", "not_applicable"
        elif name.endswith("_share"):
            function, quantile = "numerator record count / explicitly stated nonzero denominator record count", "not_applicable"
        else:
            function, quantile = "not_selected_for_aggregation", "not_applicable"
        rows.append(dict(zip(SPEC_COLUMNS, (name, source, category, status, columns, formula, unit, unit_status,
                                               denominator, validity, null, limit, evidence, "false", formula,
                                               function, quantile, limit))))

    event_gate = "CANDIDATE_BLOCKED_EVENT_SEMANTICS"
    add("n_assigned_records", "SUPPORTING", event_gate, "occurrence_id;spatial_assignment_status", "count occurrences with SPATIAL_PROXY_ASSIGNED", denominator=assigned)
    add("n_aggregation_eligible_records", "CORE", event_gate, "occurrence_id;derived_event_eligibility", "count occurrences under approved aggregation-universe policy")
    add("n_distinct_parcels", "SUPPORTING", event_gate, "parcel_reference_pnu", "count distinct non-null frozen linked parcel identifiers", unit="parcel", limit="Distinct linked parcels, not complexes or households")
    for name, flag, value in (("n_boundary_sensitive_records", "parcel_crosses_grid_boundary", "true"), ("n_pos_dominant_disagreement_records", "parcel_pos_equals_dominant_grid", "false")):
        add(name, "DIAGNOSTIC", event_gate, flag, "count eligible occurrences with frozen flag=" + value, limit="Parcel representative proxy sensitivity; not source/linkage coverage")
        add(name.removeprefix("n_").removesuffix("_records") + "_assigned_share", "DIAGNOSTIC", event_gate, flag,
            name + "/n_aggregation_eligible_records", unit="proportion", null="NULL when denominator=0", limit="Eligible assigned-record denominator only; unresolved records have no known grid")
    add("exclusive_use_area", "SUPPORTING", "AVAILABLE_TYPED_CANDIDATE_UNIT_ONLY", "exclusive_use_area__parsed", "Availability inventory only; no selected aggregate", "m2", "unit_supported_but_not_explicit", null="NULL if typed slot unavailable", limit="Official concept-level m2 evidence does not confirm API-field unit explicitly")
    add("floor_number", "DIAGNOSTIC", "AVAILABLE_NOT_SELECTED", "floor_number__parsed", "Availability inventory only; no selected aggregate", "floor_number", "unit_confirmed", limit="Signed floor value; no basement inference and not a core market measure")
    add("construction_year_component", "DIAGNOSTIC", "AVAILABLE_NOT_SELECTED", "construction_year_component__parsed", "Availability inventory only; no selected aggregate", "year_component", limit="No building-age or complete construction-date derivation")
    add("transaction_count", "NOT_SUITABLE", "PROHIBITED_UNIQUE_EVENT_INTERPRETATION", "occurrence_id", "Not available", limit="Source occurrence multiplicity does not establish unique economic events")
    if source == SALE:
        add("n_valid_sale_amount", "SUPPORTING", event_gate, "sale_sale_amount__parsed;sale_sale_amount__parse_status", "count finite parsed reported amounts among eligible records", unit_status="unit_confirmed", validity="Parsed finite amount; raw/zero semantics preserved; no imputation")
        add("n_valid_unit_price", "SUPPORTING", "BLOCKED_AREA_UNIT_NOT_EXPLICITLY_CONFIRMED", "sale_sale_amount__parsed;exclusive_use_area__parsed", "candidate count finite amount and confirmed-unit area>0", validity="Formula design only; unit gate not satisfied")
        for prefix, probability in (("median", "0.5"), ("q25", "0.25"), ("q75", "0.75")):
            add(prefix + "_sale_amount", "CORE", event_gate, "sale_sale_amount__parsed", "type7(reported eligible amount,p=" + probability + ")", "KRW_10K", "unit_confirmed", validity="Finite parsed source amounts; zeros preserved as unresolved reported values", null="NULL when n_valid_sale_amount=0", limit="Nominal reported source amounts; event semantics and completeness limitations must accompany result")
            add(prefix + "_unit_price_m2", "CORE_CANDIDATE_BLOCKED", "BLOCKED_AREA_UNIT_NOT_EXPLICITLY_CONFIRMED", "sale_sale_amount__parsed;exclusive_use_area__parsed", "type7(exact per-record amount/positive area,p=" + probability + ")", "KRW_10K/m2", "area_unit_supported_but_not_explicit", validity="Blocked in real data; synthetic helper tests arithmetic only", null="NULL unless metric unit gate cleared and n_valid_unit_price>0", limit="Never median(amount)/median(area); no imputation or inflation adjustment")
        add("mean_sale_amount", "NOT_SUITABLE", "OPTIONAL_NOT_SELECTED", "sale_sale_amount__parsed", "Not selected for v0.1 core", "KRW_10K", "unit_confirmed", limit="Median and interquartile spread candidate only; no unnecessary additional statistic")
    else:
        for name, field in (("deposit", "rent_rental_deposit"), ("monthly_rent", "rent_monthly_rent")):
            add("n_parsed_" + name, "DIAGNOSTIC", "AVAILABILITY_AUDIT_ONLY", field + "__parsed;" + field + "__parse_status", "profile count of parseable values; not an approved market denominator", validity="Finite lexical parse does not establish lease type or true economic zero")
            add("all_record_" + name + "_distribution", "NOT_SUITABLE", "NOT_SELECTED_LEASE_TYPES_UNRESOLVED", field + "__parsed", "No distribution computed or executable", "KRW_10K", "unit_confirmed", limit="Do not pool JEONSE and MONTHLY_RENT into one market price; only availability audited")
        add("lease_type", "CORE_CANDIDATE_BLOCKED", "BLOCKED_NO_APPROVED_LEASE_TYPE_MAPPING", "No authoritative lease monetary-type field identified", "UNKNOWN for every current record", "category", limit="contractType new/renewal tokens do not identify JEONSE versus MONTHLY_RENT; zero rent does not imply JEONSE")
        for name in ("n_known_supported_lease_type", "n_unknown_lease_type"):
            add(name, "DIAGNOSTIC", "CANDIDATE_BLOCKED_EVENT_SEMANTICS", "derived_lease_type", "count explicitly known/unknown categories; present evidence yields all UNKNOWN", limit="No monetary-value or household-status inference")
        known = eligible + " with an officially supported known lease monetary type"
        for category in ("jeonse", "monthly_rent"):
            add(category + "_record_share", "CORE_CANDIDATE_BLOCKED", "BLOCKED_NO_APPROVED_LEASE_TYPE_MAPPING", "derived_lease_type", "n_" + category + "/n_known_supported_lease_type", "proportion", denominator=known, null="NULL when n_known_supported_lease_type=0 or classification gate unresolved", limit="Observed supported-type contract-record share; never household, resident or stock share")
        add("unknown_type_record_share", "DIAGNOSTIC", event_gate, "derived_lease_type", "n_unknown_lease_type/n_aggregation_eligible_records", "proportion", null="NULL if no eligible records", limit="Unknowns visible in all-eligible-record denominator; not imputed into known categories")
        for subtype, component, field in (("jeonse", "deposit", "rent_rental_deposit"), ("monthly_rent", "deposit", "rent_rental_deposit"), ("monthly_rent", "monthly_rent", "rent_monthly_rent")):
            add("n_valid_" + subtype + "_" + component, "SUPPORTING", "BLOCKED_NO_APPROVED_LEASE_TYPE_MAPPING", field + "__parsed;derived_lease_type", "candidate count valid typed amount within supported subtype", null="NULL while type gate unresolved; otherwise count in existing row", limit="Cannot derive subtype from monthlyRent zero/positive pattern")
            for prefix, probability in (("median", "0.5"), ("q25", "0.25"), ("q75", "0.75")):
                add(prefix + "_" + subtype + "_" + component, "CORE_CANDIDATE_BLOCKED", "BLOCKED_NO_APPROVED_LEASE_TYPE_MAPPING", field + "__parsed;derived_lease_type", "type7(supported subtype reported amount,p=" + probability + ")", "KRW_10K", "unit_confirmed", null="NULL while type gate unresolved or subtype valid n=0", limit="Separate deposit and monthly-rent measures; no rent conversion")
        add("new_renewal_contract_tokens", "DIAGNOSTIC", "RAW_TOKEN_PROFILE_ONLY", "contractType;contractType__values_json", "profile exact raw values and missingness by year and pilot_area_id", "category", limit="Observed 신규/갱신 tokens; official field label 계약구분 lacks approved exhaustive code mapping; uneven availability excludes core shares", evidence="metadata/api_response_fields.csv#MOLIT_APT_RENT/contractType")
        add("renewal_right_use_tokens", "DIAGNOSTIC", "RAW_TOKEN_PROFILE_ONLY", "useRRRight;useRRRight__values_json", "profile raw usage token and missingness", "category", limit="Blank is not non-use; no household move or household identity inference")
        add("prior_contract_amounts", "NOT_SUITABLE", "BLOCKED_RAW_ONLY", "preDeposit;preMonthlyRent", "No numerical aggregation", "unconfirmed", "unit_supported_but_not_explicit", limit="Frozen core closure disallows prior-amount numeric interpretation")
        add("rent_per_m2", "NOT_SUITABLE", "BLOCKED_AREA_UNIT_AND_LEASE_TYPE", "exclusive_use_area__parsed;rent_rental_deposit__parsed;rent_monthly_rent__parsed", "No calculation", "candidate_KRW_10K/m2", "unit_supported_but_not_explicit", limit="Both classification and explicit area-unit gates remain unresolved")
        add("equivalent_rent", "NOT_SUITABLE", "PROHIBITED_NO_APPROVED_CONVERSION_MODEL", "deposit;monthlyRent", "No conversion", "not_applicable", limit="No capitalization model, inflation adjustment, deposit-equivalent or rent-equivalent measure")
    return rows


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def profile_typed_metrics(root: Path, source: str) -> dict:
    """Availability counts only, without grouping by grid-quarter or statistics."""
    fields = ("exclusive_use_area", "floor_number", "construction_year_component") + (("sale_sale_amount",) if source == SALE else ("rent_rental_deposit", "rent_monthly_rent"))
    profiles = {field: {"parse_status_counts": Counter(), "unit_counts": Counter(), "unit_status_counts": Counter(), "zero_count": 0, "negative_count": 0, "positive_count": 0} for field in fields}
    categorical = {field: {"values": Counter(), "states": Counter(), "by_contract_year": defaultdict(Counter), "by_pilot_area_id": defaultdict(Counter)} for field in (("contractType", "useRRRight") if source == RENT else ())}
    source_rows = 0
    with (root / TYPED_PATHS[source]).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            source_rows += 1
            for field, profile in profiles.items():
                status = row[field + "__parse_status"]
                profile["parse_status_counts"][status] += 1
                profile["unit_counts"][row[field + "__unit"]] += 1
                profile["unit_status_counts"][row[field + "__unit_status"]] += 1
                value = _decimal(row[field + "__parsed"])
                if status == "parsed" and value is None:
                    raise ValueError("Parsed metric missing value")
                if status != "parsed" and value is not None:
                    raise ValueError("Unavailable metric unexpectedly populated")
                if value is not None:
                    profile["zero_count" if value == 0 else "negative_count" if value < 0 else "positive_count"] += 1
            for field, profile in categorical.items():
                value = row[field]
                profile["values"][value] += 1
                profile["states"][row[field + "__state"]] += 1
                profile["by_contract_year"][row["contract_year_component__parsed"]][value] += 1
                profile["by_pilot_area_id"][row["pilot_area_id"]][value] += 1
    for profile in categorical.values():
        profile["missing_or_whitespace_count"] = sum(count for value, count in profile["values"].items() if not value.strip())
        profile["missing_rate_exact"] = f"{profile['missing_or_whitespace_count']}/{source_rows}"
    return {"source_id": source, "row_count": source_rows, "numeric_availability": profiles, "raw_category_availability": categorical,
            "lease_type_policy": "ALL_UNKNOWN_NO_APPROVED_MAPPING" if source == RENT else "not_applicable",
            "approved_known_lease_type_count": 0 if source == RENT else None,
            "unknown_lease_type_count": source_rows if source == RENT else None,
            "production_grid_quarter_rows": 0}


def build_metric_artifacts(root: Path) -> dict:
    """Write only this new design layer; does not compute production aggregates."""
    root = Path(root)
    collisions = [path for path in ARTIFACT_PATHS if (root / path).exists()]
    if collisions:
        raise FileExistsError("Metric design artifacts already exist; refusing overwrite: " + "; ".join(collisions))
    manifest_path = "metadata/khmd_pilot_final_release_manifest_v0_1.json"
    manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
    for path in TYPED_PATHS.values():
        if _hash(root / path) != manifest["artifacts_sha256"][path]:
            raise ValueError("Typed input differs from authoritative final release: " + path)
    source_fields = {"dealAmount", "deposit", "monthlyRent", "excluUseAr", "floor", "buildYear", "contractType", "useRRRight", "preDeposit", "preMonthlyRent"}
    official = [row for row in _read_csv(root / "metadata/api_response_fields.csv") if row["field_name"] in source_fields]
    closure = [row for row in _read_csv(root / "metadata/core_semantics_closure_v0_1.csv") if row["source_field"] in source_fields]
    source_paths = set(TYPED_PATHS.values()) | {
        manifest_path, "metadata/khmd_pilot_final_release_freeze_v0_1.json",
        "metadata/core_semantics_closure_v0_1.csv", "metadata/core_semantics_official_evidence_v0_1.json",
        "metadata/core_semantics_closure_freeze_v0_1_candidate.json",
        "metadata/canonical_semantics_freeze_v0_2_candidate.json", "metadata/api_response_fields.csv",
        "metadata/typed_column_dictionary_v0_1.csv", "docs/api_schema_notes.md",
    }
    source_paths.update(row["source_file"] for row in official)
    evidence = {
        "version": "0.1", "status": "METRIC_CANDIDATES_WITH_UNRESOLVED_SEMANTIC_GATES",
        "scope": "Read-only full-source availability profile; no grid-quarter group or production distribution computed",
        "input_sha256": {path: _hash(root / path) for path in sorted(source_paths)},
        "official_preserved_response_dictionary_rows": official,
        "frozen_core_closure_rows": closure,
        "profiles": {source: profile_typed_metrics(root, source) for source in (SALE, RENT)},
        "sale_amount": "Typed KRW_10K unit confirmed; candidate record-level nominal distributions remain subject to event-universe gate",
        "sale_unit_price": "BLOCKED: area m2 has concept-level official support but unit_supported_but_not_explicit; do not upgrade frozen evidence",
        "rent_monetary_fields": "Typed deposit/monthlyRent KRW_10K units confirmed; literal zero economic meaning remains unresolved",
        "rent_type": "BLOCKED: contractType is contract division with observed new/renewal tokens; no approved lease monetary type or monetary-value derivation; all UNKNOWN",
        "rent_core_money_distributions": "Subtype distributions blocked; pooled all-record distributions not selected/executable",
        "rent_long_fact_mapping": {
            "grain": "grid_id/year_quarter/lease_type",
            "candidate_lease_type_vocabulary": ["JEONSE", "MONTHLY_RENT", "UNKNOWN"],
            "median_jeonse_deposit": {"lease_type": "JEONSE", "column": "median_deposit"},
            "q25_jeonse_deposit": {"lease_type": "JEONSE", "column": "q25_deposit"},
            "q75_jeonse_deposit": {"lease_type": "JEONSE", "column": "q75_deposit"},
            "median_monthly_rent_deposit": {"lease_type": "MONTHLY_RENT", "column": "median_deposit"},
            "q25_monthly_rent_deposit": {"lease_type": "MONTHLY_RENT", "column": "q25_deposit"},
            "q75_monthly_rent_deposit": {"lease_type": "MONTHLY_RENT", "column": "q75_deposit"},
            "median_monthly_rent_monthly_rent": {"lease_type": "MONTHLY_RENT", "column": "median_monthly_rent"},
            "q25_monthly_rent_monthly_rent": {"lease_type": "MONTHLY_RENT", "column": "q25_monthly_rent"},
            "q75_monthly_rent_monthly_rent": {"lease_type": "MONTHLY_RENT", "column": "q75_monthly_rent"},
            "n_valid_jeonse_deposit": {"lease_type": "JEONSE", "column": "n_valid_deposit"},
            "n_valid_monthly_rent_deposit": {"lease_type": "MONTHLY_RENT", "column": "n_valid_deposit"},
            "n_valid_monthly_rent_monthly_rent": {"lease_type": "MONTHLY_RENT", "column": "n_valid_monthly_rent"},
            "UNKNOWN_policy": "Monetary statistics and valid monetary metric denominators MUST be NULL while lease type semantics remain unapproved; retain source-record diagnostics only",
            "JEONSE_monthly_rent_policy": "NULL/not applicable, not fabricated zero",
            "OTHER_policy": "Not in current vocabulary; requires separate approved extension",
            "execution_authorized": False,
        },
        "rent_new_renewal": "Raw observed token availability diagnostic only; not core share, household move, or tenure transition",
        "type_share_denominator": quantile_contract()["type_share_candidate_denominator"],
        "raw_preservation": "No source field edits, no row deletion, no deduplication, no cancellation removal",
        "aggregation_event_gate": "Must be satisfied separately; these metric candidates do not grant execution permission",
        "actual_sale_grid_quarter_rows": 0, "actual_rent_grid_quarter_rows": 0,
        "production_aggregation": 0, "network_requests": 0,
    }
    for source, path in ((SALE, SALE_SPEC), (RENT, RENT_SPEC)):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=SPEC_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(metric_specs(source))
    for path, value in ((QUANTILE_CONTRACT, quantile_contract()), (EVIDENCE, evidence)):
        with (root / path).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return {"status": evidence["status"], "artifact_paths": list(ARTIFACT_PATHS), "metric_spec_rows": {SALE: len(metric_specs(SALE)), RENT: len(metric_specs(RENT))},
            "source_rows_profiled": {source: evidence["profiles"][source]["row_count"] for source in (SALE, RENT)},
            "sale_unit_price_blocked": True, "rent_type_metrics_blocked": True, "production_aggregation_rows": 0}

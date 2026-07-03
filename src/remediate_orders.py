"""
Remediate data-quality issues in the customer_orders batch.

Remediation steps (mirrors wdi_flow_blueprint.yaml stages):
  1. load raw data
  2. detect DQ issues on the raw data and write pre-remediation report
  3. normalize fields (standardize_fields stage)
  4. enrich missing customer_id from customer_dimension (enrich_customer_id stage)
  5. repair malformed email from customer_dimension (repair_email_from_dimension stage)
  6. deduplicate exact duplicate order_ids, keep earliest ingested_at (dedupe_orders stage)
  7. quarantine negative order_total and non-USD rows (split_quarantine stage)
  8. remediate invalid ship_dates (remediate_dates stage)
  9. write remediated (gold) and quarantine outputs (write_gold / write_quarantine stages)

Real IBM SDK calls are in integration/create_or_update_flow_with_sdk.py behind the
sdk_credentials_available() gate so this script runs without IBM credentials.
"""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = ROOT / "assets/data/customer_orders_raw.csv"
CUSTOMER_DIM = ROOT / "assets/reference/customer_dimension.csv"
DQ_RULES = ROOT / "assets/config/dq_rules.yaml"
REMEDIATION_POLICY = ROOT / "assets/config/remediation_policy.yaml"

REMEDIATED_OUT = ROOT / "assets/data/customer_orders_remediated.csv"
QUARANTINE_OUT = ROOT / "assets/data/customer_orders_quarantine.csv"
REPORT_DIR = ROOT / "reports"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TERMINAL_STATUSES = {"CANCELLED", "RETURNED"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_policy() -> dict:
    with REMEDIATION_POLICY.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _business_date(policy: dict) -> str:
    return policy.get("current_business_date", "2026-07-03")


# ---------------------------------------------------------------------------
# Stage 1: normalize fields (standardize_fields)
# ---------------------------------------------------------------------------

def normalize_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Trim, case-normalize, and parse typed columns."""
    out = df.copy()
    for col in ["email", "status", "currency", "source_system"]:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip()
    out["email"] = out["email"].str.lower()
    out["status"] = out["status"].str.upper()
    out["currency"] = out["currency"].str.upper()
    out["order_total"] = pd.to_numeric(out["order_total"], errors="coerce")
    out["order_date"] = pd.to_datetime(out["order_date"], errors="coerce").dt.date
    out["ship_date"] = pd.to_datetime(out["ship_date"], errors="coerce").dt.date
    return out


# ---------------------------------------------------------------------------
# Stage 2: enrich_customer_id
# ---------------------------------------------------------------------------

def enrich_customer_id(df: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """Fill missing customer_id by matching normalized email against customer_dimension."""
    # Build email -> customer_id lookup from dimension
    email_to_id = dim.set_index("primary_email")["customer_id"].to_dict()

    out = df.copy()
    missing_mask = out["customer_id"].isna() | (out["customer_id"].astype("string").str.strip() == "")
    out.loc[missing_mask, "customer_id"] = out.loc[missing_mask, "email"].map(email_to_id)
    return out


# ---------------------------------------------------------------------------
# Stage 3: repair_email_from_dimension
# ---------------------------------------------------------------------------

def repair_email_from_dimension(df: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """When email is malformed and customer_id exists, replace with primary_email."""
    cid_to_email = dim.set_index("customer_id")["primary_email"].to_dict()

    out = df.copy()
    malformed_mask = out["email"].apply(
        lambda e: not EMAIL_RE.match(str(e)) if pd.notna(e) else True
    )
    has_cid_mask = out["customer_id"].notna() & (out["customer_id"].astype("string").str.strip() != "")
    repair_mask = malformed_mask & has_cid_mask

    out.loc[repair_mask, "email"] = out.loc[repair_mask, "customer_id"].map(cid_to_email)
    return out


# ---------------------------------------------------------------------------
# Stage 4: dedupe_orders  →  also populates quarantine rows
# ---------------------------------------------------------------------------

def dedupe_orders(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop exact duplicate order_id records, keeping earliest ingested_at.

    Returns (clean_df, quarantine_rows) where quarantine_rows have dq_action='deduplicated'.
    """
    out = df.copy()
    out["ingested_at"] = pd.to_datetime(out["ingested_at"], errors="coerce", utc=True)
    # Sort so earliest ingested_at sorts first; break ties by original index position.
    out = out.sort_values(["order_id", "ingested_at"], kind="stable")
    duplicated_mask = out.duplicated(subset=["order_id"], keep="first")

    quarantine_rows = out[duplicated_mask].copy()
    quarantine_rows["dq_action"] = "deduplicated"
    quarantine_rows["dq_reason"] = "exact duplicate order_id removed; earliest ingested_at kept"

    clean = out[~duplicated_mask].copy()
    # Restore ingested_at as string for output consistency
    clean["ingested_at"] = clean["ingested_at"].astype(str)
    quarantine_rows["ingested_at"] = quarantine_rows["ingested_at"].astype(str)
    return clean, quarantine_rows


# ---------------------------------------------------------------------------
# Stage 5: split_quarantine (negative totals + non-USD)
# ---------------------------------------------------------------------------

def split_quarantine(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Send negative order_total and non-USD rows to quarantine.

    Returns (clean_df, quarantine_rows).
    """
    negative_mask = df["order_total"] < 0
    non_usd_mask = df["currency"] != "USD"
    quarantine_mask = negative_mask | non_usd_mask

    quarantine_rows = df[quarantine_mask].copy()
    quarantine_rows["dq_action"] = "quarantined"
    reasons = []
    for _, row in quarantine_rows.iterrows():
        parts = []
        if row["order_total"] < 0:
            parts.append("negative order_total")
        if row["currency"] != "USD":
            parts.append("non-USD currency; awaiting FX pipeline")
        reasons.append("; ".join(parts))
    quarantine_rows["dq_reason"] = reasons

    clean = df[~quarantine_mask].copy()
    return clean, quarantine_rows


# ---------------------------------------------------------------------------
# Stage 6: remediate_dates
# ---------------------------------------------------------------------------

def remediate_dates(df: pd.DataFrame, business_date_str: str) -> pd.DataFrame:
    """Clear ship_date when it violates business rules and mark for reprocessing.

    Rules (from remediation_policy.yaml):
    - ship_date < order_date  → set ship_date null, set status PROCESSING unless terminal
    - ship_date > business_date → set ship_date null, set status PROCESSING unless terminal
    """
    import datetime
    business_date = datetime.date.fromisoformat(business_date_str)

    out = df.copy()
    for idx, row in out.iterrows():
        ship = row["ship_date"]
        order = row["order_date"]
        if pd.isna(ship):
            continue
        invalid = False
        if pd.notna(order) and ship < order:
            invalid = True
        if ship > business_date:
            invalid = True
        if invalid:
            out.at[idx, "ship_date"] = None
            if str(row["status"]) not in TERMINAL_STATUSES:
                out.at[idx, "status"] = "PROCESSING"
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    policy = _load_policy()
    business_date = _business_date(policy)

    # ---- Load raw data -------------------------------------------------------
    raw = pd.read_csv(RAW_DATA, dtype={"order_id": "string", "customer_id": "string"})
    dim = pd.read_csv(CUSTOMER_DIM, dtype={"customer_id": "string"})

    # ---- Pre-remediation DQ detection (writes reports/) ----------------------
    # Import here so src/ stays importable in tests without circular deps.
    from dq_detect import load_rules, detect_issues, write_issue_outputs, normalize_for_detection

    rules_config = load_rules(DQ_RULES)
    issues = detect_issues(raw, rules_config, current_business_date=business_date)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_issue_outputs(issues, raw, output_dir=REPORT_DIR)

    # ---- Remediation pipeline ------------------------------------------------
    df = normalize_fields(raw)
    df = enrich_customer_id(df, dim)
    df = repair_email_from_dimension(df, dim)
    df, dedup_quarantine = dedupe_orders(df)
    df, value_quarantine = split_quarantine(df)
    df = remediate_dates(df, business_date)

    # ---- Write outputs -------------------------------------------------------
    REMEDIATED_OUT.parent.mkdir(parents=True, exist_ok=True)
    QUARANTINE_OUT.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(REMEDIATED_OUT, index=False)

    quarantine = pd.concat([dedup_quarantine, value_quarantine], ignore_index=True)
    quarantine.to_csv(QUARANTINE_OUT, index=False)

    # ---- Console summary -----------------------------------------------------
    total = len(raw)
    remediated = len(df)
    quarantined = len(quarantine)
    print(f"[DQ-148] Remediation complete.")
    print(f"  Raw rows      : {total}")
    print(f"  Remediated    : {remediated}  → {REMEDIATED_OUT.relative_to(ROOT)}")
    print(f"  Quarantined   : {quarantined}  → {QUARANTINE_OUT.relative_to(ROOT)}")
    print(f"  DQ report     : {(REPORT_DIR / 'dq_summary.json').relative_to(ROOT)}")
    print(f"  Invalid rows  : {(REPORT_DIR / 'invalid_rows.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()

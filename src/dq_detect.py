"""
Data-quality detection adapter.

Local demo mode uses pandas so the repository runs without IBM credentials.
When the `data-intelligence-sdk` package is installed, this module can be extended to
construct wxdi.dq_validator Validator/PandasValidator objects from dq_rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
import json
import re
from typing import Iterable

import pandas as pd
import yaml

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class DQIssue:
    row_number: int
    order_id: str
    rule_id: str
    column: str
    severity: str
    value: object
    message: str
    remediation: str


def load_rules(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rule_lookup(rules_config: dict) -> dict[str, dict]:
    return {rule["id"]: rule for rule in rules_config["rules"]}


def normalize_for_detection(df: pd.DataFrame) -> pd.DataFrame:
    """Apply non-destructive standardization used by both detection and remediation."""
    out = df.copy()
    for col in ["email", "status", "currency", "source_system"]:
        out[col] = out[col].astype("string").str.strip()
    out["email"] = out["email"].str.lower()
    out["status"] = out["status"].str.upper()
    out["currency"] = out["currency"].str.upper()
    out["order_total"] = pd.to_numeric(out["order_total"], errors="coerce")
    out["order_date"] = pd.to_datetime(out["order_date"], errors="coerce").dt.date
    out["ship_date"] = pd.to_datetime(out["ship_date"], errors="coerce").dt.date
    return out


def detect_issues(
    df: pd.DataFrame,
    rules_config: dict,
    current_business_date: str = "2026-07-03",
) -> list[DQIssue]:
    """Detect the rules needed for the mock issue."""
    normalized = normalize_for_detection(df)
    rules = _rule_lookup(rules_config)
    business_date = date.fromisoformat(current_business_date)
    issues: list[DQIssue] = []

    duplicated_order_ids = normalized["order_id"].duplicated(keep=False)

    for pos, (idx, row) in enumerate(normalized.iterrows()):
        row_number = int(pos) + 2  # CSV line number including header
        order_id = str(row.get("order_id", ""))

        def add(rule_id: str, value: object, message: str):
            rule = rules[rule_id]
            issues.append(
                DQIssue(
                    row_number=row_number,
                    order_id=order_id,
                    rule_id=rule_id,
                    column=rule["column"],
                    severity=rule["severity"],
                    value=None if pd.isna(value) else value,
                    message=message,
                    remediation=rule["remediation"],
                )
            )

        if pd.isna(row["order_id"]) or str(row["order_id"]).strip() == "":
            add("ORDER_ID_NOT_NULL", row["order_id"], "order_id is required")

        if bool(duplicated_order_ids.loc[idx]):
            add("ORDER_ID_UNIQUE", row["order_id"], "order_id appears more than once in this batch")

        if pd.isna(row["customer_id"]) or str(row["customer_id"]).strip() == "":
            add("CUSTOMER_ID_NOT_NULL", row["customer_id"], "customer_id is required for customer joins")

        if pd.isna(row["email"]) or not EMAIL_RE.match(str(row["email"])):
            add("EMAIL_FORMAT", row["email"], "email must be RFC-like name@domain.tld format")

        if row["status"] not in set(rules["STATUS_VALID"]["values"]):
            add("STATUS_VALID", row["status"], "status is not in the accepted status code set")

        if pd.isna(row["order_total"]) or float(row["order_total"]) < float(rules["ORDER_TOTAL_NON_NEGATIVE"]["min"]):
            add("ORDER_TOTAL_NON_NEGATIVE", row["order_total"], "order_total must be zero or greater")

        if row["currency"] not in set(rules["CURRENCY_VALID"]["values"]):
            add("CURRENCY_VALID", row["currency"], "only USD rows are supported in the gold table")

        ship_date = row["ship_date"]
        order_date = row["order_date"]
        if pd.notna(ship_date) and pd.notna(order_date) and ship_date < order_date:
            add("SHIP_DATE_NOT_BEFORE_ORDER_DATE", ship_date.isoformat(), "ship_date cannot be earlier than order_date")
        if pd.notna(ship_date) and ship_date > business_date:
            add("SHIP_DATE_NOT_IN_FUTURE", ship_date.isoformat(), "ship_date cannot be after the business date")

    return issues


def summarize_issues(issues: Iterable[DQIssue], total_rows: int) -> dict:
    issues = list(issues)
    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    impacted_order_ids: set[str] = set()
    for issue in issues:
        by_rule[issue.rule_id] = by_rule.get(issue.rule_id, 0) + 1
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        impacted_order_ids.add(issue.order_id)

    invalid_rows = len(impacted_order_ids)
    return {
        "total_rows": total_rows,
        "invalid_rows": invalid_rows,
        "valid_rows": total_rows - invalid_rows,
        "issue_count": len(issues),
        "pass_rate": round((total_rows - invalid_rows) / total_rows, 4) if total_rows else 1.0,
        "issues_by_rule": dict(sorted(by_rule.items())),
        "issues_by_severity": dict(sorted(by_severity.items())),
        "impacted_order_ids": sorted(impacted_order_ids),
    }


def write_issue_outputs(issues: list[DQIssue], input_df: pd.DataFrame, output_dir: str | Path = "reports") -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_issues(issues, total_rows=len(input_df))

    with (output_dir / "dq_summary.json").open("w", encoding="utf-8") as f:
        json.dump({"summary": summary, "issues": [asdict(i) for i in issues]}, f, indent=2, default=str)

    issue_df = pd.DataFrame(asdict(i) for i in issues)
    if issue_df.empty:
        issue_df = pd.DataFrame(columns=["row_number", "order_id", "rule_id", "column", "severity", "value", "message", "remediation"])
    issue_df.to_csv(output_dir / "invalid_rows.csv", index=False)
    return summary


def sdk_available() -> bool:
    """Check whether the real IBM data-intelligence SDK import path is available."""
    try:
        import wxdi.dq_validator  # noqa: F401
        return True
    except Exception:
        return False


def build_wxdi_validator_placeholder(rules_config: dict):
    """Template for implementing the real SDK adapter.

    IBM's current SDK examples use wxdi.dq_validator.Validator, ValidationRule,
    LengthCheck/ValidValuesCheck/CompletenessCheck/RangeCheck/etc., plus
    wxdi.dq_validator.integrations.PandasValidator for DataFrames. Keep this
    boundary isolated so the local demo remains runnable without credentials.
    """
    if not sdk_available():
        raise RuntimeError("data-intelligence-sdk is not installed; use local pandas mode")
    raise NotImplementedError("Map dq_rules.yaml to wxdi.dq_validator rules here")

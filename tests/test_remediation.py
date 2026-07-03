from pathlib import Path
import subprocess
import sys
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run_remediation():
    subprocess.run([sys.executable, "src/remediate_orders.py"], cwd=ROOT, check=True)


def test_acceptance_criteria_outputs_exist():
    run_remediation()
    assert (ROOT / "assets/data/customer_orders_remediated.csv").exists()
    assert (ROOT / "assets/data/customer_orders_quarantine.csv").exists()
    assert (ROOT / "reports/dq_summary.json").exists()
    assert (ROOT / "reports/invalid_rows.csv").exists()


def test_clean_output_has_no_duplicate_order_ids_and_valid_values():
    run_remediation()
    clean = pd.read_csv(ROOT / "assets/data/customer_orders_remediated.csv", dtype={"order_id": "string"})
    assert clean["order_id"].duplicated().sum() == 0
    assert (clean["currency"] == "USD").all()
    assert (clean["order_total"] >= 0).all()
    assert set(clean["status"]).issubset({"PENDING", "PROCESSING", "SHIPPED", "CANCELLED", "RETURNED"})


def test_clean_ship_dates_are_valid_for_business_date():
    run_remediation()
    clean = pd.read_csv(ROOT / "assets/data/customer_orders_remediated.csv", parse_dates=["order_date", "ship_date"])
    ship = clean[clean["ship_date"].notna()]
    assert (ship["ship_date"] >= ship["order_date"]).all()
    assert (ship["ship_date"] <= pd.Timestamp("2026-07-03")).all()


def test_quarantine_contains_unrecoverable_and_duplicate_rows():
    run_remediation()
    quarantine = pd.read_csv(ROOT / "assets/data/customer_orders_quarantine.csv", dtype={"order_id": "string"})
    assert set(quarantine["order_id"]) == {"10008", "10010", "10013"}
    assert set(quarantine["dq_action"]) == {"quarantined", "deduplicated"}


def test_pre_remediation_report_detects_issue_context():
    run_remediation()
    report = json.loads((ROOT / "reports/dq_summary.json").read_text())
    summary = report["summary"]
    assert summary["total_rows"] == 15
    assert summary["issue_count"] == 8
    assert summary["issues_by_rule"]["ORDER_ID_UNIQUE"] == 2
    assert "10013" in summary["impacted_order_ids"]

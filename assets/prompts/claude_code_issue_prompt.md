# Claude Code prompt: use Git issue context to write remediation code

You are working in this repository. Use the mock GitHub issue as the source of truth:

`assets/issues/ISSUE_148_customer_orders_dq_regression.md`

Goal: implement production-shaped starter code for data-quality detection and remediation using the watsonx.data intelligence SDK/MCP for data-quality context and watsonx.data integration SDK/MCP for pipeline/flow lifecycle context.

## Context to load first

Read these files before writing code:

1. `assets/issues/ISSUE_148_customer_orders_dq_regression.md`
2. `assets/config/dq_rules.yaml`
3. `assets/config/remediation_policy.yaml`
4. `assets/data/customer_orders_raw.csv`
5. `assets/reference/customer_dimension.csv`
6. `integration/wdi_flow_blueprint.yaml`

## Implementation instructions

- Keep `src/remediate_orders.py` runnable locally with pandas only.
- Keep `src/dq_detect.py` as the adapter boundary for the real watsonx.data intelligence SDK.
- Do not hard-code row numbers; detect by keys and rules.
- Preserve original raw records in quarantine output.
- Add remediation metadata columns:
  - `dq_action`
  - `dq_reason`
  - `dq_issue_ids`
  - `dq_remediated_at`
- Write DQ evidence to `reports/dq_summary.json`.
- Write a compact invalid-row sample to `reports/invalid_rows.csv`.
- Add/keep tests in `tests/test_remediation.py` for the issue acceptance criteria.

## MCP usage pattern

Use the MCP servers only for environment-backed operations. For this mock repo, treat the MCP calls as prompts/intents, not required local execution.

Suggested natural-language MCP steps:

1. Ask watsonx.data intelligence MCP: “Find asset `demo_catalog.sales_curated.customer_orders`, show data-quality checks, latest score, failed rules, lineage, and downstream impacted assets.”
2. Ask watsonx.data intelligence MCP: “Create or update DQ rules matching `assets/config/dq_rules.yaml` and publish reusable rules to the catalog/project.”
3. Ask watsonx.data integration MCP: “Create or update batch flow `flow_customer_orders_daily` from `integration/wdi_flow_blueprint.yaml`, add normalization, reference lookup, dedupe, validation, quarantine, and publish stages.”
4. Ask watsonx.data integration MCP: “Run the flow in dry-run mode and return job metrics, logs, and row counts.”
5. Commit code and reference this issue in the commit message.

## Commit message

```text
fix(dq): remediate customer orders SLA breach

Uses DQ-148 issue context to add local detection/remediation starter logic,
quarantine outputs, evidence reporting, and watsonx.data integration flow intent.
```

# watsonx.data intelligence + watsonx.data integration DQ remediation demo

This starter repo is a mock issue-driven demo for detecting and remediating data-quality regressions using:

- **watsonx.data intelligence MCP/SDK** for data-quality context, checks, evidence, lineage, and impact analysis
- **watsonx.data integration MCP/SDK** for creating/updating the pipeline stages that prevent recurrence
- **Claude Code** as the coding agent that reads a GitHub issue and repository context, then writes remediation code

The local demo runs without IBM credentials. IBM MCP/SDK integration points are represented as clean adapters and prompts so you can swap in real environment calls later.

## Scenario

A legacy CRM source was added to the daily `customer_orders` ingestion flow. The flow loaded records into the gold table without the same normalization, deduplication, customer lookup, currency, and date checks used by the existing Shopify path.

The mock incident is captured in:

```text
assets/issues/ISSUE_148_customer_orders_dq_regression.md
```

The issue has the required sections:

- What happened
- Why it happened
- What’s impacted
- How to fix it

## Repo layout

```text
.
├── CLAUDE.md
├── README.md
├── .claude
│   └── skills
│       └── wxdi-remediate      # SDK-grounded remediation skill
├── assets
│   ├── config
│   │   ├── dq_rules.yaml
│   │   └── remediation_policy.yaml
│   ├── data
│   │   ├── customer_orders_raw.csv
│   │   ├── customer_orders_remediated.csv          # generated
│   │   └── customer_orders_quarantine.csv          # generated
│   ├── issues
│   │   └── ISSUE_148_customer_orders_dq_regression.md
│   ├── prompts
│   │   └── claude_code_issue_prompt.md
│   └── reference
│       ├── customer_dimension.csv
│       └── valid_status_codes.csv
├── integration
│   ├── create_or_update_flow_with_sdk.py
│   ├── mcp_runbook.md
│   └── wdi_flow_blueprint.yaml
├── reports
│   ├── dq_summary.json                             # generated
│   └── invalid_rows.csv                            # generated
├── src
│   ├── dq_detect.py
│   └── remediate_orders.py
└── tests
    └── test_remediation.py
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/remediate_orders.py
pytest -q
```

Expected result:

```text
5 passed
```

Generated outputs:

- `assets/data/customer_orders_remediated.csv`
- `assets/data/customer_orders_quarantine.csv`
- `reports/dq_summary.json`
- `reports/invalid_rows.csv`

## Demo flow

1. **Data-quality detection**
   - Read `assets/data/customer_orders_raw.csv`
   - Apply rules from `assets/config/dq_rules.yaml`
   - Write issue evidence to `reports/dq_summary.json` and `reports/invalid_rows.csv`

2. **Mock GitHub issue**
   - Use `assets/issues/ISSUE_148_customer_orders_dq_regression.md`
   - Optional command:

   ```bash
   gh issue create \
     --title "[DQ-148] Customer orders feed breached gold-table SLA after legacy CRM cutover" \
     --body-file assets/issues/ISSUE_148_customer_orders_dq_regression.md \
     --label data-quality \
     --label watsonx.data-intelligence \
     --label watsonx.data-integration \
     --label claude-code-ready
   ```

3. **Claude Code remediation**
   - Open `assets/prompts/claude_code_issue_prompt.md`
   - Claude Code reads the issue, config, input data, and flow blueprint
   - Claude Code updates local code and tests

4. **watsonx.data integration prevention**
   - Use `integration/wdi_flow_blueprint.yaml` to create/update the batch flow
   - Use `integration/mcp_runbook.md` for natural-language MCP prompts

## What the local remediation does

- normalizes `status`, `currency`, and `email`
- fills missing `customer_id` from `customer_dimension.csv`
- repairs malformed email from the customer dimension when possible
- drops exact duplicate `order_id` records into quarantine evidence
- quarantines negative order totals and unsupported currency rows
- clears invalid/future ship dates and marks records for fulfillment reprocessing
- writes audit metadata columns: `dq_action`, `dq_reason`, `dq_issue_ids`, `dq_remediated_at`

## IBM integration notes

Use `.mcp/claude_desktop_config.example.json` as a starting point for local MCP setup.

- `wxdi-mcp-server`: data intelligence MCP server
- `data-intg-mcp`: data integration MCP server
- `watsonx-data-lakehouse-mcp-optional`: optional lakehouse MCP server for direct lakehouse/table exploration

Use `src/dq_detect.py` as the adapter boundary for the real `data-intelligence-sdk` DQ validator implementation.

Use `integration/create_or_update_flow_with_sdk.py` and `integration/wdi_flow_blueprint.yaml` as the adapter boundary for the real watsonx.data integration SDK/MCP flow implementation. Set `WATSONX_API_KEY` + `WXDI_PROJECT_ID` to exercise the real SDK path (`apply_blueprint_via_sdk`); without them the script only prints the blueprint intent.

Claude Code skill: `.claude/skills/wxdi-remediate/` documents the grounded `ibm-watsonx-data-integration` SDK call sequence (auth, flows, stages, jobs/metrics) for extending the adapter above.

## References checked while creating this starter

- IBM watsonx.data intelligence SDK for Python docs
- IBM watsonx.data intelligence MCP server docs and repository
- IBM watsonx.data integration SDK for Python docs
- IBM watsonx.data integration MCP server docs
- IBM watsonx.data quality SLA and remediation docs

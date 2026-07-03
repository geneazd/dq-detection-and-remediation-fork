# MCP runbook

## watsonx.data intelligence MCP

Use this to discover the asset, inspect quality, lineages, downstream impact, and rule configuration.

Example prompts:

```text
Find asset demo_catalog.sales_curated.customer_orders. Show latest data quality score, failed checks, quality SLA status, lineage, and downstream impacted assets.
```

```text
Create or update data quality rules for demo_catalog.sales_curated.customer_orders using the rules in assets/config/dq_rules.yaml. Publish reusable rules to the catalog if supported in this environment.
```

## watsonx.data integration MCP

Use this to create/update the pipeline and dry-run the remediation flow.

```text
Create or update batch flow flow_customer_orders_daily from integration/wdi_flow_blueprint.yaml. Include normalization, customer lookup, exact duplicate removal, DQ validation, quarantine routing, date remediation, and gold-table merge stages.
```

```text
Run flow_customer_orders_daily in dry-run mode. Return stage metrics, failed rows, validation logs, and recommended fixes.
```

## Claude Code handoff

After the issue is created, ask Claude Code:

```text
Use GitHub issue DQ-148 and this repository context to implement and test the data quality remediation. Keep the local demo runnable without IBM credentials; put real MCP/SDK calls behind adapter boundaries.
```

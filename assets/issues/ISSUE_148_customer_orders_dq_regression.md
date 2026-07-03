# [DQ-148] Customer orders feed breached gold-table SLA after legacy CRM cutover

Labels: `data-quality`, `watsonx.data-intelligence`, `watsonx.data-integration`, `incident`, `claude-code-ready`
Assignee: `commerce-data-eng`
Priority: P1
Detected by: watsonx.data intelligence data-quality rule run
Pipeline: watsonx.data integration batch flow `flow_customer_orders_daily`
Business date: 2026-07-03

## What happened

The `sales_curated.customer_orders` gold table failed the daily data-quality SLA. The mock detection report shows multiple validation failures in the July 3 daily ingestion window:

- duplicate `order_id`: `10010` appears twice
- missing `customer_id`: order `10004`
- malformed email: order `10005` has `elena@example`
- negative `order_total`: order `10008` has `-14.99`
- future `ship_date`: order `10009` has `2026-07-08` while the business date is `2026-07-03`
- invalid temporal order: order `10012` shipped before it was ordered
- non-USD currency: order `10013` has `EUR`
- lowercase status: orders `10010` duplicated as `shipped`

## Why it happened

A legacy CRM source was added to the watsonx.data integration flow without the same standardization and reference-data checks used by the Shopify source path. The immediate causes are:

1. The integration flow accepted mixed-case status codes and did not normalize them before publishing to the curated table.
2. The flow did not enforce uniqueness on `order_id` after the union stage.
3. The flow did not enrich missing `customer_id` values from the customer dimension.
4. The flow did not validate cross-field date logic before load.
5. Currency conversion is not implemented in this starter scenario, so non-USD rows must be quarantined until the FX enrichment step exists.

## What’s impacted

- Asset: `demo_catalog.sales_curated.customer_orders`
- Downstream assets:
  - `revenue_daily_summary`
  - `customer_lifetime_value_features`
  - `orders_open_fulfillment_queue`
- Business impact:
  - negative and duplicate order amounts can distort daily revenue
  - future or backwards ship dates can create false fulfillment SLA misses
  - invalid customer identifiers break joins to the customer dimension
  - non-USD orders can inflate/deflate USD revenue if loaded without conversion

## How to fix it

Implement remediation in code and update the integration-flow intent so the pipeline prevents recurrence:

1. Detect all configured DQ rules from `assets/config/dq_rules.yaml`.
2. Normalize `status`, `currency`, and `email` before validation.
3. Fill missing `customer_id` from `assets/reference/customer_dimension.csv` by matching email.
4. Replace malformed email from the customer dimension when a valid `customer_id` exists.
5. Deduplicate exact duplicate `order_id` records, keeping the earliest `ingested_at`.
6. Quarantine rows with negative `order_total` or unsupported currency.
7. Clear `ship_date` and mark for reprocessing when dates are inconsistent or in the future.
8. Write a JSON evidence report and invalid-row sample for watsonx.data intelligence evidence/audit review.
9. Update the watsonx.data integration flow blueprint to include these stages before publishing to the gold table.

## Acceptance criteria

- `python src/remediate_orders.py` writes:
  - `assets/data/customer_orders_remediated.csv`
  - `assets/data/customer_orders_quarantine.csv`
  - `reports/dq_summary.json`
  - `reports/invalid_rows.csv`
- No duplicate `order_id` remains in the remediated output.
- Remediated rows are all `USD` and have non-negative `order_total`.
- Remediated rows have uppercase valid status codes.
- Remediated `ship_date`, when present, is between `order_date` and `2026-07-03` inclusive.
- Quarantine file contains the unrecoverable negative-amount and non-USD records.
- The code is written so Claude Code can extend it to call the real watsonx.data intelligence SDK/MCP and watsonx.data integration SDK/MCP.

## Suggested GitHub CLI command

```bash
gh issue create \
  --title "[DQ-148] Customer orders feed breached gold-table SLA after legacy CRM cutover" \
  --body-file assets/issues/ISSUE_148_customer_orders_dq_regression.md \
  --label data-quality \
  --label watsonx.data-intelligence \
  --label watsonx.data-integration \
  --label claude-code-ready
```

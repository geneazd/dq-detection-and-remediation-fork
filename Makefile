.PHONY: run test clean issue-intent flow-intent

run:
	python src/remediate_orders.py

test:
	pytest -q

clean:
	rm -f assets/data/customer_orders_remediated.csv assets/data/customer_orders_quarantine.csv reports/dq_summary.json reports/invalid_rows.csv

issue-intent:
	cat assets/issues/ISSUE_148_customer_orders_dq_regression.md

flow-intent:
	python integration/create_or_update_flow_with_sdk.py

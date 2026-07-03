# Claude Code repo instructions

This repository is a mock demo for issue-driven data-quality remediation.

Start with:

```bash
cat assets/issues/ISSUE_148_customer_orders_dq_regression.md
cat assets/prompts/claude_code_issue_prompt.md
```

Then run:

```bash
python src/remediate_orders.py
pytest -q
```

The code is intentionally local-first. Real IBM calls should be added behind adapter boundaries so the demo remains runnable without IBM credentials.

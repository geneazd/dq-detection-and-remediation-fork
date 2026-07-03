"""
Starter scaffold for watsonx.data integration SDK usage.

This file is intentionally a blueprint adapter rather than fully executable SDK code, because
real project IDs, connection assets, environments, and credentials are environment-specific.
Use the data-intg MCP server to look up exact model classes/stage configurations, or see
`.claude/skills/wxdi-remediate/` for the grounded SDK call sequence used by
`apply_blueprint_via_sdk` below.
"""

import os
import time
from pathlib import Path
import yaml

BLUEPRINT = Path("integration/wdi_flow_blueprint.yaml")


def load_blueprint(path: Path = BLUEPRINT) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_flow_intent(blueprint: dict) -> str:
    stages = "\n".join(
        f"- {stage['id']}: {stage['kind']} — {stage['operation']}"
        for stage in blueprint["stages"]
    )
    return f"""
Create or update watsonx.data integration batch flow `{blueprint['flow_name']}`.

Sources:
{yaml.safe_dump(blueprint['sources'], sort_keys=False)}

Targets:
{yaml.safe_dump(blueprint['targets'], sort_keys=False)}

Stages:
{stages}

Observability requirements:
{yaml.safe_dump(blueprint['observability'], sort_keys=False)}
""".strip()


def sdk_credentials_available() -> bool:
    """Adapter-boundary gate: only attempt real SDK calls when both are set."""
    return bool(os.environ.get("WATSONX_API_KEY")) and bool(os.environ.get("WXDI_PROJECT_ID"))


def _quality_sla(rules_path: Path = Path("assets/config/dq_rules.yaml")) -> dict:
    with rules_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("quality_sla", {})


def apply_blueprint_via_sdk(blueprint: dict) -> dict:
    """Create/update the real batch flow from `blueprint` using ibm-watsonx-data-integration.

    Requires WATSONX_API_KEY and WXDI_PROJECT_ID (WXDI_BASE_API_URL optional, defaults to the
    SDK's default region). Never called by the local demo path (`__main__` below) so the repo
    stays runnable without IBM credentials. Stage `type` strings are not guessed here: only
    stages already present in `batch_flow.available_stages` (matched by label) are configured,
    everything else is reported back for a human/agent to resolve against the target
    environment's real stage catalog.

    If every blueprint stage resolves, stages are wired in blueprint order via
    `connect_output_to` (plus a `split_quarantine -> write_quarantine` branch), the flow is
    compiled, and a job run is started to serve as the "dry run" (per the SDK cheatsheet: there
    is no dedicated dry-run flag, so a job run against the target project/environment is read
    back for stage/link metrics instead). If any stage is unresolved, compile/job are skipped
    rather than running a flow that's missing real logic — the caller should resolve
    `unresolved_stages` against the environment's stage catalog first.
    """
    if not sdk_credentials_available():
        raise RuntimeError(
            "WATSONX_API_KEY and WXDI_PROJECT_ID must both be set to use the real SDK path; "
            "use build_flow_intent() for the local/no-credentials demo instead."
        )

    from ibm_watsonx_data_integration.common.auth import IAMAuthenticator
    from ibm_watsonx_data_integration.platform import Platform

    base_api_url = os.environ.get("WXDI_BASE_API_URL")
    auth = IAMAuthenticator(api_key=os.environ["WATSONX_API_KEY"], base_auth_url="https://cloud.ibm.com")
    platform = Platform(auth, base_api_url=base_api_url) if base_api_url else Platform(auth)

    project = platform.projects.get(project_id=os.environ["WXDI_PROJECT_ID"])
    flow = project.flows.get(name=blueprint["flow_name"])
    if flow is None:
        flow = project.create_flow(name=blueprint["flow_name"], flow_type="batch")

    available = {info.name: info for info in flow.available_stages}
    stage_objs = {stage.label: stage for stage in flow.stages} if hasattr(flow, "stages") else {}

    configured, unresolved = [], []
    for stage in blueprint["stages"]:
        if stage["id"] in stage_objs:
            configured.append(stage["id"])
            continue
        match = available.get(stage["id"]) or available.get(stage["kind"])
        if match is None:
            unresolved.append(stage["id"])
            continue
        stage_objs[stage["id"]] = flow.add_stage(stage_info=match, label=stage["id"])
        configured.append(stage["id"])

    result = {
        "flow_name": blueprint["flow_name"],
        "configured_stages": configured,
        "unresolved_stages": unresolved,
        "compiled": False,
        "job_id": None,
        "job_run_id": None,
        "job_state": None,
        "metrics": None,
        "quality_sla_breach": None,
    }

    if unresolved:
        project.update_flow(flow)
        result["note"] = (
            "Skipped stage wiring/compile/job: resolve unresolved_stages against this "
            "environment's real stage catalog first (see available_stages)."
        )
        return result

    # Wire stages in blueprint order; split_quarantine also branches to write_quarantine.
    ordered_ids = [stage["id"] for stage in blueprint["stages"]]
    for upstream_id, downstream_id in zip(ordered_ids, ordered_ids[1:]):
        stage_objs[upstream_id].connect_output_to(stage_objs[downstream_id])
    if "split_quarantine" in stage_objs and "write_quarantine" in stage_objs:
        stage_objs["split_quarantine"].connect_output_to(stage_objs["write_quarantine"])

    project.update_flow(flow)
    flow.compile()
    result["compiled"] = True

    job = project.create_job(flow=flow, name=f"{blueprint['flow_name']}_dry_run")
    job_run = job.start(name=f"{blueprint['flow_name']}_dry_run_run")
    result["job_id"] = getattr(job, "id", None) or getattr(job, "job_id", None)
    result["job_run_id"] = getattr(job_run, "id", None) or getattr(job_run, "run_id", None)

    max_polls, poll_interval_s = 30, 10
    for _ in range(max_polls):
        job_run.refresh_status()
        state = str(getattr(job_run, "state", "")).lower()
        if any(terminal in state for terminal in ("complet", "fail", "cancel", "error")):
            break
        time.sleep(poll_interval_s)
    result["job_state"] = getattr(job_run, "state", None)

    job_run.refresh_metrics()
    metrics = job_run.metrics
    stage_metrics = {
        m.stage_name: m.rows_read for m in getattr(metrics, "stage_metrics", [])
    }
    result["metrics"] = stage_metrics

    total = stage_metrics.get("read_raw_orders")
    quarantined = stage_metrics.get("write_quarantine")
    if total:
        pass_rate = round((total - (quarantined or 0)) / total, 4)
        sla = _quality_sla()
        result["quality_pass_rate"] = pass_rate
        result["quality_sla_breach"] = pass_rate < sla.get("min_pass_rate", 0.98)

    return result


if __name__ == "__main__":
    bp = load_blueprint()
    print(build_flow_intent(bp))
    if sdk_credentials_available():
        print("\nWATSONX_API_KEY/WXDI_PROJECT_ID detected — applying blueprint via the real SDK...")
        try:
            print(apply_blueprint_via_sdk(bp))
        except Exception as exc:  # isolate real-SDK failures from the local demo path
            print(f"apply_blueprint_via_sdk failed: {exc}")
    else:
        print("\nNext: paste this intent into the watsonx.data integration MCP server, or set "
              "WATSONX_API_KEY + WXDI_PROJECT_ID to apply it via the real SDK "
              "(see .claude/skills/wxdi-remediate/).")

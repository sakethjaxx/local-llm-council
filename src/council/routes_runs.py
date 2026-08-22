import asyncio
import io
import json
import zipfile
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from logging_utils import get_logger
from metrics_store import metrics_store
from provider_caps import redact_config
from run_store import run_store

logger = get_logger(__name__)
router = APIRouter()


class FeedbackRequest(BaseModel):
    action_index: int
    rating: Literal["thumbs_up", "thumbs_down", "ignored"]
    note: str = ""


def _metrics_run_for_export(run_id: str) -> dict:
    for run in metrics_store.list_runs(limit=500):
        if run.get("run_id") == run_id:
            return redact_config(run)
    return {}


def _render_run_markdown(run: dict, metrics: dict) -> str:
    lines = [
        "# Council Run Export",
        "",
        f"Run ID: {run.get('run_id', '')}",
        f"Status: {run.get('status', '')}",
        "",
        "## Topic",
        run.get("topic", ""),
        "",
    ]
    chairman_phase = next(
        (p for p in run.get("phases", []) if p.get("phase") == 3 and p.get("member_id") == "chairman"),
        None,
    )
    if chairman_phase:
        lines.extend(["## Chairman Verdict", chairman_phase.get("output", ""), ""])

    for phase in run.get("phases", []):
        seat = (run.get("roster") or {}).get(phase.get("member_id"), {})
        label = seat.get("label") or phase.get("member_id", "unknown")
        lines.extend([f"## Phase {phase.get('phase')} — {label}", "", phase.get("output", ""), ""])

    if run.get("feedback"):
        lines.append("## Feedback\n")
        for item in run["feedback"]:
            lines.append(f"- Action {item.get('action_index')}: {item.get('rating')} {item.get('note', '').strip()}".rstrip())
        lines.append("")

    if metrics:
        lines.extend(["## Metrics", "", json.dumps(metrics, indent=2), ""])
    return "\n".join(lines)


@router.get("/runs")
async def list_runs(limit: int = 50, fingerprint_hash: Optional[str] = None):
    return run_store.list_runs(limit=limit, fingerprint_hash=fingerprint_hash)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    deleted = run_store.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {"deleted": True, "run_id": run_id}


@router.delete("/runs")
async def delete_all_runs():
    deleted_count = run_store.delete_all_runs()
    return {"deleted": True, "count": deleted_count}


@router.post("/runs/{run_id}/feedback")
async def record_feedback(run_id: str, req: FeedbackRequest):
    if not run_store.run_exists(run_id):
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    run_store.record_feedback(run_id, req.action_index, req.rating, req.note)
    return {"ok": True, "run_id": run_id, "action_index": req.action_index}


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str, format: str = "zip"):
    run = run_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    metrics = _metrics_run_for_export(run_id)
    md_content = _render_run_markdown(run, metrics)
    if format.lower() == "markdown":
        return Response(
            content=md_content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="council-run-{run_id}.md"'},
        )

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"council-run-{run_id}/README.md", md_content)
        archive.writestr(f"council-run-{run_id}/run.json", json.dumps(redact_config(run), indent=2))
        archive.writestr(f"council-run-{run_id}/metrics.json", json.dumps(metrics, indent=2))
        archive.writestr(f"council-run-{run_id}/verdict.md", run.get("output", "") or md_content)

    bundle.seek(0)
    return Response(
        content=bundle.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="council-run-{run_id}.zip"'},
    )


@router.get("/quality-metrics")
async def get_quality_metrics(limit: int = 100):
    return run_store.list_quality_metrics(limit=limit)


@router.get("/metrics")
async def list_metrics(limit: int = 20):
    return metrics_store.list_runs(limit=limit)


@router.get("/metrics/summary")
async def get_metrics_summary():
    return metrics_store.get_summary()

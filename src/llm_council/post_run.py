import asyncio
import contextlib
import json


def _consume_task_exception(task: asyncio.Task) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.exception()


class PostRunFinalizer:
    def __init__(self, run_store, metrics_store, memory_engine, skill_registry):
        self.run_store = run_store
        self.metrics_store = metrics_store
        self.memory_engine = memory_engine
        self.skill_registry = skill_registry

    async def finalize_success(
        self,
        run_id: str,
        combined_topic: str,
        chairman_text: str,
        chairman_model: str,
        parse_tier: str | None,
        phase1_divergence: float | None,
        specificity_score: float,
        grounding: float | None,
        confidence_score: int,
        stances: dict,
        stance_sources: dict,
        agreement: str,
    ) -> None:
        await asyncio.to_thread(
            self.run_store.record_phase_output,
            run_id,
            3,
            "chairman",
            chairman_text,
            None,
            None,
            None,
            finish_reason=parse_tier,
            attempt_number=None,
        )
        await asyncio.to_thread(
            self.run_store.update_quality_metrics,
            run_id,
            parse_tier,
            phase1_divergence,
            specificity_score,
        )
        await asyncio.to_thread(
            self.run_store.update_confidence_metrics,
            run_id,
            grounding,
            confidence_score,
            json.dumps(
                {
                    "stances": stances,
                    "stance_sources": stance_sources,
                    "agreement": agreement,
                }
            ),
        )
        task = asyncio.create_task(
            self.memory_engine.extract_memory(
                combined_topic,
                chairman_text,
                chairman_model,
                run_id=run_id,
            )
        )
        task.add_done_callback(_consume_task_exception)

        self.metrics_store.finish_run(run_id, status="completed")
        await asyncio.to_thread(self.run_store.finish_run, run_id, "completed")

        task = asyncio.create_task(
            self.skill_registry.extract_skills(run_id, combined_topic, chairman_model)
        )
        task.add_done_callback(_consume_task_exception)

    async def finalize_failure(self, run_id: str, error: Exception) -> None:
        self.metrics_store.finish_run(run_id, status="failed", error=str(error))
        await asyncio.to_thread(self.run_store.finish_run, run_id, "failed", str(error))

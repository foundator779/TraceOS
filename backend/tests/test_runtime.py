from __future__ import annotations

import pytest

from app.cloud import CloudAuditConnector
from app.config import Settings
from app.gemini import GeminiReportWriter
from app.models import CaseCreate, CaseStatus
from app.runtime import InvestigationRuntime
from app.store import CaseStore


def make_runtime(tmp_path) -> InvestigationRuntime:
    settings = Settings(
        _env_file=None,
        traceos_db_path=str(tmp_path / "traceos-test.db"),
        runtime_step_delay_ms=0,
        google_api_key=None,
        enable_cloud_connectors=False,
    )
    return InvestigationRuntime(
        settings,
        CaseStore(settings.traceos_db_path),
        CloudAuditConnector(settings),
        GeminiReportWriter(settings),
    )


@pytest.mark.asyncio
async def test_case_042_golden_path(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.create_case(CaseCreate(), "CASE-042")
    await runtime._run_initial("CASE-042")
    waiting = runtime.store.get("CASE-042")
    assert waiting is not None
    assert waiting.case.status == CaseStatus.WAITING
    assert len(waiting.evidence) == 6
    assert all(len(e.sha256) == 64 for e in waiting.evidence)
    assert any(item.decision == "BLOCK" for item in waiting.model_armor_decisions)
    assert any(item.decision == "DENY" for item in waiting.gateway_decisions)
    assert waiting.integrity_events[0]["corrected_reference"] == "EVID-003"
    assert waiting.observations[1].evidence_ids == ["EVID-003"]
    assert waiting.hypotheses[0].status == "VERIFIED"
    assert waiting.memory.open_questions[0].status == "OPEN"
    assert not any(item.live_source_verified for item in waiting.evidence)

    assert runtime.append_day_eight("CASE-042") is True
    await runtime.wait("CASE-042")
    closed = runtime.store.get("CASE-042")
    assert closed is not None
    assert closed.case.status == CaseStatus.CLOSED
    assert closed.case.runtime_generation == 2
    assert closed.memory.open_questions[0].status == "RESOLVED"
    assert len(closed.findings) == 2
    assert closed.report is not None
    assert set(closed.report.evidence_index) >= {"EVID-001", "EVID-003", "EVID-004", "EVID-007"}
    assert runtime.append_day_eight("CASE-042") is False


@pytest.mark.asyncio
async def test_twenty_consecutive_golden_initial_runs(tmp_path):
    runtime = make_runtime(tmp_path)
    for index in range(20):
        case_id = f"CASE-GOLD-{index:02d}"
        runtime.create_case(CaseCreate(), case_id)
        await runtime._run_initial(case_id)
        result = runtime.store.get(case_id)
        assert result is not None
        assert result.case.status == CaseStatus.WAITING
        assert any(event.event_type == "MODEL_ARMOR_BLOCKED" for event in result.audit)
        assert any(event.event_type == "GATEWAY_DENIED" for event in result.audit)
        assert any(event.event_type == "AGENT_REPLAY_COMPLETED" for event in result.audit)


@pytest.mark.asyncio
async def test_resume_is_chained_when_evidence_arrives_during_final_checkpoint(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.settings.runtime_step_delay_ms = 2
    runtime.create_case(CaseCreate(), "CASE-RACE")
    runtime.launch("CASE-RACE")
    for _ in range(500):
        state = runtime.store.get("CASE-RACE")
        if state and state.case.status == CaseStatus.WAITING:
            break
        import asyncio
        await asyncio.sleep(0.002)
    assert runtime.append_day_eight("CASE-RACE") is True
    await runtime.wait("CASE-RACE")
    result = runtime.store.get("CASE-RACE")
    assert result is not None
    assert result.case.status == CaseStatus.CLOSED
    assert result.case.runtime_generation == 2

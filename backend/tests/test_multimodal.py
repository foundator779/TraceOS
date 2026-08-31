from __future__ import annotations

import io

import pytest
from PIL import Image

from app.api import register_image
from app.cloud import CloudAuditConnector
from app.config import Settings
from app.evidence import EvidenceStorage, demo_evidence_png, validate_image
from app.gemini import GeminiReportWriter
from app.models import CaseCreate, ReplayStage, VisualObservation, VisualRegion
from app.multimodal import analyze_registered_image
from app.replay import build_replay
from app.runtime import InvestigationRuntime
from app.store import CaseStore


def setup_runtime(tmp_path):
    settings = Settings(
        _env_file=None,
        traceos_db_path=str(tmp_path / "traceos.db"),
        evidence_local_path=str(tmp_path / "evidence"),
        runtime_step_delay_ms=0,
        google_api_key=None,
        enable_cloud_connectors=False,
    )
    store = CaseStore(settings.traceos_db_path)
    writer = GeminiReportWriter(settings)
    runtime = InvestigationRuntime(settings, store, CloudAuditConnector(settings), writer)
    runtime.create_case(CaseCreate(), "CASE-042")
    return settings, store, writer, runtime


def test_demo_image_is_valid_and_watermarked_size():
    data = demo_evidence_png()
    settings = Settings(_env_file=None)
    assert validate_image(data, "image/png", settings) == ("image/png", 1200, 720)
    assert len(data) < settings.max_image_bytes


def test_image_validation_rejects_mime_mismatch_and_oversize(tmp_path):
    settings = Settings(_env_file=None, max_image_bytes=8)
    with pytest.raises(ValueError, match="5 MB"):
        validate_image(demo_evidence_png(), "image/png", settings)
    image = Image.new("RGB", (10, 10), "white")
    buffer = io.BytesIO(); image.save(buffer, format="JPEG")
    with pytest.raises(ValueError, match="does not match"):
        validate_image(buffer.getvalue(), "image/png", Settings(_env_file=None))


@pytest.mark.asyncio
async def test_visual_agent_cannot_create_finding_without_verifier_input(tmp_path, monkeypatch):
    settings, store, writer, _ = setup_runtime(tmp_path)
    storage = EvidenceStorage(settings)
    record = register_image(store, storage, settings, "CASE-042", demo_evidence_png(), "image/png", "test", True)
    monkeypatch.setattr(writer, "analyze_image", lambda *_: VisualObservation(
        summary="A new-region sign-in alert is visible.",
        ocr_excerpt="Location: Montreal, CA",
        confidence=0.94,
        regions=[VisualRegion(label="new region", x=.1, y=.6, width=.4, height=.1, confidence=.9)],
    ))
    analyze_registered_image(store, writer, storage, "CASE-042", record.evidence_id)
    state = store.get("CASE-042")
    assert state is not None
    assert state.evidence[-1].status == "ANALYZED"
    assert state.observations[-1].agent == "visual-evidence-agent"
    assert state.findings == []


@pytest.mark.asyncio
async def test_visual_observation_is_correlated_only_after_initial_verification(tmp_path, monkeypatch):
    settings, store, writer, runtime = setup_runtime(tmp_path)
    await runtime._run_initial("CASE-042")
    storage = EvidenceStorage(settings)
    record = register_image(store, storage, settings, "CASE-042", demo_evidence_png(), "image/png", "test", True)
    monkeypatch.setattr(writer, "analyze_image", lambda *_: VisualObservation(
        summary="The alert shows a previously unseen region at 09:42 UTC.",
        ocr_excerpt="Risk signal: NEW REGION",
        confidence=0.96,
    ))
    analyze_registered_image(store, writer, storage, "CASE-042", record.evidence_id)
    state = store.get("CASE-042")
    assert state is not None
    assert record.evidence_id in state.findings[0].evidence_ids
    assert any(result.status == "VERIFIED_CORRELATION" for result in state.verification_results)
    replay = build_replay(state)
    assert {item.stage for item in replay} == set(ReplayStage)
    assert any(item.image_url for item in replay)
    assert any(item.status == "REJECTED_UNSUPPORTED" for item in replay)
    assert len(replay) <= 16

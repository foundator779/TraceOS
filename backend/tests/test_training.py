from __future__ import annotations

import pytest

from app.config import Settings
from app.models import (
    Case,
    CaseMemory,
    CaseState,
    CrossModelVerdict,
    Finding,
    ForensicReport,
    TrainingArtifact,
)
from app.store import CaseStore
from app.training import BonusModelClient, TrainingPackService, TrainingStorage


def closed_case() -> CaseState:
    finding = Finding(
        finding_id="FIND-001",
        title="Verified anomaly",
        severity="HIGH",
        statement="Identity and endpoint anomalies overlap.",
        evidence_ids=["EVID-001", "EVID-003"],
        observation_ids=["OBS-001"],
    )
    return CaseState(
        case=Case(case_id="CASE-042", external_ref="TEST", title="Training test", status="CLOSED"),
        memory=CaseMemory(case_id="CASE-042"),
        findings=[finding],
        report=ForensicReport(
            report_id="RPT-001",
            case_id="CASE-042",
            title="Verified report",
            executive_summary="Verified summary.",
            findings=["FIND-001"],
            limitations=["Synthetic test data."],
            evidence_index=["EVID-001", "EVID-003"],
        ),
    )


def service(tmp_path, **overrides) -> tuple[TrainingPackService, CaseStore]:
    settings = Settings(
        _env_file=None,
        traceos_db_path=str(tmp_path / "training.db"),
        training_local_path=str(tmp_path / "training"),
        **overrides,
    )
    store = CaseStore(settings.traceos_db_path)
    store.save(closed_case())
    return TrainingPackService(settings, store), store


def test_training_pack_is_disabled_and_idempotent_by_default(tmp_path):
    training, store = service(tmp_path)
    first, created = training.initialize("CASE-042")
    second, duplicate = training.initialize("CASE-042")
    assert created is True
    assert duplicate is False
    assert first.pack_id == second.pack_id
    assert first.status == "DISABLED"
    assert store.get("CASE-042").findings[0].status == "VERIFIED"


def test_supported_verdict_releases_separate_training_artifacts(tmp_path, monkeypatch):
    training, store = service(
        tmp_path,
        enable_gemma_verifier=True,
        enable_veo_training=True,
        enable_lyria_training=True,
        training_budget_usd=1,
    )
    pack, _ = training.initialize("CASE-042")
    before = store.get("CASE-042")
    monkeypatch.setattr(training.models, "challenge", lambda state, report_hash: CrossModelVerdict(
        verdict_id="VERDICT-001",
        case_id=state.case.case_id,
        model=training.settings.gemma_verifier_model,
        status="SUPPORTED",
        evidence_ids=[],
        rationale="All cited identifiers are internally consistent.",
        input_hash=report_hash,
        operation_id="gemma-op-1",
        estimated_cost_usd=.002,
    ))

    def ready(state, artifact: TrainingArtifact):
        artifact.status = "READY"
        artifact.storage_uri = f"memory://{artifact.artifact_id}"
        artifact.sha256 = "a" * 64
        artifact.operation_id = f"{artifact.model_family.lower()}-op-1"
        artifact.estimated_cost_usd = .32 if artifact.model_family == "Veo" else .04
        return artifact

    monkeypatch.setattr(training.models, "generate_video", ready)
    monkeypatch.setattr(training.models, "generate_audio", ready)
    result = training.run("CASE-042")
    after = store.get("CASE-042")

    assert pack.status == "QUEUED"
    assert result.status == "READY"
    assert result.gemma_verdict.status == "SUPPORTED"
    assert {item.model_family for item in result.artifacts if item.status == "READY"} == {"Veo", "Lyria"}
    assert result.estimated_cost_usd == .362
    assert after.findings == before.findings
    assert after.evidence == before.evidence
    assert all(span.attributes["evidence_plane_write"] is False for span in after.traces)


def test_cross_model_disagreement_stops_generation(tmp_path, monkeypatch):
    training, _ = service(
        tmp_path,
        enable_gemma_verifier=True,
        enable_veo_training=True,
        enable_lyria_training=True,
    )
    training.initialize("CASE-042")
    monkeypatch.setattr(training.models, "challenge", lambda state, report_hash: CrossModelVerdict(
        verdict_id="VERDICT-002",
        case_id=state.case.case_id,
        model=training.settings.gemma_verifier_model,
        status="UNSUPPORTED",
        evidence_ids=[],
        disagreements=["Finding does not cite a known evidence object."],
        rationale="Human review required.",
        input_hash=report_hash,
    ))
    monkeypatch.setattr(training.models, "generate_video", lambda *_: (_ for _ in ()).throw(AssertionError("must not run")))
    monkeypatch.setattr(training.models, "generate_audio", lambda *_: (_ for _ in ()).throw(AssertionError("must not run")))
    result = training.run("CASE-042")
    assert result.status == "HUMAN_REVIEW"
    assert all(item.status == "ARTIFACT_UNAVAILABLE" for item in result.artifacts)
    assert all(item.error_code == "CROSS_MODEL_DISAGREEMENT" for item in result.artifacts)


def test_budget_circuit_breaker_runs_before_any_model(tmp_path, monkeypatch):
    training, _ = service(
        tmp_path,
        enable_gemma_verifier=True,
        enable_veo_training=True,
        enable_lyria_training=True,
        training_budget_usd=.10,
    )
    training.initialize("CASE-042")
    monkeypatch.setattr(training.models, "challenge", lambda *_: (_ for _ in ()).throw(AssertionError("must not run")))
    result = training.run("CASE-042")
    assert result.status == "BUDGET_BLOCKED"
    assert all(item.error_code == "PACK_BUDGET_EXCEEDED" for item in result.artifacts)


def test_lyria_audio_uri_is_copied_into_private_training_storage(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        training_local_path=str(tmp_path / "training"),
        lyria_training_model="lyria-3-clip-preview",
    )
    storage = TrainingStorage(settings)
    client = BonusModelClient(settings, storage)
    monkeypatch.setattr("app.training._post_json", lambda *args, **kwargs: {
        "id": "interaction-001",
        "status": "completed",
        "outputs": [{
            "type": "audio", "mime_type": "audio/mpeg", "uri": "gs://model-output/clip.mp3"
        }],
    })
    monkeypatch.setattr(storage, "get", lambda uri: b"synthetic-audio-bytes")
    artifact = TrainingArtifact(
        artifact_id="TRAIN-AUDIO",
        kind="TABLETOP_AUDIO",
        model_family="Lyria",
        model=settings.lyria_training_model,
    )
    result = client.generate_audio(closed_case(), artifact)
    assert result.status == "READY"
    assert result.operation_id == "interaction-001"
    assert result.sha256
    assert result.storage_uri and result.storage_uri.endswith(".mp3")


def test_partial_pack_allows_only_one_bounded_artifact_retry(tmp_path, monkeypatch):
    training, store = service(
        tmp_path,
        enable_gemma_verifier=True,
        enable_lyria_training=True,
        training_budget_usd=1,
    )
    pack, _ = training.initialize("CASE-042")
    pack.status = "PARTIAL"
    pack.gemma_verdict = CrossModelVerdict(
        verdict_id="VERDICT-RETRY",
        case_id="CASE-042",
        model=training.settings.gemma_verifier_model,
        status="SUPPORTED",
        evidence_ids=[],
        rationale="Supported.",
        input_hash=pack.report_hash,
        estimated_cost_usd=.002,
    )
    audio = next(item for item in pack.artifacts if item.model_family == "Lyria")
    audio.status = "ARTIFACT_UNAVAILABLE"
    audio.estimated_cost_usd = .04
    store.mutate("CASE-042", lambda state: setattr(state, "training_pack", pack))

    def ready(state, artifact):
        artifact.status = "READY"
        artifact.storage_uri = "memory://audio"
        artifact.sha256 = "b" * 64
        artifact.operation_id = "lyria-retry-op"
        artifact.estimated_cost_usd = .04
        return artifact

    monkeypatch.setattr(training.models, "generate_audio", ready)
    result = training.retry_failed("CASE-042")
    retried = next(item for item in result.artifacts if item.model_family == "Lyria")
    assert result.status == "READY"
    assert retried.retry_count == 1
    assert retried.estimated_cost_usd == .08
    with pytest.raises(ValueError, match="partially generated"):
        training.retry_failed("CASE-042")

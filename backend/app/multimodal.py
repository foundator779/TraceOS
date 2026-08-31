from __future__ import annotations

from .evidence import EvidenceStorage
from .gemini import GeminiReportWriter
from .models import AuditEvent, CaseState, Observation, RuntimeEvent, VerificationResult, utc_now


def analyze_registered_image(
    store,
    writer: GeminiReportWriter,
    storage: EvidenceStorage,
    case_id: str,
    evidence_id: str,
) -> None:
    state = store.get(case_id)
    if state is None:
        return
    evidence = next((item for item in state.evidence if item.evidence_id == evidence_id), None)
    if evidence is None or evidence.status == "ANALYZED":
        return
    mime_type = str(evidence.metadata.get("mime_type", "image/png"))
    try:
        result = writer.analyze_image(storage.get(evidence.storage_uri), mime_type)
    except Exception as exc:
        def fail(current: CaseState) -> None:
            target = next(item for item in current.evidence if item.evidence_id == evidence_id)
            target.status = "ANALYSIS_FAILED"
            target.metadata["analysis_error"] = type(exc).__name__
            if hasattr(exc, "errors"):
                target.metadata["analysis_error_fields"] = [
                    {"path": ".".join(str(part) for part in item.get("loc", [])), "type": item.get("type")}
                    for item in exc.errors(include_input=False)[:8]
                ]
            current.runtime_events.append(RuntimeEvent(
                sequence=len(current.runtime_events) + 1,
                case_id=case_id,
                event_type="VISUAL_ANALYSIS_FAILED",
                title="Image preserved; analysis failed safely",
                detail="No visual observation or finding was created.",
                status="warning",
                agent_id="visual-evidence-agent",
            ))
        store.mutate(case_id, fail)
        return

    def apply(current: CaseState) -> None:
        target = next(item for item in current.evidence if item.evidence_id == evidence_id)
        target.status = "ANALYZED"
        target.preview = result.summary
        target.metadata["analysis_model"] = writer.settings.gemini_vision_model
        observation_id = f"OBS-VIS-{sum(o.modality == 'IMAGE' for o in current.observations) + 1:03d}"
        observation = Observation(
            observation_id=observation_id,
            agent="visual-evidence-agent",
            statement=result.summary,
            event_time=target.collected_at,
            evidence_ids=[evidence_id],
            confidence=result.confidence,
            classification="visual-identity-signal",
            modality="IMAGE",
            source_evidence_id=evidence_id,
            ocr_excerpt=result.ocr_excerpt,
            visual_regions=result.regions,
            model=writer.settings.gemini_vision_model,
        )
        current.observations.append(observation)
        # Visual facts are promoted only by correlation with the pre-existing identity
        # observation; the visual agent itself has no finding-write path.
        identity_observation = next(
            (item for item in current.observations if item.observation_id == "OBS-001"), None
        )
        hypothesis = next((item for item in current.hypotheses if item.hypothesis_id == "HYP-001"), None)
        finding = next((item for item in current.findings if item.finding_id == "FIND-001"), None)
        if identity_observation and hypothesis and finding:
            if observation_id not in hypothesis.supporting_observations:
                hypothesis.supporting_observations.append(observation_id)
            if evidence_id not in finding.evidence_ids:
                finding.evidence_ids.append(evidence_id)
            if observation_id not in finding.observation_ids:
                finding.observation_ids.append(observation_id)
            current.verification_results.append(VerificationResult(
                verification_id=f"VERIFY-VIS-{len(current.verification_results)+1:03d}",
                hypothesis_id=hypothesis.hypothesis_id,
                status="VERIFIED_CORRELATION",
                evidence_ids=[identity_observation.evidence_ids[0], evidence_id],
                rationale="Visual OCR time and new-region signal correlate with the independently registered identity event.",
            ))
        current.audit.append(AuditEvent(
            event_id=f"AUD-{len(current.audit)+1:03d}",
            case_id=case_id,
            event_type="VISUAL_OBSERVATION_CREATED",
            actor="traceos/visual-evidence",
            summary="Gemini produced an observable-facts-only image record; verifier correlation remained separate.",
            evidence_ids=[evidence_id],
            attributes={"model": writer.settings.gemini_vision_model},
        ))
        current.runtime_events.append(RuntimeEvent(
            sequence=len(current.runtime_events) + 1,
            case_id=case_id,
            event_type="VISUAL_ANALYSIS_COMPLETE",
            title="Image observation verified against case evidence",
            detail="Gemini extracted visible facts; the verifier correlated them with the identity event.",
            status="success",
            agent_id="visual-evidence-agent",
        ))
        current.case.updated_at = utc_now()
    store.mutate(case_id, apply)

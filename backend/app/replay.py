from __future__ import annotations

from .models import CaseState, ReplayEvent, ReplayStage


def build_replay(state: CaseState) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    relevant_ids = {item for finding in state.findings for item in finding.evidence_ids}
    relevant_ids.update(
        evidence.evidence_id for evidence in state.evidence if evidence.evidence_type == "image"
    )
    live = [evidence for evidence in state.evidence if evidence.live_source_verified]
    if live:
        relevant_ids.add(max(live, key=lambda evidence: evidence.collected_at).evidence_id)
    for evidence in state.evidence:
        if evidence.evidence_id not in relevant_ids:
            continue
        events.append(ReplayEvent(
            replay_id=f"source-{evidence.evidence_id}",
            stage=ReplayStage.SOURCE,
            title=evidence.evidence_type.replace("_", " ").title(),
            detail=evidence.preview or f"Evidence received from {evidence.source_system}.",
            event_time=evidence.collected_at,
            evidence_ids=[evidence.evidence_id],
            status=evidence.status,
            source_kind=evidence.source_kind,
            image_url=(
                f"/api/v1/cases/{state.case.case_id}/evidence/{evidence.evidence_id}/content"
                if evidence.evidence_type == "image" and evidence.metadata.get("public_demo")
                else None
            ),
            sha256=evidence.sha256,
        ))
    for observation in state.observations:
        if not relevant_ids.intersection(observation.evidence_ids):
            continue
        events.append(ReplayEvent(
            replay_id=f"observation-{observation.observation_id}",
            stage=ReplayStage.OBSERVATION,
            title=observation.classification.replace("-", " ").title(),
            detail=observation.statement,
            event_time=observation.event_time,
            evidence_ids=observation.evidence_ids,
            confidence=observation.confidence,
            status=observation.integrity_status,
            ocr_excerpt=observation.ocr_excerpt,
            model=observation.model,
            visual_regions=observation.visual_regions,
        ))
    for hypothesis in state.hypotheses:
        evidence_ids = sorted({
            evidence_id
            for observation in state.observations
            if observation.observation_id in hypothesis.supporting_observations
            for evidence_id in observation.evidence_ids
        })
        events.append(ReplayEvent(
            replay_id=f"hypothesis-{hypothesis.hypothesis_id}",
            stage=ReplayStage.HYPOTHESIS,
            title=hypothesis.hypothesis_id,
            detail=hypothesis.statement,
            event_time=state.case.updated_at,
            evidence_ids=evidence_ids,
            status=hypothesis.status,
        ))
    for integrity in state.integrity_events:
        if integrity.get("reason") != "unsupported evidence reference":
            continue
        blocked_event = next(
            (item for item in state.runtime_events if item.event_type == "UNSUPPORTED_EVIDENCE_REFERENCE"),
            None,
        )
        referenced = str(integrity.get("referenced", "unregistered evidence"))
        events.append(ReplayEvent(
            replay_id=f"rejected-{integrity.get('event_id', referenced)}",
            stage=ReplayStage.HYPOTHESIS,
            title=f"Unsupported {referenced} claim",
            detail="Fleet Integrity stopped this claim because its evidence reference did not exist. It never reached the verified-finding lane.",
            event_time=blocked_event.timestamp if blocked_event else state.case.updated_at,
            evidence_ids=[],
            status="REJECTED_UNSUPPORTED",
        ))
    for finding in state.findings:
        events.append(ReplayEvent(
            replay_id=f"finding-{finding.finding_id}",
            stage=ReplayStage.FINDING,
            title=finding.title,
            detail=finding.statement,
            event_time=finding.created_at,
            evidence_ids=finding.evidence_ids,
            status=finding.status,
        ))
    stage_order = {stage: index for index, stage in enumerate(ReplayStage)}
    return sorted(events, key=lambda event: (stage_order[event.stage], event.event_time, event.replay_id))

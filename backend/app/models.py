from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CaseStatus(StrEnum):
    NEW = "NEW"
    INTAKE = "INTAKE"
    TRIAGE = "TRIAGE"
    ANALYZING = "ANALYZING"
    CORRELATING = "CORRELATING"
    INTEGRITY_CHECK = "INTEGRITY_CHECK"
    VERIFYING = "VERIFYING"
    REVIEW_READY = "REVIEW_READY"
    WAITING = "WAITING_FOR_NEW_EVIDENCE"
    RESUMED = "RESUMED"
    REPORTING = "REPORTING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class SourceKind(StrEnum):
    GOOGLE_CLOUD_LIVE = "GOOGLE_CLOUD_LIVE"
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"


class CaseCreate(BaseModel):
    external_ref: str = "INC-2026-1042"
    title: str = "Suspected enterprise account compromise"
    source: str = "demo-siem"
    priority: str = "high"
    demo_case: bool = True


class Case(BaseModel):
    case_id: str
    external_ref: str
    title: str
    status: CaseStatus = CaseStatus.NEW
    priority: str = "high"
    source: str = "api"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    last_evidence_at: str | None = None
    runtime_generation: int = 1
    review_status: str = "PENDING"
    active_agents: list[str] = Field(default_factory=list)
    risk_score: int = 78


class EvidenceRecord(BaseModel):
    evidence_id: str
    case_id: str
    evidence_type: str
    source_system: str
    source_kind: SourceKind
    source_product: str
    collected_at: str
    ingested_at: str = Field(default_factory=utc_now)
    sha256: str
    classification: str = "internal"
    status: str = "VERIFIED"
    storage_uri: str
    source_project: str | None = None
    source_resource: str | None = None
    external_event_id: str | None = None
    live_source_verified: bool = False
    access_count: int = 0
    preview: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def honest_source_label(self) -> "EvidenceRecord":
        if self.source_kind == SourceKind.DEMO_SYNTHETIC and self.live_source_verified:
            raise ValueError("synthetic evidence cannot be marked live_source_verified")
        return self


class ChainOfCustodyEvent(BaseModel):
    event_id: str
    evidence_id: str
    actor: str
    action: str
    timestamp: str = Field(default_factory=utc_now)
    details: str | None = None


class AgentManifest(BaseModel):
    agent_id: str
    display_name: str
    version: str = "1.0.0"
    status: str = "APPROVED"
    owner: str = "TraceOS Security Engineering"
    identity: str
    allowed_tools: list[str]
    data_scopes: list[str]
    max_runtime_seconds: int = 60
    deployment_state: str = "LOCAL_READY"
    active_cases: int = 0


class GatewayRequest(BaseModel):
    case_id: str
    agent_identity: str
    action: str
    resource: str
    reason: str


class GatewayDecision(BaseModel):
    decision_id: str
    request: GatewayRequest
    decision: str
    policy: str
    reason: str
    timestamp: str = Field(default_factory=utc_now)


class ModelArmorDecision(BaseModel):
    decision_id: str
    evidence_id: str
    decision: str
    category: str | None = None
    action: str
    original_preserved: bool = True
    provider: str = "LOCAL_FAIL_CLOSED"
    timestamp: str = Field(default_factory=utc_now)


class VisualRegion(BaseModel):
    label: str
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


class Observation(BaseModel):
    observation_id: str
    agent: str
    statement: str
    event_time: str
    evidence_ids: list[str]
    confidence: float
    classification: str
    integrity_status: str = "PASSED"
    modality: str = "STRUCTURED_DATA"
    source_evidence_id: str | None = None
    ocr_excerpt: str | None = None
    model: str | None = None
    visual_regions: list[VisualRegion] = Field(default_factory=list)
    processing_status: str = "COMPLETE"


class VisualObservation(BaseModel):
    summary: str
    ocr_excerpt: str | None = None
    regions: list[VisualRegion] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ReplayStage(StrEnum):
    SOURCE = "SOURCE"
    OBSERVATION = "OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    FINDING = "FINDING"


class ReplayEvent(BaseModel):
    replay_id: str
    stage: ReplayStage
    title: str
    detail: str
    event_time: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    status: str
    source_kind: SourceKind | None = None
    image_url: str | None = None
    sha256: str | None = None
    ocr_excerpt: str | None = None
    model: str | None = None
    visual_regions: list[VisualRegion] = Field(default_factory=list)


class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    supporting_observations: list[str]
    missing_evidence: list[str]
    verification_criteria: list[str]
    status: str = "UNVERIFIED"
    revisions: list[dict[str, Any]] = Field(default_factory=list)


class VerificationResult(BaseModel):
    verification_id: str
    hypothesis_id: str
    status: str
    evidence_ids: list[str]
    verified_by: str = "verification-agent"
    rationale: str
    timestamp: str = Field(default_factory=utc_now)


class Finding(BaseModel):
    finding_id: str
    title: str
    severity: str
    status: str = "VERIFIED"
    statement: str
    evidence_ids: list[str]
    observation_ids: list[str]
    verified_by: str = "verification-agent"
    created_at: str = Field(default_factory=utc_now)


class TimelineEvent(BaseModel):
    timeline_id: str
    event_time: str
    title: str
    description: str
    evidence_ids: list[str]
    category: str
    confidence: float


class VerifiedFact(BaseModel):
    fact_id: str
    statement: str
    evidence_ids: list[str]
    verified_by: str = "verification-agent"


class OpenQuestion(BaseModel):
    question_id: str
    text: str
    status: str = "OPEN"


class CaseMemory(BaseModel):
    case_id: str
    version: int = 1
    verified_facts: list[VerifiedFact] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    last_checkpoint: str = Field(default_factory=utc_now)
    provider: str = "SQLITE_MIRROR"


class RuntimeCheckpoint(BaseModel):
    checkpoint_id: str
    case_id: str
    workflow_state: str
    active_agents: list[str]
    retry_count: int = 0
    runtime_generation: int = 1
    timestamp: str = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    event_id: str
    case_id: str
    event_type: str
    actor: str
    summary: str
    timestamp: str = Field(default_factory=utc_now)
    evidence_ids: list[str] = Field(default_factory=list)
    trace_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSpan(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    category: str
    agent_id: str | None = None
    status: str = "OK"
    started_at: str = Field(default_factory=utc_now)
    duration_ms: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)


class ForensicReport(BaseModel):
    report_id: str
    case_id: str
    title: str
    executive_summary: str
    findings: list[str]
    limitations: list[str]
    evidence_index: list[str]
    generated_by: str = "reporting-agent"
    generated_at: str = Field(default_factory=utc_now)
    model: str = "deterministic-structured-renderer"


class CrossModelVerdict(BaseModel):
    verdict_id: str
    case_id: str
    model_family: str = "Gemma"
    model: str
    status: str
    evidence_ids: list[str]
    disagreements: list[str] = Field(default_factory=list)
    rationale: str
    input_hash: str
    operation_id: str | None = None
    estimated_cost_usd: float = 0.0
    created_at: str = Field(default_factory=utc_now)


class TrainingArtifact(BaseModel):
    artifact_id: str
    kind: str
    model_family: str
    model: str
    status: str = "QUEUED"
    storage_uri: str | None = None
    media_url: str | None = None
    sha256: str | None = None
    operation_id: str | None = None
    mime_type: str | None = None
    duration_seconds: int | None = None
    estimated_cost_usd: float = 0.0
    label: str = "SYNTHETIC TRAINING MATERIAL — NOT EVIDENCE"
    error_code: str | None = None
    retry_count: int = 0
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None


class TrainingPack(BaseModel):
    pack_id: str
    case_id: str
    status: str
    report_hash: str
    source_report_id: str
    evidence_ids: list[str]
    gemma_verdict: CrossModelVerdict | None = None
    artifacts: list[TrainingArtifact] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    generation_mode: str = "DISABLED"
    queue_message_id: str | None = None
    provenance_boundary: str = "Generated artifacts are downstream training material and can never become evidence."
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class IntegrationStatus(BaseModel):
    id: str
    name: str
    status: str
    mode: str
    source_kind: SourceKind
    last_verified_at: str | None = None
    detail: str


class EnterpriseSourceEvent(BaseModel):
    external_event_id: str
    source_product: str
    source_project: str
    source_resource: str
    event_time: str
    payload: dict[str, Any]


class RuntimeEvent(BaseModel):
    sequence: int
    case_id: str
    event_type: str
    title: str
    detail: str
    status: str = "info"
    agent_id: str | None = None
    timestamp: str = Field(default_factory=utc_now)


class CaseState(BaseModel):
    case: Case
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    chain_of_custody: list[ChainOfCustodyEvent] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    verification_results: list[VerificationResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    memory: CaseMemory
    checkpoints: list[RuntimeCheckpoint] = Field(default_factory=list)
    audit: list[AuditEvent] = Field(default_factory=list)
    traces: list[TraceSpan] = Field(default_factory=list)
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    gateway_decisions: list[GatewayDecision] = Field(default_factory=list)
    model_armor_decisions: list[ModelArmorDecision] = Field(default_factory=list)
    report: ForensicReport | None = None
    training_pack: TrainingPack | None = None
    integrity_events: list[dict[str, Any]] = Field(default_factory=list)

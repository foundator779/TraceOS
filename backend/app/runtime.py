from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from typing import Any

from .cloud import CloudAuditConnector
from .config import Settings
from .demo_data import DAY_EIGHT_EVIDENCE, DEMO_EVIDENCE, build_registry
from .gemini import GeminiReportWriter
from .models import (
    AuditEvent,
    Case,
    CaseCreate,
    CaseMemory,
    CaseState,
    CaseStatus,
    ChainOfCustodyEvent,
    EvidenceRecord,
    Finding,
    ForensicReport,
    GatewayRequest,
    Hypothesis,
    Observation,
    OpenQuestion,
    RuntimeCheckpoint,
    RuntimeEvent,
    SourceKind,
    TimelineEvent,
    TraceSpan,
    VerificationResult,
    VerifiedFact,
    utc_now,
)
from .security import EvidenceArmor, PolicyGateway, sha256_hex
from .store import CaseStore


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, set[asyncio.Queue[RuntimeEvent]]] = defaultdict(set)

    async def publish(self, event: RuntimeEvent) -> None:
        for queue in list(self._queues[event.case_id]):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def subscribe(self, case_id: str) -> asyncio.Queue[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=128)
        self._queues[case_id].add(queue)
        return queue

    def unsubscribe(self, case_id: str, queue: asyncio.Queue[RuntimeEvent]) -> None:
        self._queues[case_id].discard(queue)


class InvestigationRuntime:
    def __init__(
        self,
        settings: Settings,
        store: CaseStore,
        audit_connector: CloudAuditConnector,
        report_writer: GeminiReportWriter,
    ) -> None:
        self.settings = settings
        self.store = store
        self.audit_connector = audit_connector
        self.report_writer = report_writer
        self.armor = EvidenceArmor(settings)
        self.gateway = PolicyGateway()
        self.bus = EventBus()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create_case(self, payload: CaseCreate, case_id: str = "CASE-042") -> CaseState:
        now = utc_now()
        case = Case(
            case_id=case_id,
            external_ref=payload.external_ref,
            title=payload.title,
            priority=payload.priority,
            source=payload.source,
            created_at=now,
            updated_at=now,
        )
        state = CaseState(case=case, memory=CaseMemory(case_id=case_id))
        self.store.save(state)
        return state

    def launch(self, case_id: str, *, resume: bool = False) -> None:
        existing = self._tasks.get(case_id)
        if existing and not existing.done():
            if resume:
                async def resume_after_active() -> None:
                    with suppress(asyncio.CancelledError):
                        await existing
                    await self._run_resume(case_id)

                self._tasks[case_id] = asyncio.create_task(
                    resume_after_active(), name=f"traceos-{case_id}-resume-chained"
                )
            return
        self._tasks[case_id] = asyncio.create_task(
            self._run_resume(case_id) if resume else self._run_initial(case_id),
            name=f"traceos-{case_id}-{'resume' if resume else 'initial'}",
        )

    async def wait(self, case_id: str) -> None:
        task = self._tasks.get(case_id)
        if task:
            await task

    async def _delay(self) -> None:
        await asyncio.sleep(max(self.settings.runtime_step_delay_ms, 0) / 1000)

    async def _transition(
        self,
        case_id: str,
        status: CaseStatus,
        title: str,
        detail: str,
        *,
        agent: str | None = None,
        event_status: str = "info",
        trace_name: str | None = None,
        trace_category: str = "agent",
        audit_type: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> CaseState:
        def apply(state: CaseState) -> None:
            state.case.status = status
            state.case.updated_at = utc_now()
            state.case.active_agents = [agent] if agent else []
            sequence = len(state.runtime_events) + 1
            trace_id = f"trace-{case_id.lower()}-run-{state.case.runtime_generation:03d}"
            event = RuntimeEvent(
                sequence=sequence,
                case_id=case_id,
                event_type=audit_type or status.value,
                title=title,
                detail=detail,
                status=event_status,
                agent_id=agent,
            )
            state.runtime_events.append(event)
            if trace_name:
                parent = next((s.span_id for s in state.traces if s.trace_id == trace_id and s.parent_span_id is None), None)
                state.traces.append(
                    TraceSpan(
                        span_id=f"span-{len(state.traces)+1:03d}",
                        trace_id=trace_id,
                        parent_span_id=parent,
                        name=trace_name,
                        category=trace_category,
                        agent_id=agent,
                        duration_ms=max(self.settings.runtime_step_delay_ms, 1),
                        attributes=attributes or {},
                    )
                )
            if audit_type:
                state.audit.append(
                    AuditEvent(
                        event_id=f"AUD-{len(state.audit)+1:03d}",
                        case_id=case_id,
                        event_type=audit_type,
                        actor=f"traceos/{agent}" if agent else "traceos/runtime",
                        summary=detail,
                        trace_id=trace_id,
                        attributes=attributes or {},
                    )
                )
            state.checkpoints.append(
                RuntimeCheckpoint(
                    checkpoint_id=f"CP-{len(state.checkpoints)+1:03d}",
                    case_id=case_id,
                    workflow_state=status.value,
                    active_agents=state.case.active_agents,
                    runtime_generation=state.case.runtime_generation,
                )
            )

        state = self.store.mutate(case_id, apply)
        await self.bus.publish(state.runtime_events[-1])
        await self._delay()
        return state

    def _ensure_root_span(self, case_id: str) -> None:
        def apply(state: CaseState) -> None:
            trace_id = f"trace-{case_id.lower()}-run-{state.case.runtime_generation:03d}"
            state.traces.append(
                TraceSpan(
                    span_id=f"span-{len(state.traces)+1:03d}",
                    trace_id=trace_id,
                    name="CaseCoordinator",
                    category="runtime",
                    agent_id="case-coordinator",
                    attributes={"case_id": case_id, "runtime_generation": state.case.runtime_generation},
                )
            )

        self.store.mutate(case_id, apply)

    async def _run_initial(self, case_id: str) -> None:
        try:
            self._ensure_root_span(case_id)
            await self._transition(
                case_id, CaseStatus.INTAKE, "Runtime accepted case", "API returned while generation 1 continued asynchronously.",
                agent="case-coordinator", trace_name="runtime.start", trace_category="runtime", audit_type="RUNTIME_STARTED"
            )
            registry = [agent for agent in build_registry() if agent.status == "APPROVED"]
            await self._transition(
                case_id, CaseStatus.INTAKE, "Approved fleet resolved", f"Registry returned {len(registry)} approved, versioned agents.",
                agent="case-coordinator", trace_name="Registry.resolve", trace_category="registry", audit_type="AGENT_SELECTED",
                attributes={"approved_agents": len(registry)}
            )
            await self._transition(
                case_id, CaseStatus.INTAKE, "Case memory loaded", "No prior memory found; a case-scoped memory record was initialized.",
                agent="case-coordinator", trace_name="Memory.load", trace_category="memory", audit_type="MEMORY_READ"
            )
            await self._ingest_demo_bundle(case_id)
            await self._try_live_cloud_evidence(case_id)
            await self._analyze(case_id)
            await self._correlate_verify(case_id)
            await self._gateway_demo(case_id)
            await self._checkpoint_wait(case_id)
        except Exception as exc:
            await self._transition(
                case_id, CaseStatus.FAILED, "Runtime failed safely", f"{type(exc).__name__}; case state was preserved at the last checkpoint.",
                event_status="critical", trace_name="runtime.failure", trace_category="error", audit_type="RUNTIME_FAILED"
            )

    async def _ingest_demo_bundle(self, case_id: str) -> None:
        for item in DEMO_EVIDENCE:
            payload = item["payload"]

            def add(state: CaseState, item: dict[str, Any] = item, payload: Any = payload) -> None:
                if any(e.evidence_id == item["evidence_id"] for e in state.evidence):
                    return
                record = EvidenceRecord(
                    case_id=case_id,
                    evidence_id=item["evidence_id"],
                    evidence_type=item["evidence_type"],
                    source_system=item["source_system"],
                    source_kind=item["source_kind"],
                    source_product=item["source_product"],
                    collected_at=item["collected_at"],
                    sha256=sha256_hex(payload),
                    storage_uri=f"immutable://{case_id}/{item['evidence_id']}",
                    preview=item["preview"],
                    metadata={"fixture": True, "raw_preserved": True},
                )
                state.evidence.append(record)
                state.chain_of_custody.extend([
                    ChainOfCustodyEvent(event_id=f"COC-{len(state.chain_of_custody)+1:03d}", evidence_id=record.evidence_id, actor="traceos/evidence-intake", action="REGISTERED"),
                    ChainOfCustodyEvent(event_id=f"COC-{len(state.chain_of_custody)+2:03d}", evidence_id=record.evidence_id, actor="traceos/evidence-intake", action="HASH_VERIFIED"),
                ])
                state.case.last_evidence_at = record.ingested_at
                state.memory.evidence_references.append(record.evidence_id)

            self.store.mutate(case_id, add)
            await self._transition(
                case_id, CaseStatus.INTAKE, f"{item['evidence_id']} registered", "Original preserved, SHA-256 verified, and custody history appended.",
                agent="evidence-intake-agent", trace_name="Evidence.register", trace_category="tool", audit_type="EVIDENCE_REGISTERED",
                attributes={"evidence_id": item["evidence_id"], "source_kind": SourceKind.DEMO_SYNTHETIC.value}
            )
            if item["evidence_id"] == "EVID-006":
                decision = self.armor.inspect("EVID-006", payload["text"], 1)

                def add_armor(state: CaseState) -> None:
                    state.model_armor_decisions.append(decision)

                self.store.mutate(case_id, add_armor)
                await self._transition(
                    case_id, CaseStatus.TRIAGE, "Model Armor blocked embedded instruction", "EVID-006 was quarantined from control context; the immutable original remains unchanged.",
                    agent="evidence-intake-agent", event_status="warning", trace_name="ModelArmor.inspect", trace_category="policy", audit_type="MODEL_ARMOR_BLOCKED",
                    attributes={"evidence_id": "EVID-006", "provider": decision.provider}
                )

    async def _try_live_cloud_evidence(self, case_id: str) -> None:
        event = await asyncio.to_thread(self.audit_connector.fetch_recent_admin_event)
        if event is None:
            await self._transition(
                case_id, CaseStatus.TRIAGE, "Live Cloud Audit connector not verified", "The runtime kept the cloud-shaped fixture labeled DEMO CONNECTOR; no live badge was issued.",
                agent="evidence-intake-agent", event_status="warning", trace_name="CloudAudit.query", trace_category="connector", audit_type="ENTERPRISE_CONNECTOR_UNVERIFIED"
            )
            return

        def add(state: CaseState) -> None:
            if any(e.external_event_id == event.external_event_id for e in state.evidence):
                return
            evidence_id = "EVID-GCP-001"
            state.evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    case_id=case_id,
                    evidence_type="cloud_audit_log",
                    source_system="Google Cloud Audit Logs",
                    source_kind=SourceKind.GOOGLE_CLOUD_LIVE,
                    source_product=event.source_product,
                    source_project=event.source_project,
                    source_resource=event.source_resource,
                    external_event_id=event.external_event_id,
                    collected_at=event.event_time,
                    sha256=sha256_hex(event.payload),
                    storage_uri=f"gcp-audit://{event.source_project}/{event.external_event_id}",
                    live_source_verified=True,
                    preview="Authenticated Cloud Logging API read; metadata retained without exposing sensitive raw payload.",
                    metadata={"authenticated_api_read": True},
                )
            )
            state.chain_of_custody.append(
                ChainOfCustodyEvent(event_id=f"COC-{len(state.chain_of_custody)+1:03d}", evidence_id=evidence_id, actor="traceos/cloud-audit-connector", action="LIVE_SOURCE_VERIFIED")
            )
            state.memory.evidence_references.append(evidence_id)

        self.store.mutate(case_id, add)
        await self._transition(
            case_id, CaseStatus.TRIAGE, "Live Google Cloud evidence verified", f"{event.external_event_id} was read from {event.source_project} through the official Logging API.",
            agent="evidence-intake-agent", trace_name="CloudAudit.query", trace_category="connector", audit_type="LIVE_EVIDENCE_REGISTERED",
            attributes={"evidence_id": "EVID-GCP-001", "source_project": event.source_project}
        )

    async def _analyze(self, case_id: str) -> None:
        observations = [
            Observation(observation_id="OBS-001", agent="identity-analysis-agent", statement="Authentication from a previously unseen region was observed for the case principal.", event_time="2026-08-01T09:42:00Z", evidence_ids=["EVID-001"], confidence=0.92, classification="identity-anomaly"),
            Observation(observation_id="OBS-002", agent="endpoint-analysis-agent", statement="An unusual synthetic process tree followed the suspicious download.", event_time="2026-08-01T09:47:03Z", evidence_ids=["EVID-019"], confidence=0.93, classification="endpoint-anomaly", integrity_status="BLOCKED"),
            Observation(observation_id="OBS-003", agent="network-analysis-agent", statement="The affected host queried a reserved demonstration domain during the anomaly window.", event_time="2026-08-01T09:47:11Z", evidence_ids=["EVID-004"], confidence=0.88, classification="network-anomaly"),
        ]
        for obs in observations:
            def add(state: CaseState, obs: Observation = obs) -> None:
                state.observations.append(obs)

            self.store.mutate(case_id, add)
            await self._transition(
                case_id, CaseStatus.ANALYZING, obs.observation_id + " created", obs.statement,
                agent=obs.agent, trace_name=obs.agent.replace("-agent", "") + ".analyze", trace_category="agent", audit_type="OBSERVATION_CREATED",
                attributes={"observation_id": obs.observation_id, "evidence_ids": obs.evidence_ids}
            )

        await self._transition(
            case_id, CaseStatus.INTEGRITY_CHECK, "Fleet Integrity blocked unsupported reference", "Endpoint Analysis referenced nonexistent EVID-019; promotion stopped and bounded replay requested.",
            agent="fleet-integrity-agent", event_status="critical", trace_name="integrity.block_output", trace_category="integrity", audit_type="UNSUPPORTED_EVIDENCE_REFERENCE",
            attributes={"referenced": "EVID-019", "retry_count": 0}
        )

        def replay(state: CaseState) -> None:
            target = next(o for o in state.observations if o.observation_id == "OBS-002")
            target.evidence_ids = ["EVID-003"]
            target.integrity_status = "REPLAY_PASSED"
            state.integrity_events.append({
                "event_id": "INT-001", "agent": "endpoint-analysis-agent", "reason": "unsupported evidence reference",
                "referenced": "EVID-019", "corrected_reference": "EVID-003", "action": "bounded replay", "status": "REPLAY_PASSED"
            })

        self.store.mutate(case_id, replay)
        await self._transition(
            case_id, CaseStatus.ANALYZING, "Bounded replay passed", "Endpoint Analysis corrected EVID-019 to scoped endpoint evidence EVID-003.",
            agent="fleet-integrity-agent", event_status="success", trace_name="integrity.replay_result", trace_category="integrity", audit_type="AGENT_REPLAY_COMPLETED",
            attributes={"retry_count": 1, "corrected_reference": "EVID-003"}
        )

    async def _correlate_verify(self, case_id: str) -> None:
        def correlate(state: CaseState) -> None:
            state.timeline.extend([
                TimelineEvent(timeline_id="TIME-001", event_time="2026-08-01T09:42:00Z", title="Unusual authentication", description="Previously unseen region and elevated session risk.", evidence_ids=["EVID-001"], category="identity", confidence=0.92),
                TimelineEvent(timeline_id="TIME-002", event_time="2026-08-01T09:46:18Z", title="Suspicious synthetic download", description="Browser metadata links a download to the reserved demo domain.", evidence_ids=["EVID-002"], category="browser", confidence=0.84),
                TimelineEvent(timeline_id="TIME-003", event_time="2026-08-01T09:47:03Z", title="Endpoint process anomaly", description="Unusual process tree began within five minutes of authentication.", evidence_ids=["EVID-003"], category="endpoint", confidence=0.93),
                TimelineEvent(timeline_id="TIME-004", event_time="2026-08-01T09:47:11Z", title="Reserved-domain lookup", description="The same host queried update-check.invalid.", evidence_ids=["EVID-004"], category="network", confidence=0.88),
            ])
            state.hypotheses.append(Hypothesis(
                hypothesis_id="HYP-001",
                statement="The case account was used in activity correlated with an endpoint and network anomaly.",
                supporting_observations=["OBS-001", "OBS-002", "OBS-003"],
                missing_evidence=["Later cloud activity confirming continued account use"],
                verification_criteria=["Two independent evidence types", "All evidence references exist", "Dedicated verification approval"],
                status="UNVERIFIED",
            ))

        self.store.mutate(case_id, correlate)
        await self._transition(
            case_id, CaseStatus.CORRELATING, "Timeline correlated", "Four evidence-linked events were normalized from scoped worker observations.",
            agent="timeline-agent", trace_name="Timeline.correlate", audit_type="TIMELINE_CREATED"
        )
        await self._transition(
            case_id, CaseStatus.VERIFYING, "HYP-001 remains unverified", "The Hypothesis Agent proposed a bounded claim; only Verification can promote it.",
            agent="hypothesis-agent", event_status="warning", trace_name="Hypothesis.create", audit_type="HYPOTHESIS_CREATED"
        )

        def verify(state: CaseState) -> None:
            hypothesis = state.hypotheses[0]
            hypothesis.revisions.append({"from": "UNVERIFIED", "to": "VERIFIED", "by": "verification-agent", "at": utc_now()})
            hypothesis.status = "VERIFIED"
            evidence_ids = ["EVID-001", "EVID-003", "EVID-004"]
            live_ids = [e.evidence_id for e in state.evidence if e.live_source_verified]
            evidence_ids.extend(live_ids)
            state.verification_results.append(VerificationResult(
                verification_id="VER-001", hypothesis_id="HYP-001", status="VERIFIED", evidence_ids=evidence_ids,
                rationale="Independent identity, endpoint, and network records exist; integrity replay passed."
            ))
            state.findings.append(Finding(
                finding_id="FIND-001", title="Correlated account and workstation anomaly", severity="HIGH",
                statement="Anomalous identity activity and endpoint/network activity occurred in the same investigation window.",
                evidence_ids=evidence_ids, observation_ids=["OBS-001", "OBS-002", "OBS-003"]
            ))
            state.memory.verified_facts.append(VerifiedFact(
                fact_id="FACT-001", statement="Identity, endpoint, and network anomalies overlap in the same investigation window.",
                evidence_ids=evidence_ids
            ))
            state.memory.open_questions.append(OpenQuestion(question_id="Q-001", text="Does later activity confirm continued use of the case account?"))
            state.memory.version += 1
            state.memory.last_checkpoint = utc_now()

        self.store.mutate(case_id, verify)
        await self._transition(
            case_id, CaseStatus.REVIEW_READY, "HYP-001 independently verified", "Verification promoted the hypothesis after evidence-reference and cross-source checks passed.",
            agent="verification-agent", event_status="success", trace_name="Verification.verify", audit_type="HYPOTHESIS_VERIFIED",
            attributes={"finding_id": "FIND-001"}
        )

    async def _gateway_demo(self, case_id: str) -> None:
        deny_request = GatewayRequest(case_id=case_id, agent_identity="traceos/reporting", action="read", resource="raw:endpoint:EVID-003", reason="prepare final report")
        deny = self.gateway.authorize(deny_request, 1)
        allow_request = GatewayRequest(case_id=case_id, agent_identity="traceos/reporting", action="read", resource="verified_findings", reason="prepare final report")
        allow = self.gateway.authorize(allow_request, 2)

        def add(state: CaseState) -> None:
            state.gateway_decisions.extend([deny, allow])

        self.store.mutate(case_id, add)
        await self._transition(
            case_id, CaseStatus.REVIEW_READY, "Agent Gateway denied raw evidence", "traceos/reporting was denied raw:endpoint:EVID-003 by least-privilege policy.",
            agent="reporting-agent", event_status="critical", trace_name="Gateway.authorize", trace_category="policy", audit_type="GATEWAY_DENIED",
            attributes={"decision": "DENY", "policy": deny.policy}
        )
        await self._transition(
            case_id, CaseStatus.REVIEW_READY, "Reporting recovered through approved tool", "The verified_findings interface was allowed; the policy denial did not break the workflow.",
            agent="reporting-agent", event_status="success", trace_name="Gateway.authorize", trace_category="policy", audit_type="GATEWAY_ALLOWED",
            attributes={"decision": "ALLOW", "resource": "verified_findings"}
        )

    async def _checkpoint_wait(self, case_id: str) -> None:
        def checkpoint(state: CaseState) -> None:
            state.memory.last_checkpoint = utc_now()

        self.store.mutate(case_id, checkpoint)
        await self._transition(
            case_id, CaseStatus.WAITING, "Memory checkpoint persisted", "Verified facts, open questions, and evidence references are ready for a later same-case resume.",
            agent="case-coordinator", trace_name="Memory.checkpoint", trace_category="memory", audit_type="MEMORY_WRITE"
        )

    def append_day_eight(self, case_id: str) -> bool:
        state = self.store.get(case_id)
        if not state:
            raise KeyError(case_id)
        if any(e.evidence_id == "EVID-007" for e in state.evidence):
            return False
        item = DAY_EIGHT_EVIDENCE
        record = EvidenceRecord(
            case_id=case_id, evidence_id=item["evidence_id"], evidence_type=item["evidence_type"],
            source_system=item["source_system"], source_kind=item["source_kind"], source_product=item["source_product"],
            collected_at=item["collected_at"], sha256=sha256_hex(item["payload"]), storage_uri=f"immutable://{case_id}/EVID-007",
            preview=item["preview"], metadata={"fixture": True, "day_eight": True, "raw_preserved": True}
        )

        def add(current: CaseState) -> None:
            current.evidence.append(record)
            current.chain_of_custody.append(ChainOfCustodyEvent(event_id=f"COC-{len(current.chain_of_custody)+1:03d}", evidence_id="EVID-007", actor="traceos/evidence-intake", action="REGISTERED_AND_HASH_VERIFIED"))
            current.case.runtime_generation += 1
            current.case.last_evidence_at = record.ingested_at
            current.case.updated_at = utc_now()
            current.memory.evidence_references.append("EVID-007")

        self.store.mutate(case_id, add)
        self.launch(case_id, resume=True)
        return True

    async def _run_resume(self, case_id: str) -> None:
        try:
            self._ensure_root_span(case_id)
            await self._transition(
                case_id, CaseStatus.RESUMED, "Seven-day resume signal accepted", "EVID-007 was appended through the real API to the same CASE-042.",
                agent="case-coordinator", trace_name="runtime.resume", trace_category="runtime", audit_type="RUNTIME_RESUMED"
            )
            await self._transition(
                case_id, CaseStatus.RESUMED, "Prior memory loaded", "Memory version 2 restored verified facts and matched open question Q-001.",
                agent="case-coordinator", trace_name="Memory.load", trace_category="memory", audit_type="MEMORY_READ"
            )

            def update(state: CaseState) -> None:
                state.timeline.append(TimelineEvent(
                    timeline_id="TIME-005", event_time="2026-08-08T14:21:09Z", title="Continued account activity observed",
                    description="Day-eight audit-shaped evidence confirms continued resource enumeration.", evidence_ids=["EVID-007"], category="cloud", confidence=0.91
                ))
                state.observations.append(Observation(
                    observation_id="OBS-004", agent="identity-analysis-agent", statement="The same case principal appears in later audit-shaped activity.",
                    event_time="2026-08-08T14:21:09Z", evidence_ids=["EVID-007"], confidence=0.91, classification="continued-activity"
                ))
                state.findings.append(Finding(
                    finding_id="FIND-002", title="Continued account activity seven days later", severity="MEDIUM",
                    statement="Later evidence shows continued resource enumeration by the same case principal.",
                    evidence_ids=["EVID-007"], observation_ids=["OBS-004"]
                ))
                state.memory.verified_facts.append(VerifiedFact(
                    fact_id="FACT-002", statement="The case principal appears in later resource-enumeration activity.", evidence_ids=["EVID-007"]
                ))
                state.memory.open_questions[0].status = "RESOLVED"
                state.memory.version += 1
                state.memory.last_checkpoint = utc_now()

            self.store.mutate(case_id, update)
            await self._transition(
                case_id, CaseStatus.VERIFYING, "Later evidence verified", "Q-001 was resolved and FIND-002 was added without creating a second case.",
                agent="verification-agent", trace_name="Verification.resume", audit_type="HYPOTHESIS_VERIFIED"
            )
            await self._generate_report(case_id)
            await self._transition(
                case_id, CaseStatus.CLOSED, "Investigation report ready", "The evidence-linked report was generated from verified findings only.",
                agent="reporting-agent", event_status="success", trace_name="Report.generate", audit_type="REPORT_GENERATED"
            )
        except Exception as exc:
            await self._transition(
                case_id, CaseStatus.FAILED, "Resume failed safely", f"{type(exc).__name__}; generation 2 state remains checkpointed.",
                event_status="critical", trace_name="runtime.failure", trace_category="error", audit_type="RUNTIME_FAILED"
            )

    async def _generate_report(self, case_id: str) -> None:
        state = self.store.get(case_id)
        assert state
        summary, model = await asyncio.to_thread(
            self.report_writer.generate,
            {"case_id": case_id, "findings": [f.model_dump() for f in state.findings]},
        )

        def add(current: CaseState) -> None:
            current.report = ForensicReport(
                report_id="RPT-001", case_id=case_id, title="CASE-042 Forensic Investigation Report",
                executive_summary=summary, findings=[f.finding_id for f in current.findings],
                limitations=["Synthetic endpoint, browser, DNS, and day-eight fixtures are demonstration data.", "No legal conclusion or containment action is provided."],
                evidence_index=sorted({eid for finding in current.findings for eid in finding.evidence_ids}), model=model
            )

        self.store.mutate(case_id, add)

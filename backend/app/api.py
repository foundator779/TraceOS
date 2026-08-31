from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .cloud import CloudAuditConnector, integration_catalog, verify_pubsub_identity
from .config import Settings, get_settings
from .demo_data import build_registry
from .evidence import EvidenceStorage, demo_evidence_png, validate_image
from .gemini import GeminiReportWriter, model_integration_status
from .models import CaseCreate, CaseState, ChainOfCustodyEvent, EvidenceRecord, SourceKind, utc_now
from .multimodal import analyze_registered_image
from .replay import build_replay
from .runtime import InvestigationRuntime
from .security import sha256_hex
from .store import CaseStore, FirestoreCaseStore
from .training import TrainingPackService, publish_training_job, verify_training_push_identity


class StructuredEventAppend(BaseModel):
    event_type: str
    source_system: str = "external-api"
    event_time: str = Field(default_factory=utc_now)
    payload: dict[str, Any]
    evidence_id: str | None = None
    source_kind: SourceKind = SourceKind.DEMO_SYNTHETIC
    source_product: str = "GENERIC_REST"
    classification: str = "internal"


class EvidenceAppend(BaseModel):
    evidence_type: str
    source_system: str
    collection_time: str
    content: str | dict[str, Any]
    classification: str = "internal"
    source_product: str = "GENERIC_REST"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.store = (
        FirestoreCaseStore(settings.google_cloud_project)
        if settings.traceos_store.lower() == "firestore"
        else CaseStore(settings.traceos_db_path)
    )
    app.state.audit_connector = CloudAuditConnector(settings)
    app.state.report_writer = GeminiReportWriter(settings)
    app.state.evidence_storage = EvidenceStorage(settings)
    app.state.training_service = TrainingPackService(settings, app.state.store)
    app.state.runtime = InvestigationRuntime(
        settings, app.state.store, app.state.audit_connector, app.state.report_writer
    )
    yield
    for task in list(app.state.runtime._tasks.values()):
        if not task.done():
            task.cancel()


app = FastAPI(
    title="TraceOS API",
    version="1.0.0",
    description="Zero-trust autonomous digital-forensics fleet control plane.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def runtime(request: Request) -> InvestigationRuntime:
    return request.app.state.runtime


def store(request: Request) -> CaseStore:
    return request.app.state.store


def settings(request: Request) -> Settings:
    return request.app.state.settings


def require_write_key(
    request: Request,
    x_traceos_api_key: str | None = Header(default=None),
) -> None:
    configured = request.app.state.settings.traceos_api_key
    if configured and x_traceos_api_key != configured:
        raise HTTPException(status_code=401, detail="Valid X-TraceOS-API-Key required")


def require_case(case_id: str, db: CaseStore) -> CaseState:
    state = db.get(case_id.upper())
    if state is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return state


def register_image(
    db: CaseStore,
    storage: EvidenceStorage,
    settings: Settings,
    case_id: str,
    data: bytes,
    mime_type: str,
    source_system: str,
    public_demo: bool = False,
) -> EvidenceRecord:
    state = require_case(case_id, db)
    actual_mime, width, height = validate_image(data, mime_type, settings)
    evidence_id = "EVID-IMG-001" if public_demo else f"EVID-IMG-{sum(e.evidence_type == 'image' for e in state.evidence)+1:03d}"
    existing = next((item for item in state.evidence if item.evidence_id == evidence_id), None)
    if existing:
        return existing
    digest = sha256_hex(data)
    storage_uri = storage.put(case_id, evidence_id, data, actual_mime)
    record = EvidenceRecord(
        evidence_id=evidence_id,
        case_id=case_id,
        evidence_type="image",
        source_system=source_system,
        source_kind=SourceKind.DEMO_SYNTHETIC,
        source_product="VISUAL_EVIDENCE",
        collected_at="2026-08-01T09:42:00Z" if public_demo else utc_now(),
        sha256=digest,
        status="ANALYSIS_QUEUED",
        storage_uri=storage_uri,
        preview="Synthetic sign-in alert queued for observable-facts-only Gemini analysis." if public_demo else "Image evidence queued for observable-facts-only Gemini analysis.",
        metadata={
            "mime_type": actual_mime,
            "width": width,
            "height": height,
            "raw_preserved": True,
            "public_demo": public_demo,
        },
    )
    def add(current: CaseState) -> None:
        current.evidence.append(record)
        current.chain_of_custody.extend([
            ChainOfCustodyEvent(
                event_id=f"COC-{len(current.chain_of_custody)+1:03d}",
                evidence_id=evidence_id,
                actor="traceos/evidence-intake",
                action="REGISTERED",
            ),
            ChainOfCustodyEvent(
                event_id=f"COC-{len(current.chain_of_custody)+2:03d}",
                evidence_id=evidence_id,
                actor="traceos/evidence-intake",
                action="HASH_VERIFIED",
            ),
        ])
        current.memory.evidence_references.append(evidence_id)
        current.case.last_evidence_at = record.ingested_at
        current.case.updated_at = utc_now()
    db.mutate(case_id, add)
    return record


@app.get("/api/v1/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "traceos-api"}


@app.get("/api/v1/readyz")
def readyz(request: Request) -> dict[str, Any]:
    return {
        "status": "ready",
        "database": request.app.state.settings.traceos_store.lower(),
        "gemini_configured": bool(
            request.app.state.settings.google_api_key
            or request.app.state.settings.gemini_use_vertex
        ),
        "cloud_connector_enabled": request.app.state.settings.enable_cloud_connectors,
    }


@app.get("/api/v1/dashboard")
def dashboard(db: CaseStore = Depends(store)) -> dict[str, Any]:
    states = db.list()
    active = {"INTAKE", "TRIAGE", "ANALYZING", "CORRELATING", "INTEGRITY_CHECK", "VERIFYING", "RESUMED", "REPORTING"}
    return {
        "active_investigations": sum(s.case.status.value in active for s in states),
        "waiting_for_evidence": sum(s.case.status.value == "WAITING_FOR_NEW_EVIDENCE" for s in states),
        "policy_blocks": sum(len(s.gateway_decisions) + len(s.model_armor_decisions) for s in states),
        "fleet_health": "HEALTHY",
        "fleet_agents": len(build_registry()),
        "cases": len(states),
    }


@app.get("/api/v1/cases")
def list_cases(db: CaseStore = Depends(store)) -> list[dict[str, Any]]:
    return [
        {
            **state.case.model_dump(mode="json"),
            "evidence_count": len(state.evidence),
            "finding_count": len(state.findings),
            "review_status": state.case.review_status,
        }
        for state in db.list()
    ]


@app.post("/api/v1/cases", status_code=status.HTTP_202_ACCEPTED)
async def create_case(
    payload: CaseCreate,
    request: Request,
    force: bool = False,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_write_key),
) -> dict[str, Any]:
    db: CaseStore = request.app.state.store
    engine: InvestigationRuntime = request.app.state.runtime
    if idempotency_key:
        cached = db.get_idempotent(f"case:{idempotency_key}")
        if cached:
            return cached
    case_id = "CASE-042" if payload.demo_case else f"CASE-{len(db.list())+43:03d}"
    existing = db.get(case_id)
    if existing and not force:
        response = {"case_id": case_id, "status": existing.case.status, "runtime_status": "EXISTING"}
    else:
        if existing:
            db.delete(case_id)
        state = engine.create_case(payload, case_id)
        engine.launch(case_id)
        response = {"case_id": case_id, "status": state.case.status, "runtime_status": "QUEUED"}
    if idempotency_key:
        db.set_idempotent(f"case:{idempotency_key}", json.loads(json.dumps(response, default=str)))
    return response


@app.post("/api/v1/demo/start", status_code=status.HTTP_202_ACCEPTED)
async def start_public_demo(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Bounded public action: no arbitrary input and no repeated paid analysis."""
    db: CaseStore = request.app.state.store
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = db.increment_counter(f"public-demo:{day}")
    if count > request.app.state.settings.demo_daily_run_limit:
        raise HTTPException(status_code=429, detail="Daily public demo limit reached; the completed CASE-042 remains available.")
    state = db.get("CASE-042")
    if state is None:
        state = request.app.state.runtime.create_case(CaseCreate(), "CASE-042")
        request.app.state.runtime.launch("CASE-042")
    record = register_image(
        db,
        request.app.state.evidence_storage,
        request.app.state.settings,
        "CASE-042",
        demo_evidence_png(),
        "image/png",
        "TraceOS synthetic identity alert",
        public_demo=True,
    )
    if record.status == "ANALYSIS_FAILED":
        def retry(current: CaseState) -> None:
            target = next(item for item in current.evidence if item.evidence_id == record.evidence_id)
            target.status = "ANALYSIS_QUEUED"
            target.metadata.pop("analysis_error", None)
            target.metadata.pop("analysis_error_fields", None)
        db.mutate("CASE-042", retry)
        record.status = "ANALYSIS_QUEUED"
    if record.status == "ANALYSIS_QUEUED":
        background_tasks.add_task(
            analyze_registered_image,
            db,
            request.app.state.report_writer,
            request.app.state.evidence_storage,
            "CASE-042",
            record.evidence_id,
        )
    return {
        "case_id": "CASE-042",
        "runtime_status": "EXISTING" if state.case.status.value != "NEW" else "QUEUED",
        "image_evidence_id": record.evidence_id,
        "image_status": record.status,
        "daily_run": count,
        "daily_limit": request.app.state.settings.demo_daily_run_limit,
    }


@app.post("/api/v1/demo/day-eight", status_code=status.HTTP_202_ACCEPTED)
async def public_day_eight(request: Request) -> dict[str, Any]:
    """Bodyless public continuation for the canonical synthetic case only."""
    state = require_case("CASE-042", request.app.state.store)
    if any(e.evidence_id == "EVID-007" for e in state.evidence):
        return {
            "case_id": "CASE-042",
            "runtime_status": "ALREADY_PROCESSED",
            "runtime_generation": state.case.runtime_generation,
        }
    appended = request.app.state.runtime.append_day_eight("CASE-042")
    return {
        "case_id": "CASE-042",
        "runtime_status": "RESUMED" if appended else "ALREADY_PROCESSED",
        "runtime_generation": state.case.runtime_generation + int(appended),
    }


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str, db: CaseStore = Depends(store)) -> CaseState:
    return require_case(case_id, db)


@app.get("/api/v1/cases/{case_id}/replay")
def replay(case_id: str, db: CaseStore = Depends(store)):
    return build_replay(require_case(case_id, db))


@app.get("/api/v1/cases/{case_id}/evidence/{evidence_id}/content")
def evidence_content(case_id: str, evidence_id: str, request: Request) -> Response:
    state = require_case(case_id, request.app.state.store)
    evidence = next((item for item in state.evidence if item.evidence_id == evidence_id), None)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not evidence.metadata.get("public_demo") or evidence.source_kind != SourceKind.DEMO_SYNTHETIC:
        raise HTTPException(status_code=403, detail="Only the synthetic public demo image can be rendered")
    try:
        content = request.app.state.evidence_storage.get(evidence.storage_uri)
    except FileNotFoundError:
        # The fixture is deterministic, so a Cloud Run revision may safely regenerate it.
        content = demo_evidence_png()
    return Response(content=content, media_type=str(evidence.metadata.get("mime_type", "image/png")), headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/v1/cases/{case_id}/evidence/image", status_code=202)
async def append_image_evidence(
    case_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_write_key),
) -> dict[str, Any]:
    db: CaseStore = request.app.state.store
    require_case(case_id.upper(), db)
    if idempotency_key:
        cached = db.get_idempotent(f"image:{case_id}:{idempotency_key}")
        if cached:
            return cached
    data = await file.read(request.app.state.settings.max_image_bytes + 1)
    try:
        record = register_image(
            db,
            request.app.state.evidence_storage,
            request.app.state.settings,
            case_id.upper(),
            data,
            file.content_type or "application/octet-stream",
            file.filename or "uploaded image",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    background_tasks.add_task(
        analyze_registered_image,
        db,
        request.app.state.report_writer,
        request.app.state.evidence_storage,
        case_id.upper(),
        record.evidence_id,
    )
    response = {"case_id": case_id.upper(), "evidence_id": record.evidence_id, "status": record.status, "sha256": record.sha256}
    if idempotency_key:
        db.set_idempotent(f"image:{case_id}:{idempotency_key}", response)
    return response


@app.get("/api/v1/cases/{case_id}/stream")
async def stream_case(case_id: str, request: Request) -> StreamingResponse:
    db: CaseStore = request.app.state.store
    engine: InvestigationRuntime = request.app.state.runtime
    initial = require_case(case_id, db)
    queue = engine.bus.subscribe(case_id.upper())

    async def events() -> AsyncIterator[str]:
        try:
            for item in initial.runtime_events[-30:]:
                yield f"id: {item.sequence}\nevent: runtime\ndata: {item.model_dump_json()}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"id: {item.sequence}\nevent: runtime\ndata: {item.model_dump_json()}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            engine.bus.unsubscribe(case_id.upper(), queue)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/cases/{case_id}/evidence", status_code=202)
def append_evidence(
    case_id: str,
    payload: EvidenceAppend,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_write_key),
) -> dict[str, Any]:
    db: CaseStore = request.app.state.store
    state = require_case(case_id, db)
    if idempotency_key:
        cached = db.get_idempotent(f"evidence:{case_id}:{idempotency_key}")
        if cached:
            return cached
    evidence_id = f"EVID-{len(state.evidence)+1:03d}"

    def add(current: CaseState) -> None:
        current.evidence.append(EvidenceRecord(
            evidence_id=evidence_id, case_id=current.case.case_id, evidence_type=payload.evidence_type,
            source_system=payload.source_system, source_kind=SourceKind.DEMO_SYNTHETIC,
            source_product=payload.source_product, collected_at=payload.collection_time,
            sha256=sha256_hex(payload.content), storage_uri=f"immutable://{current.case.case_id}/{evidence_id}",
            classification=payload.classification, preview="Evidence appended through the public API.",
            metadata={"api_ingested": True, "raw_preserved": True}
        ))
        current.case.last_evidence_at = utc_now()
        current.case.updated_at = utc_now()

    db.mutate(case_id.upper(), add)
    response = {"case_id": case_id.upper(), "evidence_id": evidence_id, "status": "REGISTERED", "sha256_verified": True}
    if idempotency_key:
        db.set_idempotent(f"evidence:{case_id}:{idempotency_key}", response)
    return response


@app.post("/api/v1/cases/{case_id}/events", status_code=202)
async def append_event(
    case_id: str,
    payload: StructuredEventAppend,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(require_write_key),
) -> dict[str, Any]:
    db: CaseStore = request.app.state.store
    engine: InvestigationRuntime = request.app.state.runtime
    state = require_case(case_id, db)
    if idempotency_key:
        cached = db.get_idempotent(f"event:{case_id}:{idempotency_key}")
        if cached:
            return cached
    if payload.event_type == "DAY_EIGHT" or payload.evidence_id == "EVID-007":
        appended = engine.append_day_eight(case_id.upper())
        response = {"case_id": case_id.upper(), "runtime_status": "RESUMED" if appended else "ALREADY_PROCESSED", "runtime_generation": state.case.runtime_generation + int(appended)}
    else:
        evidence_id = payload.evidence_id or f"EVID-{len(state.evidence)+1:03d}"

        def add(current: CaseState) -> None:
            current.evidence.append(EvidenceRecord(
                evidence_id=evidence_id, case_id=current.case.case_id, evidence_type=payload.event_type.lower(),
                source_system=payload.source_system, source_kind=SourceKind.DEMO_SYNTHETIC,
                source_product=payload.source_product, collected_at=payload.event_time,
                sha256=sha256_hex(payload.payload), storage_uri=f"immutable://{current.case.case_id}/{evidence_id}",
                classification=payload.classification, preview="Structured event appended through the public API.",
                metadata={"api_ingested": True, "raw_preserved": True}
            ))
            current.case.last_evidence_at = utc_now()
            current.case.updated_at = utc_now()

        db.mutate(case_id.upper(), add)
        response = {"case_id": case_id.upper(), "evidence_id": evidence_id, "runtime_status": "ENRICHED"}
    if idempotency_key:
        db.set_idempotent(f"event:{case_id}:{idempotency_key}", response)
    return response


@app.post("/api/v1/cases/{case_id}/resume", status_code=202)
async def resume_case(case_id: str, request: Request, _: None = Depends(require_write_key)) -> dict[str, Any]:
    state = require_case(case_id, request.app.state.store)
    if any(e.evidence_id == "EVID-007" for e in state.evidence):
        request.app.state.runtime.launch(case_id.upper(), resume=True)
        return {"case_id": case_id.upper(), "runtime_status": "RESUME_QUEUED"}
    raise HTTPException(status_code=409, detail="Append new evidence before resuming a waiting case")


@app.get("/api/v1/cases/{case_id}/findings")
def findings(case_id: str, db: CaseStore = Depends(store)):
    return require_case(case_id, db).findings


@app.get("/api/v1/cases/{case_id}/timeline")
def timeline(case_id: str, db: CaseStore = Depends(store)):
    return require_case(case_id, db).timeline


@app.get("/api/v1/cases/{case_id}/audit")
def audit(case_id: str, db: CaseStore = Depends(store)):
    return require_case(case_id, db).audit


@app.get("/api/v1/cases/{case_id}/report")
def report(case_id: str, db: CaseStore = Depends(store)):
    state = require_case(case_id, db)
    if not state.report:
        raise HTTPException(status_code=409, detail="Report is available after the seven-day resume completes")
    return state.report


@app.get("/api/v1/cases/{case_id}/report.md", response_class=PlainTextResponse)
def report_markdown(case_id: str, db: CaseStore = Depends(store)) -> str:
    state = require_case(case_id, db)
    if not state.report:
        raise HTTPException(status_code=409, detail="Report not generated")
    report = state.report
    finding_lines = "\n".join(f"- {f.title} — {f.statement} ({', '.join(f.evidence_ids)})" for f in state.findings)
    return f"# {report.title}\n\n## Executive summary\n\n{report.executive_summary}\n\n## Verified findings\n\n{finding_lines}\n\n## Limitations\n\n" + "\n".join(f"- {item}" for item in report.limitations)


@app.get("/api/v1/cases/{case_id}/training-pack")
def get_training_pack(case_id: str, request: Request):
    state = require_case(case_id.upper(), request.app.state.store)
    if state.training_pack:
        return state.training_pack
    if not state.report:
        raise HTTPException(status_code=409, detail="A verified report is required before a training pack can be prepared")
    raise HTTPException(status_code=404, detail="Training pack has not been prepared")


@app.post("/api/v1/cases/{case_id}/training-pack", status_code=202)
def create_training_pack(
    case_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_write_key),
):
    case_id = case_id.upper()
    state = require_case(case_id, request.app.state.store)
    if not state.report:
        raise HTTPException(status_code=409, detail="Close the investigation and generate its verified report first")
    pack, created = request.app.state.training_service.initialize(case_id)
    if not created or pack.status == "DISABLED":
        return pack
    if request.app.state.settings.training_pubsub_topic:
        try:
            message_id = publish_training_job(request.app.state.settings, case_id, pack.report_hash)
        except Exception as exc:
            request.app.state.training_service.mark_queue_unavailable(case_id, type(exc).__name__)
            raise HTTPException(status_code=503, detail="Training queue is unavailable; no model was invoked") from exc
        pack.generation_mode = "PUBSUB_WORKER"
        pack.queue_message_id = message_id
        request.app.state.store.mutate(case_id, lambda current: setattr(current, "training_pack", pack))
        return {**pack.model_dump(mode="json"), "queue_message_id": message_id}
    background_tasks.add_task(request.app.state.training_service.run, case_id)
    return pack


@app.post("/api/v1/internal/training-pack/jobs", status_code=202)
def training_pack_worker(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authenticated Pub/Sub push token required")
    try:
        verify_training_push_identity(authorization[7:], request.app.state.settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Training worker identity verification failed") from exc
    message = payload.get("message", {})
    message_id = message.get("messageId")
    if not message_id or not message.get("data"):
        raise HTTPException(status_code=422, detail="Pub/Sub envelope requires messageId and data")
    try:
        job = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Pub/Sub training job must be base64-encoded JSON") from exc
    case_id = str(job.get("case_id", "")).upper()
    state = require_case(case_id, request.app.state.store)
    if not state.training_pack or state.training_pack.report_hash != job.get("report_hash"):
        raise HTTPException(status_code=409, detail="Training job does not match the current verified report")
    key = f"training-job:{message_id}"
    if request.app.state.store.get_idempotent(key):
        return {"status": "DUPLICATE_IGNORED", "message_id": message_id}
    request.app.state.store.set_idempotent(key, {"status": "ACCEPTED", "message_id": message_id})
    pack = request.app.state.training_service.run(case_id)
    return {"status": pack.status, "message_id": message_id, "case_id": case_id}


@app.post("/api/v1/cases/{case_id}/training-pack/retry", status_code=202)
def retry_training_pack(
    case_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_write_key),
):
    case_id = case_id.upper()
    state = require_case(case_id, request.app.state.store)
    if (
        not state.training_pack
        or state.training_pack.status != "PARTIAL"
        or any(
            item.retry_count >= request.app.state.settings.training_max_artifact_retries
            for item in state.training_pack.artifacts
            if item.status == "ARTIFACT_UNAVAILABLE"
        )
    ):
        raise HTTPException(status_code=409, detail="No bounded artifact retry is available")
    background_tasks.add_task(request.app.state.training_service.retry_failed, case_id)
    return {
        "case_id": case_id,
        "status": "RETRY_QUEUED",
        "maximum_retries": request.app.state.settings.training_max_artifact_retries,
    }


@app.get("/api/v1/cases/{case_id}/training-pack/artifacts/{artifact_id}/content")
def training_artifact_content(case_id: str, artifact_id: str, request: Request) -> Response:
    state = require_case(case_id.upper(), request.app.state.store)
    if not state.training_pack:
        raise HTTPException(status_code=404, detail="Training pack not found")
    artifact = next(
        (item for item in state.training_pack.artifacts if item.artifact_id == artifact_id),
        None,
    )
    if not artifact or artifact.status != "READY" or not artifact.storage_uri:
        raise HTTPException(status_code=404, detail="Training artifact is not ready")
    data = request.app.state.training_service.storage.get(artifact.storage_uri)
    if artifact.sha256 and hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise HTTPException(status_code=409, detail="Training artifact integrity check failed")
    return Response(
        content=data,
        media_type=artifact.mime_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-TraceOS-Artifact-Class": "SYNTHETIC-TRAINING-NOT-EVIDENCE",
        },
    )


@app.get("/api/v1/fleet")
def fleet(request: Request):
    deployed = os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID") is not None
    cases = request.app.state.store.list()
    active_ids = {agent for state in cases for agent in state.case.active_agents}
    manifests = build_registry(deployed)
    for manifest in manifests:
        manifest.active_cases = int(manifest.agent_id in active_ids)
    return manifests


@app.get("/api/v1/integrations")
def integrations(request: Request):
    catalog = integration_catalog(request.app.state.settings, request.app.state.audit_connector)
    live = [e for state in request.app.state.store.list() for e in state.evidence if e.live_source_verified]
    if live:
        latest = max(live, key=lambda item: item.ingested_at)
        catalog[0].status = "CONNECTED"
        catalog[0].last_verified_at = latest.ingested_at
        catalog[0].detail = f"Persisted authenticated evidence from {latest.source_project}."
    return catalog


@app.post("/api/v1/integrations/cloud-audit/verify")
async def verify_cloud_audit(request: Request, _: None = Depends(require_write_key)) -> dict[str, Any]:
    event = await asyncio.to_thread(request.app.state.audit_connector.fetch_recent_admin_event)
    return {"verified": event is not None, "event": event, "status": request.app.state.audit_connector.status()}


@app.post("/api/v1/ingest/scc", status_code=202)
def ingest_scc(payload: dict[str, Any], request: Request, _: None = Depends(require_write_key)) -> dict[str, Any]:
    # SCC Pub/Sub envelopes are accepted and correlated, but they are not labeled live
    # until deployment-level authenticated push/IAM has been configured and documented.
    message_id = payload.get("message", {}).get("messageId") or payload.get("finding", {}).get("name")
    if not message_id:
        raise HTTPException(status_code=422, detail="SCC Pub/Sub envelope requires a message or finding identifier")
    return {"status": "QUARANTINED_PENDING_SOURCE_VERIFICATION", "external_event_id": message_id, "source_kind": "GOOGLE_CLOUD_LIVE", "live_source_verified": False}


@app.post("/api/v1/ingest/cloud-audit", status_code=202)
def ingest_cloud_audit(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authenticated Pub/Sub push token required")
    try:
        verify_pubsub_identity(authorization[7:], request.app.state.settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Pub/Sub push identity verification failed") from exc
    message = payload.get("message", {})
    message_id = message.get("messageId")
    if not message_id or not message.get("data"):
        raise HTTPException(status_code=422, detail="Pub/Sub envelope requires messageId and data")
    try:
        event = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Pub/Sub data must be base64-encoded JSON") from exc
    db: CaseStore = request.app.state.store
    if db.get_idempotent(f"cloud-audit:{message_id}"):
        return {"status": "DUPLICATE_IGNORED", "external_event_id": message_id}
    state = require_case("CASE-042", db)
    # Pub/Sub can deliver several events concurrently. A count-based identifier can
    # therefore collide; derive the evidence ID from the immutable message ID instead.
    evidence_id = f"EVID-GCP-PUSH-{hashlib.sha256(message_id.encode('utf-8')).hexdigest()[:12].upper()}"
    proto = event.get("protoPayload", {})
    record = EvidenceRecord(
        evidence_id=evidence_id,
        case_id="CASE-042",
        evidence_type="cloud_audit_log",
        source_system="Google Cloud Audit Logs",
        source_kind=SourceKind.GOOGLE_CLOUD_LIVE,
        source_product="CLOUD_AUDIT_LOGS_PUBSUB",
        source_project=event.get("resource", {}).get("labels", {}).get("project_id", request.app.state.settings.google_cloud_project),
        source_resource=proto.get("resourceName", "unknown"),
        external_event_id=event.get("insertId", message_id),
        collected_at=event.get("timestamp", utc_now()),
        sha256=sha256_hex(event),
        storage_uri=f"gcp-audit-pubsub://{message_id}",
        live_source_verified=True,
        preview="Authenticated Logging sink delivery through Pub/Sub; raw payload hash preserved.",
        metadata={"pubsub_message_id": message_id, "authenticated_push": True},
    )
    inserted = False

    def append_once(current: CaseState) -> None:
        nonlocal inserted
        if any(
            item.evidence_id == evidence_id
            or item.metadata.get("pubsub_message_id") == message_id
            for item in current.evidence
        ):
            return
        current.evidence.append(record)
        inserted = True

    db.mutate("CASE-042", append_once)
    if not inserted:
        response = {"status": "DUPLICATE_IGNORED", "external_event_id": message_id, "evidence_id": evidence_id}
        db.set_idempotent(f"cloud-audit:{message_id}", response)
        return response
    response = {"status": "INGESTED", "external_event_id": message_id, "evidence_id": evidence_id}
    db.set_idempotent(f"cloud-audit:{message_id}", response)
    return response


@app.get("/api/v1/system/model-integrations")
def models(request: Request):
    states = request.app.state.store.list()
    invocations = [
        observation.event_time
        for state in states
        for observation in state.observations
        if observation.model == request.app.state.settings.gemini_model
    ]
    invocations.extend(
        state.report.generated_at
        for state in states
        if state.report and state.report.model == request.app.state.settings.gemini_model
    )
    additional: dict[str, dict[str, Any]] = {}
    for state in states:
        pack = state.training_pack
        if not pack:
            continue
        if pack.gemma_verdict:
            additional["Gemma"] = {
                "status": pack.gemma_verdict.status,
                "last_successful_invocation": pack.gemma_verdict.created_at,
                "operation_id": pack.gemma_verdict.operation_id,
                "estimated_cost_usd": pack.gemma_verdict.estimated_cost_usd,
            }
        for artifact in pack.artifacts:
            if artifact.status == "READY":
                additional[artifact.model_family] = {
                    "status": "CONNECTED",
                    "last_successful_invocation": artifact.completed_at,
                    "operation_id": artifact.operation_id,
                    "estimated_cost_usd": artifact.estimated_cost_usd,
                }
    return model_integration_status(
        request.app.state.settings,
        request.app.state.report_writer,
        max(invocations) if invocations else None,
        additional,
    )


@app.get("/api/v1/system/security-controls")
def security_controls(request: Request) -> dict[str, Any]:
    decisions = [d for state in request.app.state.store.list() for d in state.model_armor_decisions]
    managed = [d for d in decisions if d.provider == "GOOGLE_CLOUD_MODEL_ARMOR"]
    return {
        "model_armor": {
            "status": "CONNECTED" if managed else ("CONFIGURED" if request.app.state.settings.enable_model_armor else "LOCAL_FALLBACK"),
            "last_verified_at": max((d.timestamp for d in managed), default=None),
        },
        "agent_gateway": {
            "status": request.app.state.settings.agent_gateway_status,
            "managed_claim": request.app.state.settings.agent_gateway_status == "CONNECTED",
            "fallback": "APPLICATION_POLICY_GATEWAY",
        },
        "security_command_center": {"status": "NOT_CONNECTED"},
    }


@app.exception_handler(KeyError)
def key_error_handler(_: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": f"Case {exc.args[0]} not found"})


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

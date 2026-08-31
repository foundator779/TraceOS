from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .models import EnterpriseSourceEvent, IntegrationStatus, SourceKind, utc_now


def verify_pubsub_identity(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.pubsub_push_audience or not settings.pubsub_push_service_account:
        raise ValueError("Pub/Sub push identity is not configured")
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    claims = id_token.verify_oauth2_token(
        token,
        Request(),
        audience=settings.pubsub_push_audience,
    )
    if claims.get("email") != settings.pubsub_push_service_account:
        raise ValueError("Unexpected Pub/Sub push service account")
    if str(claims.get("email_verified", "false")).lower() != "true":
        raise ValueError("Pub/Sub push identity email is not verified")
    return claims


class CloudAuditConnector:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_error: str | None = None
        self.last_verified_at: str | None = None

    def status(self) -> IntegrationStatus:
        if self.last_verified_at:
            return IntegrationStatus(
                id="cloud_audit_logs",
                name="Google Cloud Audit Logs",
                status="CONNECTED",
                mode="SCOPED_LOGGING_API",
                source_kind=SourceKind.GOOGLE_CLOUD_LIVE,
                last_verified_at=self.last_verified_at,
                detail=f"Authenticated read verified for {self.settings.google_cloud_project}.",
            )
        detail = "Connector disabled; enable it with an authenticated least-privilege service identity."
        if self.settings.enable_cloud_connectors:
            detail = self.last_error or "Configured; awaiting a successful authenticated read."
        return IntegrationStatus(
            id="cloud_audit_logs",
            name="Google Cloud Audit Logs",
            status="CONFIGURED" if self.settings.enable_cloud_connectors else "NOT_CONNECTED",
            mode="SCOPED_LOGGING_API",
            source_kind=SourceKind.GOOGLE_CLOUD_LIVE,
            detail=detail,
        )

    def fetch_recent_admin_event(self) -> EnterpriseSourceEvent | None:
        if not self.settings.enable_cloud_connectors:
            return None
        try:
            from google.cloud import logging_v2

            client = logging_v2.Client(project=self.settings.google_cloud_project)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            log_filter = (
                'logName:"cloudaudit.googleapis.com%2Factivity" '
                f'AND timestamp>="{cutoff}"'
            )
            entry = next(iter(client.list_entries(filter_=log_filter, order_by="timestamp desc", page_size=1)), None)
            if entry is None:
                self.last_error = "Authenticated, but no recent Admin Activity event matched the scoped query."
                return None
            payload: dict[str, Any] = entry.payload if isinstance(entry.payload, dict) else {"message": str(entry.payload)}
            resource = getattr(entry, "resource", None)
            resource_name = str(getattr(resource, "labels", {}).get("resource_name", "unknown"))
            insert_id = entry.insert_id or f"audit-{int(entry.timestamp.timestamp())}"
            self.last_verified_at = utc_now()
            self.last_error = None
            return EnterpriseSourceEvent(
                external_event_id=insert_id,
                source_product="CLOUD_AUDIT_LOGS",
                source_project=self.settings.google_cloud_project,
                source_resource=resource_name,
                event_time=entry.timestamp.isoformat().replace("+00:00", "Z"),
                payload={
                    "log_name": entry.log_name,
                    "resource_type": getattr(resource, "type", "unknown"),
                    "protoPayload": payload,
                    "labels": dict(entry.labels or {}),
                },
            )
        except Exception as exc:
            self.last_error = f"Live verification failed: {type(exc).__name__}."
            return None


def integration_catalog(settings: Settings, audit: CloudAuditConnector) -> list[IntegrationStatus]:
    return [
        audit.status(),
        IntegrationStatus(
            id="security_command_center",
            name="Security Command Center",
            status="NOT_CONNECTED",
            mode="PUBSUB_NOTIFICATION",
            source_kind=SourceKind.GOOGLE_CLOUD_LIVE,
            detail="Optional connector is implemented at /api/v1/ingest/scc; notification configuration is not yet verified.",
        ),
        IntegrationStatus(
            id="demo_edr", name="Synthetic EDR", status="READY", mode="DEMO_FIXTURE",
            source_kind=SourceKind.DEMO_SYNTHETIC, detail="Deterministic endpoint telemetry for CASE-042."
        ),
        IntegrationStatus(
            id="demo_dns", name="Synthetic DNS", status="READY", mode="DEMO_FIXTURE",
            source_kind=SourceKind.DEMO_SYNTHETIC, detail="Reserved .invalid-domain network telemetry."
        ),
        IntegrationStatus(
            id="demo_browser", name="Synthetic Browser", status="READY", mode="DEMO_FIXTURE",
            source_kind=SourceKind.DEMO_SYNTHETIC, detail="Safe download metadata; no executable payloads."
        ),
    ]

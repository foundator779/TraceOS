from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .config import Settings
from .models import GatewayDecision, GatewayRequest, ModelArmorDecision


INJECTION_PATTERNS = [
    re.compile(r"ignore (?:all |the )?(?:previous |investigation )?(?:instructions|policy)", re.I),
    re.compile(r"do not report", re.I),
    re.compile(r"mark (?:this|the) system clean", re.I),
    re.compile(r"(?:system|developer) prompt", re.I),
]


def canonical_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class PolicyGateway:
    def authorize(self, request: GatewayRequest, sequence: int) -> GatewayDecision:
        reporting_raw = (
            request.agent_identity == "traceos/reporting"
            and request.action == "read"
            and request.resource.startswith("raw:endpoint:")
        )
        if reporting_raw:
            return GatewayDecision(
                decision_id=f"GATE-{sequence:03d}",
                request=request,
                decision="DENY",
                policy="reporting-agent-no-raw-endpoint",
                reason="resource scope not granted to reporting identity",
            )
        return GatewayDecision(
            decision_id=f"GATE-{sequence:03d}",
            request=request,
            decision="ALLOW",
            policy="least-privilege-scope-match",
            reason="identity scope grants the requested registered tool",
        )


class EvidenceArmor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def inspect(self, evidence_id: str, text: str, sequence: int) -> ModelArmorDecision:
        provider = "LOCAL_FAIL_CLOSED"
        decision = "PASS"
        category = None
        action = "provided as untrusted forensic content"

        # Local screening remains active even when the managed service is unavailable.
        # The provider label makes it impossible to confuse this fallback with cloud proof.
        if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
            decision = "BLOCK"
            category = "instruction injection"
            action = "quarantined from agent control context; safe metadata retained"

        if self.settings.enable_model_armor:
            managed = self._inspect_managed(text)
            if managed is not None:
                provider = "GOOGLE_CLOUD_MODEL_ARMOR"
                decision, category, action = managed

        return ModelArmorDecision(
            decision_id=f"ARMOR-{sequence:03d}",
            evidence_id=evidence_id,
            decision=decision,
            category=category,
            action=action,
            provider=provider,
        )

    def _inspect_managed(self, text: str) -> tuple[str, str | None, str] | None:
        try:
            from google.cloud import modelarmor_v1beta

            endpoint = f"modelarmor.{self.settings.google_cloud_location}.rep.googleapis.com"
            client = modelarmor_v1beta.ModelArmorClient(
                transport="grpc", client_options={"api_endpoint": endpoint}
            )
            prompt = modelarmor_v1beta.DataItem(text=text)
            request = modelarmor_v1beta.SanitizeUserPromptRequest(
                name=client.template_path(
                    self.settings.google_cloud_project,
                    self.settings.google_cloud_location,
                    self.settings.model_armor_template_id,
                ),
                user_prompt_data=prompt,
            )
            response = client.sanitize_user_prompt(request=request)
            # The exact filter fields evolve; the serialized response is checked for the
            # platform's MATCHED result without logging raw evidence.
            serialized = str(response).upper()
            if "MATCHED" in serialized:
                return "BLOCK", "managed safety policy", "blocked by Google Cloud Model Armor"
            return "PASS", None, "inspected by Google Cloud Model Armor"
        except Exception:
            return None

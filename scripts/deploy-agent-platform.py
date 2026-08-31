"""Deploy the TraceOS ADK fleet to Gemini Enterprise Agent Runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
import vertexai
from vertexai import agent_engines, types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.agent import root_agent  # noqa: E402


def cloud_sdk_credentials() -> Credentials:
    gcloud = shutil.which("gcloud")
    if not gcloud and os.name == "nt":
        candidate = (
            Path(os.environ["LOCALAPPDATA"])
            / "Google"
            / "Cloud SDK"
            / "google-cloud-sdk"
            / "bin"
            / "gcloud.cmd"
        )
        if candidate.exists():
            gcloud = str(candidate)
    if not gcloud:
        raise RuntimeError("gcloud CLI was not found")
    token = subprocess.check_output(
        [gcloud, "auth", "print-access-token"], text=True
    ).strip()
    if not token:
        raise RuntimeError("gcloud did not return an access token")
    return Credentials(token=token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="traceos-506713")
    parser.add_argument("--location", default="northamerica-northeast1")
    parser.add_argument("--staging-bucket", default="gs://traceos-506713-agent-platform-ca")
    args = parser.parse_args()
    os.chdir(ROOT / "backend")

    credentials = cloud_sdk_credentials()
    vertexai.init(
        project=args.project,
        location=args.location,
        credentials=credentials,
        staging_bucket=args.staging_bucket,
    )
    client = vertexai.Client(
        project=args.project,
        location=args.location,
        credentials=credentials,
    )
    local_app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)
    remote_agent = client.agent_engines.create(
        agent=local_app,
        config={
            "display_name": "TraceOS Forensics Fleet",
            "description": "Evidence-scoped multi-agent digital forensics workflow",
            "requirements": [
                "google-cloud-aiplatform[agent_engines,adk]>=1.112",
                "google-adk>=2.7,<3",
                "pydantic>=2.12.5,<3",
                "cloudpickle>=3,<4",
            ],
            "extra_packages": ["agents"],
            "staging_bucket": args.staging_bucket,
            "identity_type": types.IdentityType.AGENT_IDENTITY,
            "min_instances": 0,
            "max_instances": 1,
            "resource_limits": {"cpu": "2", "memory": "2Gi"},
            "container_concurrency": 5,
            "env_vars": {
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GEMINI_MODEL": "gemini-3.5-flash",
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            },
        },
    )
    print(json.dumps({"resource_name": remote_agent.api_resource.name}, indent=2))


if __name__ == "__main__":
    main()

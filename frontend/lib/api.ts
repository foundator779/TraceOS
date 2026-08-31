const inferredLocalBase = typeof window !== "undefined" && window.location.port === "3000"
  ? "http://localhost:8000"
  : "";
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? inferredLocalBase;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? "Request failed");
  }
  return response.json();
}

export type SourceKind = "GOOGLE_CLOUD_LIVE" | "DEMO_SYNTHETIC";

export interface CaseSummary {
  case_id: string;
  external_ref: string;
  title: string;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  last_evidence_at?: string;
  runtime_generation: number;
  risk_score: number;
  active_agents: string[];
  evidence_count: number;
  finding_count: number;
  review_status: string;
  source?: string;
}

export interface Evidence {
  evidence_id: string;
  evidence_type: string;
  source_system: string;
  source_kind: SourceKind;
  source_product: string;
  collected_at: string;
  ingested_at: string;
  sha256: string;
  status: string;
  classification: string;
  live_source_verified: boolean;
  source_project?: string;
  source_resource?: string;
  external_event_id?: string;
  preview?: string;
  access_count: number;
  storage_uri?: string;
  metadata?: Record<string, unknown>;
}

export interface ReplayEvent {
  replay_id: string;
  stage: "SOURCE" | "OBSERVATION" | "HYPOTHESIS" | "FINDING";
  title: string;
  detail: string;
  event_time: string;
  evidence_ids: string[];
  confidence?: number;
  status: string;
  source_kind?: SourceKind;
  image_url?: string;
  sha256?: string;
  ocr_excerpt?: string;
  model?: string;
  visual_regions?: Array<{ label: string; x: number; y: number; width: number; height: number; confidence: number }>;
}

export interface RuntimeEvent {
  sequence: number;
  event_type: string;
  title: string;
  detail: string;
  status: string;
  agent_id?: string;
  timestamp: string;
}

export interface Finding {
  finding_id: string;
  title: string;
  severity: string;
  status: string;
  statement: string;
  evidence_ids: string[];
  observation_ids: string[];
  verified_by: string;
}

export interface CrossModelVerdict {
  verdict_id: string;
  model_family: string;
  model: string;
  status: string;
  evidence_ids: string[];
  disagreements: string[];
  rationale: string;
  input_hash: string;
  operation_id?: string;
  estimated_cost_usd: number;
  created_at: string;
}

export interface TrainingArtifact {
  artifact_id: string;
  kind: string;
  model_family: string;
  model: string;
  status: string;
  storage_uri?: string;
  sha256?: string;
  operation_id?: string;
  mime_type?: string;
  duration_seconds?: number;
  estimated_cost_usd: number;
  label: string;
  error_code?: string;
  retry_count: number;
  completed_at?: string;
}

export interface TrainingPack {
  pack_id: string;
  case_id: string;
  status: string;
  report_hash: string;
  source_report_id: string;
  evidence_ids: string[];
  gemma_verdict?: CrossModelVerdict;
  artifacts: TrainingArtifact[];
  estimated_cost_usd: number;
  generation_mode: string;
  provenance_boundary: string;
  created_at: string;
  updated_at: string;
}

export interface CaseState {
  case: CaseSummary;
  evidence: Evidence[];
  chain_of_custody: Array<Record<string, string>>;
  observations: Array<Record<string, unknown>>;
  hypotheses: Array<Record<string, unknown>>;
  verification_results: Array<Record<string, unknown>>;
  findings: Finding[];
  timeline: Array<Record<string, unknown>>;
  memory: {
    version: number;
    provider: string;
    verified_facts: Array<Record<string, unknown>>;
    open_questions: Array<Record<string, unknown>>;
    last_checkpoint: string;
    evidence_references: string[];
  };
  audit: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
  runtime_events: RuntimeEvent[];
  gateway_decisions: Array<Record<string, any>>;
  model_armor_decisions: Array<Record<string, any>>;
  integrity_events: Array<Record<string, any>>;
  report?: Record<string, any>;
  training_pack?: TrainingPack;
}

export interface AgentManifest {
  agent_id: string;
  display_name: string;
  version: string;
  status: string;
  owner: string;
  identity: string;
  allowed_tools: string[];
  data_scopes: string[];
  deployment_state: string;
  active_cases: number;
}

export interface Integration {
  id: string;
  name: string;
  status: string;
  mode: string;
  source_kind: SourceKind;
  last_verified_at?: string;
  detail: string;
}

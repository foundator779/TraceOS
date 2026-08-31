terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 6.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 6.0" }
  }
}

variable "project_id" {
  type = string
}
variable "region" {
  type    = string
  default = "us-central1"
}
variable "image" {
  type = string
}

provider "google" {
  project = var.project_id
  region  = var.region
}
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  run_url = "https://traceos-${data.google_project.current.number}.${var.region}.run.app"
  services = toset([
    "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
    "firestore.googleapis.com", "logging.googleapis.com", "aiplatform.googleapis.com",
    "modelarmor.googleapis.com", "pubsub.googleapis.com", "storage.googleapis.com"
  ])
}

resource "google_project_service" "apis" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "traceos-runtime"
  display_name = "TraceOS runtime"
}

resource "google_artifact_registry_repository" "app" {
  project       = var.project_id
  location      = var.region
  repository_id = "traceos"
  description   = "TraceOS application images"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset([
    "roles/datastore.user", "roles/logging.viewer", "roles/logging.logWriter",
    "roles/aiplatform.user", "roles/modelarmor.user"
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "evidence" {
  project                     = var.project_id
  name                        = "${var.project_id}-traceos-evidence"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = 60 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "runtime_evidence" {
  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "training" {
  project                     = var.project_id
  name                        = "${var.project_id}-traceos-training"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = 60 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "runtime_training" {
  bucket = google_storage_bucket.training.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_pubsub_topic" "audit_evidence" {
  name                       = "traceos-audit-evidence"
  project                    = var.project_id
  message_retention_duration = "86400s"
  depends_on                 = [google_project_service.apis]
}

resource "google_pubsub_topic" "training_pack" {
  name                       = "traceos-training-pack"
  project                    = var.project_id
  message_retention_duration = "86400s"
  depends_on                 = [google_project_service.apis]
}

resource "google_pubsub_topic_iam_member" "runtime_training_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.training_pack.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_logging_project_sink" "audit_evidence" {
  name                   = "traceos-audit-evidence"
  project                = var.project_id
  destination            = "pubsub.googleapis.com/projects/${var.project_id}/topics/${google_pubsub_topic.audit_evidence.name}"
  filter                 = "logName:\"cloudaudit.googleapis.com%2Factivity\""
  unique_writer_identity = true
}

resource "google_pubsub_topic_iam_member" "sink_writer" {
  project = var.project_id
  topic   = google_pubsub_topic.audit_evidence.name
  role    = "roles/pubsub.publisher"
  member  = google_logging_project_sink.audit_evidence.writer_identity
}

resource "google_service_account" "pubsub_push" {
  project      = var.project_id
  account_id   = "traceos-pubsub-push"
  display_name = "TraceOS authenticated Pub/Sub push"
}

resource "google_project_service_identity" "pubsub_agent" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

resource "google_project_iam_member" "pubsub_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:${google_project_service_identity.pubsub_agent.email}"
}

resource "google_cloud_run_v2_service" "app" {
  name                = "traceos"
  location            = var.region
  project             = var.project_id
  deletion_protection = false
  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.image
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      env {
        name  = "ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "EVIDENCE_BUCKET"
        value = google_storage_bucket.evidence.name
      }
      env {
        name  = "TRAINING_OUTPUT_BUCKET"
        value = google_storage_bucket.training.name
      }
      env {
        name  = "TRAINING_PUBSUB_TOPIC"
        value = google_pubsub_topic.training_pack.id
      }
      env {
        name  = "TRAINING_PUBSUB_AUDIENCE"
        value = "${local.run_url}/api/v1/internal/training-pack/jobs"
      }
      env {
        name  = "TRAINING_WORKER_SERVICE_ACCOUNT"
        value = google_service_account.pubsub_push.email
      }
      env {
        name  = "TRAINING_BUDGET_USD"
        value = "1.00"
      }
      env {
        name  = "TRAINING_MAX_LIVE_RUNS"
        value = "1"
      }
      env {
        name  = "TRAINING_MAX_ARTIFACT_RETRIES"
        value = "2"
      }
      env {
        name  = "ENABLE_GEMMA_VERIFIER"
        value = "false"
      }
      env {
        name  = "ENABLE_VEO_TRAINING"
        value = "false"
      }
      env {
        name  = "ENABLE_LYRIA_TRAINING"
        value = "false"
      }
      env {
        name  = "PUBSUB_PUSH_AUDIENCE"
        value = "${local.run_url}/api/v1/ingest/cloud-audit"
      }
      env {
        name  = "PUBSUB_PUSH_SERVICE_ACCOUNT"
        value = google_service_account.pubsub_push.email
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "TRACEOS_STORE"
        value = "firestore"
      }
      env {
        name  = "ENABLE_CLOUD_CONNECTORS"
        value = "true"
      }
      env {
        name  = "GEMINI_MODEL"
        value = "gemini-3.7-flash"
      }
      env {
        name  = "GEMINI_VISION_MODEL"
        value = "gemini-2.5-flash"
      }
      env {
        name  = "GEMINI_LOCATION"
        value = "global"
      }
      env {
        name  = "GEMINI_USE_VERTEX"
        value = "true"
      }
    }
  }
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.runtime_roles,
    google_artifact_registry_repository.app
  ]
}

resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_push.email}"
}

resource "google_pubsub_subscription" "audit_push" {
  project              = var.project_id
  name                 = "traceos-audit-evidence-push"
  topic                = google_pubsub_topic.audit_evidence.name
  ack_deadline_seconds = 30
  expiration_policy { ttl = "" }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  push_config {
    push_endpoint = "${local.run_url}/api/v1/ingest/cloud-audit"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
      audience              = "${local.run_url}/api/v1/ingest/cloud-audit"
    }
    attributes = { x-goog-version = "v1" }
  }
  depends_on = [
    google_cloud_run_v2_service_iam_member.pubsub_invoker,
    google_project_iam_member.pubsub_token_creator,
  ]
}

resource "google_pubsub_subscription" "training_push" {
  project              = var.project_id
  name                 = "traceos-training-pack-push"
  topic                = google_pubsub_topic.training_pack.name
  ack_deadline_seconds = 30
  expiration_policy { ttl = "" }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  push_config {
    push_endpoint = "${local.run_url}/api/v1/internal/training-pack/jobs"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
      audience              = "${local.run_url}/api/v1/internal/training-pack/jobs"
    }
    attributes = { x-goog-version = "v1" }
  }
  depends_on = [
    google_cloud_run_v2_service_iam_member.pubsub_invoker,
    google_project_iam_member.pubsub_token_creator,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" {
  value = google_cloud_run_v2_service.app.uri
}

output "evidence_bucket" {
  value = google_storage_bucket.evidence.name
}

output "training_bucket" {
  value = google_storage_bucket.training.name
}

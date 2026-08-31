from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable

from .models import CaseState


class CaseStore:
    """Small durable state store used locally and as the UI mirror in Cloud Run.

    The entire aggregate is committed transactionally. Evidence and audit histories are
    append-only in the runtime; updates only replace the serialized aggregate snapshot.
    """

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cases ("
                "case_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS idempotency ("
                "key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )

    def save(self, state: CaseState) -> None:
        payload = state.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO cases(case_id,state_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(case_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                (state.case.case_id, payload, state.case.updated_at),
            )

    def get(self, case_id: str) -> CaseState | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT state_json FROM cases WHERE case_id=?", (case_id,)).fetchone()
        return CaseState.model_validate_json(row["state_json"]) if row else None

    def list(self) -> list[CaseState]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT state_json FROM cases ORDER BY updated_at DESC").fetchall()
        return [CaseState.model_validate_json(row["state_json"]) for row in rows]

    def mutate(self, case_id: str, fn: Callable[[CaseState], None]) -> CaseState:
        with self._lock:
            state = self.get(case_id)
            if state is None:
                raise KeyError(case_id)
            fn(state)
            self.save(state)
            return state

    def delete(self, case_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cases WHERE case_id=?", (case_id,))

    def get_idempotent(self, key: str) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT response_json FROM idempotency WHERE key=?", (key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def set_idempotent(self, key: str, response: dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency(key,response_json) VALUES(?,?)",
                (key, json.dumps(response)),
            )

    def increment_counter(self, key: str) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO counters(key,value) VALUES(?,1) "
                "ON CONFLICT(key) DO UPDATE SET value=value+1",
                (key,),
            )
            row = conn.execute("SELECT value FROM counters WHERE key=?", (key,)).fetchone()
        return int(row["value"])


class FirestoreCaseStore:
    """Persistent Cloud Run store using Firestore as the application state mirror."""

    def __init__(self, project: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project)
        self.cases = self.client.collection("cases")
        self.idempotency = self.client.collection("idempotency")
        self.counters = self.client.collection("counters")
        self._lock = threading.RLock()

    def save(self, state: CaseState) -> None:
        self.cases.document(state.case.case_id).set(
            {"state_json": state.model_dump_json(), "updated_at": state.case.updated_at}
        )

    def get(self, case_id: str) -> CaseState | None:
        snapshot = self.cases.document(case_id).get()
        if not snapshot.exists:
            return None
        return CaseState.model_validate_json(snapshot.to_dict()["state_json"])

    def list(self) -> list[CaseState]:
        snapshots = self.cases.order_by("updated_at", direction="DESCENDING").stream()
        return [CaseState.model_validate_json(snapshot.to_dict()["state_json"]) for snapshot in snapshots]

    def mutate(self, case_id: str, fn: Callable[[CaseState], None]) -> CaseState:
        # A process lock prevents concurrent SSE/API writers in the bounded one-instance
        # demo deployment. Production can replace this with a Firestore transaction.
        with self._lock:
            state = self.get(case_id)
            if state is None:
                raise KeyError(case_id)
            fn(state)
            self.save(state)
            return state

    def delete(self, case_id: str) -> None:
        self.cases.document(case_id).delete()

    @staticmethod
    def _idempotency_doc(key: str) -> str:
        import hashlib

        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get_idempotent(self, key: str) -> dict | None:
        snapshot = self.idempotency.document(self._idempotency_doc(key)).get()
        return snapshot.to_dict().get("response") if snapshot.exists else None

    def set_idempotent(self, key: str, response: dict) -> None:
        try:
            self.idempotency.document(self._idempotency_doc(key)).create({"response": response, "key_hash_only": True})
        except Exception:
            pass

    def increment_counter(self, key: str) -> int:
        from google.cloud import firestore

        ref = self.counters.document(self._idempotency_doc(key))
        transaction = self.client.transaction()

        @firestore.transactional
        def update(txn):
            snapshot = ref.get(transaction=txn)
            value = int(snapshot.to_dict().get("value", 0)) + 1 if snapshot.exists else 1
            txn.set(ref, {"value": value, "key_hash_only": True})
            return value

        return update(transaction)

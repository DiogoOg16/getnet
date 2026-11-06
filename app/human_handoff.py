from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def is_attendant_user(user_id: str | None) -> bool:
    if not user_id:
        return False
    normalized = user_id.strip().lower()
    return normalized.startswith("atendente_") or normalized in {"atendente", "support", "suporte", "operator"}


class HumanHandoffStore:
    """Persist and manage human handoff requests for a user/session."""

    def __init__(self, storage_path: str | None = None) -> None:
        self.storage_path = Path(
            storage_path or os.getenv(
                "GETNET_HUMAN_HANDOFF_PATH",
                str(Path(tempfile.gettempdir()) / "getnet_human_handoff.json"),
            )
        )
        self._records = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.storage_path.exists():
            return {}

        try:
            raw = self.storage_path.read_text(encoding="utf-8")
            if not raw.strip():
                return {}
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}

        records: dict[str, dict] = {}
        for ticket_id, payload in data.items():
            if not isinstance(payload, dict):
                continue
            records[str(ticket_id)] = payload
        return records

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.storage_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.storage_path)

    def create(
        self,
        *,
        user_id: str,
        session_id: str,
        message: str,
    ) -> dict:
        if not user_id or not session_id:
            raise ValueError("user_id e session_id são obrigatórios.")

        ticket_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        record = {
            "id": ticket_id,
            "user_id": user_id,
            "session_id": session_id,
            "message": message.strip(),
            "status": "pending",
            "assignee": None,
            "resolution": None,
            "created_at": now,
            "updated_at": now,
        }
        self._records[ticket_id] = record
        self._save()
        return record.copy()

    def serialize_for_user(self, record: dict, actor_user_id: str) -> dict:
        if is_attendant_user(actor_user_id) or record.get("user_id") == actor_user_id:
            return record.copy()

        redacted = record.copy()
        redacted["message"] = "[mensagem ocultada por política de privacidade]"
        redacted["resolution"] = "[resolução ocultada por política de privacidade]" if redacted.get("resolution") else None
        return redacted

    def list(self) -> list[dict]:
        return [record.copy() for record in sorted(
            self._records.values(),
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )]

    def list_for_user(self, user_id: str) -> list[dict]:
        records = self.list()
        if is_attendant_user(user_id):
            return records
        return [record for record in records if record.get("user_id") == user_id]

    def get(self, ticket_id: str) -> dict | None:
        record = self._records.get(ticket_id)
        return record.copy() if record else None

    def find_active_for_session(self, *, user_id: str, session_id: str) -> dict | None:
        for record in sorted(
            self._records.values(),
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        ):
            if (
                record.get("user_id") == user_id
                and record.get("session_id") == session_id
                and record.get("status") in {"pending", "assigned"}
            ):
                return record.copy()
        return None

    def assume(self, ticket_id: str, assignee: str) -> dict:
        record = self._records.get(ticket_id)
        if record is None:
            raise KeyError(f"Ticket {ticket_id} não encontrado.")
        if not assignee or not assignee.strip():
            raise ValueError("assignee não pode ser vazio.")
        if record.get("status") == "completed":
            raise ValueError("Ticket já concluído e não pode ser assumido novamente.")
        if record.get("status") == "assigned":
            raise ValueError("Ticket já foi assumido por outro atendente.")
        if record.get("status") != "pending":
            raise ValueError("Transição inválida: ticket não está pendente.")

        record["status"] = "assigned"
        record["assignee"] = assignee.strip()
        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        self._save()
        return record.copy()

    def complete(self, ticket_id: str, resolution: str) -> dict:
        record = self._records.get(ticket_id)
        if record is None:
            raise KeyError(f"Ticket {ticket_id} não encontrado.")
        if not resolution or not resolution.strip():
            raise ValueError("resolution não pode ser vazia.")
        if record.get("status") == "completed":
            raise ValueError("Ticket já concluído.")
        if record.get("status") != "assigned":
            raise ValueError("Ticket só pode ser concluído após ser assumido por um atendente.")

        record["status"] = "completed"
        record["resolution"] = resolution.strip()
        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        self._save()
        return record.copy()

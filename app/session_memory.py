import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


class SessionMemory:
    """Stores short-lived per-session conversation fragments."""

    def __init__(
        self,
        storage_path: str | None = None,
        max_entries: int = 20,
        max_age_minutes: int = 60 * 24 * 7,
    ) -> None:
        self.storage_path = Path(
            storage_path or os.getenv(
                "GETNET_SESSION_MEMORY_PATH",
                str(Path(tempfile.gettempdir()) / "getnet_session_memory.json"),
            )
        )
        self.max_entries = max_entries
        self.max_age_minutes = max_age_minutes
        self._store = self._load()

    def _session_key(self, user_id: str, session_id: str | None = None) -> str:
        return f"{user_id}:{session_id or user_id}"

    def _load(self) -> dict[str, list[dict[str, str]]]:
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

        cleaned: dict[str, list[dict[str, str]]] = {}
        for key, entries in data.items():
            if not isinstance(entries, list):
                continue
            cleaned[key] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                message = str(entry.get("message", "")).strip()
                response = str(entry.get("response", "")).strip()
                timestamp = entry.get("timestamp")
                if not message and not response:
                    continue
                cleaned_entry = {
                    "message": message,
                    "response": response,
                    "timestamp": timestamp,
                }
                if isinstance(entry.get("pending_followup"), dict):
                    cleaned_entry["pending_followup"] = entry["pending_followup"]
                cleaned[key].append(cleaned_entry)
        return cleaned

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.storage_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(self._store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.storage_path)

    def _prune_expired(self, user_id: str, session_id: str | None = None) -> None:
        key = self._session_key(user_id, session_id)
        entries = self._store.get(key, [])
        if not entries:
            return

        cutoff = datetime.now() - timedelta(minutes=self.max_age_minutes)
        filtered = []
        for entry in entries:
            timestamp = entry.get("timestamp")
            if timestamp is None:
                filtered.append(entry)
                continue
            try:
                entry_time = datetime.fromisoformat(timestamp)
            except ValueError:
                filtered.append(entry)
                continue
            if entry_time >= cutoff:
                filtered.append(entry)

        self._store[key] = filtered[-self.max_entries :]

    def add_message(
        self,
        *,
        user_id: str,
        message: str,
        response: str,
        session_id: str | None = None,
        pending_followup: dict | None = None,
    ) -> None:
        key = self._session_key(user_id, session_id)
        entry = {
            "message": message.strip(),
            "response": response.strip(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        if pending_followup:
            entry["pending_followup"] = pending_followup

        if key not in self._store:
            self._store[key] = []

        self._store[key].append(entry)
        self._store[key] = self._store[key][-self.max_entries :]
        self._prune_expired(user_id, session_id)
        self._save()

    def get_recent_context(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        key = self._session_key(user_id, session_id)
        self._prune_expired(user_id, session_id)
        entries = self._store.get(key, [])

        context: list[str] = []
        for entry in entries[-limit:]:
            message = entry.get("message", "").strip()
            response = entry.get("response", "").strip()
            if message:
                context.append(f"Usuário: {message}")
            if response:
                context.append(f"Assistente: {response}")
        return context

    def get_pending_followup(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
    ) -> dict | None:
        """Retorna o fluxo pendente do último turno; vale por um único turno."""
        key = self._session_key(user_id, session_id)
        self._prune_expired(user_id, session_id)
        entries = self._store.get(key, [])
        if not entries:
            return None
        return entries[-1].get("pending_followup")

    @staticmethod
    def _normalize_reference_text(value: str) -> str:
        return " ".join(
            filter(None, re.sub(r"[^a-z0-9\s]", " ", value.casefold()).split())
        )

    def resolve_contextual_reference(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        message: str,
        limit: int = 5,
    ) -> str | None:
        normalized = self._normalize_reference_text(message)
        if not normalized:
            return None

        short_reference = normalized in {
            "essa",
            "isso",
            "este",
            "esta",
            "aquele",
            "aquela",
            "aquilo",
            "e essa",
            "e isso",
            "e este",
            "e esta",
            "e aquele",
            "e aquela",
        }
        if not short_reference:
            return None

        from app.agents.router import RouterAgent

        key = self._session_key(user_id, session_id)
        entries = self._store.get(key, [])

        for entry in reversed(entries[-limit:]):
            candidate = str(entry.get("message", "")).strip()
            if not candidate:
                continue
            if self._normalize_reference_text(candidate) == normalized:
                continue
            if RouterAgent().route(candidate).agent == "fallback":
                continue
            return candidate

        return None

    def clear_session(self, *, user_id: str, session_id: str | None = None) -> None:
        key = self._session_key(user_id, session_id)
        self._store.pop(key, None)
        self._save()

    @staticmethod
    def extract_name_from_context(context: list[str]) -> str | None:
        for item in context:
            lowered = item.lower()
            for pattern in (
                "meu nome é ",
                "me chamo ",
                "eu me chamo ",
                "meu nome é",
                "me chamo",
                "eu me chamo",
            ):
                idx = lowered.find(pattern)
                if idx != -1:
                    candidate = item[idx + len(pattern):].strip()
                    if candidate:
                        return candidate.split()[0].strip(".,!?")
        return None

    def answer_from_context(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        message: str,
    ) -> str | None:
        text = message.lower()
        if not (
            "nome" in text and (
                "qual" in text or "o nome" in text or "falei" in text or "disse" in text)
        ):
            return None

        context = self.get_recent_context(
            user_id=user_id,
            session_id=session_id,
            limit=10,
        )
        name = self.extract_name_from_context(context)
        if not name:
            return None
        return f"Você mencionou que seu nome é {name}."

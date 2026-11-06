"""Helpers to load local environment configuration for script execution."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_local_env() -> None:
    """Load .env from repository root when present.

    Does not override variables already exported in the shell.
    """
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

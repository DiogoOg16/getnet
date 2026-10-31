from __future__ import annotations

import math
import re
from typing import Any


AUTHORIZED_FACT_PRODUCERS = {
    "customer_support": {
        "lookup_transaction",
        "lookup_customer",
        "lookup_settlement",
    },
}

PUBLIC_FACT_NAMES = {
    "status",
    "amount",
    "currency",
}

VALID_CURRENCY_CODES = {"BRL", "USD", "EUR", "GBP", "ARS", "MXN", "COP"}


def _normalize_fact_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[str(key)] = _normalize_fact_value(item)
        return normalized
    if isinstance(value, list):
        normalized_values: list[Any] = []
        for item in value:
            normalized_values.append(_normalize_fact_value(item))
        return normalized_values
    return str(value)


def _type_safe_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return False
        return all(_type_safe_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(_type_safe_equal(item_a, item_b) for item_a, item_b in zip(left, right))
    return left == right


def _is_authorized_fact_origin(fact: dict[str, Any]) -> bool:
    if not isinstance(fact, dict):
        return False

    source_agent = fact.get("source_agent")
    source_tool = fact.get("source_tool")

    if not isinstance(source_agent, str) or not isinstance(source_tool, str):
        return False

    source_agent = source_agent.strip()
    source_tool = source_tool.strip()

    if source_agent == "knowledge":
        return False

    if source_agent not in AUTHORIZED_FACT_PRODUCERS:
        return False

    if not source_tool:
        return False

    allowed_tools = AUTHORIZED_FACT_PRODUCERS.get(source_agent, set())
    if source_tool not in allowed_tools:
        return False

    return True


def _validate_fact_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    normalized = name.strip()
    if not normalized:
        return None
    if normalized not in PUBLIC_FACT_NAMES:
        return None
    return normalized


def _validate_fact_value(field_name: str, value: Any) -> Any | None:
    if field_name == "amount":
        if isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return value

    if field_name == "status":
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 64:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_\-\s]+", normalized):
            return None
        return normalized

    if field_name == "currency":
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 64:
            return None
        if normalized not in VALID_CURRENCY_CODES:
            return None
        return normalized

    return None


def _public_value(item: Any, *, field_name: str | None = None) -> Any:
    if field_name is None:
        return None
    return _validate_fact_value(field_name, item)


def is_valid_verified_fact(fact: Any) -> bool:
    if not isinstance(fact, dict):
        return False
    if fact.get("verified") is not True:
        return False
    if not _is_authorized_fact_origin(fact):
        return False

    entity = fact.get("entity")
    if not isinstance(entity, str):
        return False
    entity = entity.strip()
    if not entity:
        return False

    name = _validate_fact_name(fact.get("name"))
    if name is None:
        return False

    value = _validate_fact_value(name, fact.get("value"))
    if value is None:
        return False

    return True


def make_verified_fact(
    *,
    entity: str,
    name: str,
    value: Any,
    source_agent: str,
    source_tool: str,
) -> dict[str, Any]:
    if not isinstance(source_agent, str):
        raise ValueError("source_agent must be a string")
    if not isinstance(source_tool, str):
        raise ValueError("source_tool must be a string")

    if source_agent != "customer_support":
        raise ValueError("source_agent not authorized to produce verified facts")
    if source_tool not in AUTHORIZED_FACT_PRODUCERS.get(source_agent, set()):
        raise ValueError("source_tool not authorized to produce verified facts")

    if not isinstance(entity, str):
        raise ValueError("entity must be a string")

    normalized_entity = entity.strip()
    if not normalized_entity:
        raise ValueError("entity cannot be empty")

    normalized_name = _validate_fact_name(name)
    if normalized_name is None:
        raise ValueError("name must be one of: status, amount, currency")

    normalized_value = _validate_fact_value(normalized_name, value)
    if normalized_value is None:
        raise ValueError(f"invalid value for fact {normalized_name}")

    return {
        "entity": normalized_entity,
        "name": normalized_name,
        "value": normalized_value,
        "source_agent": str(source_agent).strip(),
        "source_tool": str(source_tool).strip(),
        "verified": True,
    }


def public_verified_facts(facts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for fact in facts or []:
        if not is_valid_verified_fact(fact):
            continue

        name = _validate_fact_name(fact.get("name"))
        if name is None:
            continue

        value = _public_value(fact.get("value"), field_name=name)
        if value is None:
            continue

        public.append(
            {
                "entity": str(fact.get("entity", "")).strip(),
                "name": name,
                "value": value,
                "verified": True,
            }
        )
    return [item for item in public if item.get("entity") and item.get("name")]


def public_fact_conflicts(conflicts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for conflict in conflicts or []:
        if not isinstance(conflict, dict):
            continue

        name = _validate_fact_name(conflict.get("name"))
        if name is None:
            continue

        values = conflict.get("values", [])
        sanitized_values = []
        seen: list[Any] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            if not _is_authorized_fact_origin(item):
                continue
            public_value = _public_value(item.get("value"), field_name=name)
            if public_value is None:
                continue
            if not any(_type_safe_equal(existing, public_value) for existing in seen):
                sanitized_values.append(public_value)
                seen.append(public_value)
        if not sanitized_values:
            continue
        public.append(
            {
                "entity": str(conflict.get("entity", "")).strip(),
                "name": name,
                "values": sanitized_values,
            }
        )
    return [item for item in public if item.get("entity") and item.get("name")]


def consolidate_verified_facts(
    facts: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in facts or []:
        if not is_valid_verified_fact(fact):
            continue

        entity = fact.get("entity")
        if not isinstance(entity, str):
            continue
        entity = entity.strip()
        if not entity:
            continue

        name = _validate_fact_name(fact.get("name"))
        if name is None:
            continue

        validated_value = _validate_fact_value(name, fact.get("value"))
        if validated_value is None:
            continue

        grouped.setdefault((entity, name), []).append({
            "entity": entity,
            "name": name,
            "value": validated_value,
            "source_agent": str(fact.get("source_agent", "")).strip(),
            "source_tool": str(fact.get("source_tool", "")).strip(),
            "verified": True,
        })

    unique: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for (entity, name), entries in grouped.items():
        consolidated: list[dict[str, Any]] = []
        for entry in entries:
            matched = None
            for existing in consolidated:
                if _type_safe_equal(existing["value"], entry["value"]):
                    matched = existing
                    break
            if matched is None:
                consolidated.append({
                    "value": entry["value"],
                    "provenance": [{
                        "source_agent": entry["source_agent"],
                        "source_tool": entry["source_tool"],
                    }],
                    "verified": True,
                })
                continue

            provenance_entry = {
                "source_agent": entry["source_agent"],
                "source_tool": entry["source_tool"],
            }
            if provenance_entry not in matched["provenance"]:
                matched["provenance"].append(provenance_entry)

        if len(consolidated) == 1:
            value_group = consolidated[0]
            primary = value_group["provenance"][0]
            unique.append({
                "entity": entity,
                "name": name,
                "value": value_group["value"],
                "source_agent": primary["source_agent"],
                "source_tool": primary["source_tool"],
                "source_provenance": value_group["provenance"],
                "verified": True,
            })
            continue

        if len(consolidated) > 1:
            conflicts.append({
                "entity": entity,
                "name": name,
                "values": [
                    {
                        "value": fact["value"],
                        "source_agent": item["source_agent"],
                        "source_tool": item["source_tool"],
                    }
                    for fact in consolidated
                    for item in fact["provenance"]
                ],
            })

    return unique, conflicts

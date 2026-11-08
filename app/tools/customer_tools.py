"""Tools for retrieving simulated customer and transaction data."""

from datetime import date, timedelta

from app.tools.registry import Tool, ToolRegistry, tool_registry

CUSTOMERS = {
    "cliente1988": {
        "customer_id": "cliente1988",
        "name": "Cliente de Teste",
        "account_status": "active",
        "support_tier": "standard",
    },
    "cliente2001": {
        "customer_id": "cliente2001",
        "name": "Cliente Demonstração",
        "account_status": "pending_review",
        "support_tier": "standard",
    },
}

TRANSACTIONS = {
    "txn1001": {
        "transaction_id": "txn1001",
        "customer_id": "cliente1988",
        "amount": 149.90,
        "currency": "BRL",
        "status": "approved",
    },
    "txn1002": {
        "transaction_id": "txn1002",
        "customer_id": "cliente1988",
        "amount": 89.50,
        "currency": "BRL",
        "status": "pending",
    },
    "txn1003": {
        "transaction_id": "txn1003",
        "customer_id": "cliente1988",
        "amount": 75.00,
        "currency": "BRL",
        "status": "declined",
    },
    "txn2001": {
        "transaction_id": "txn2001",
        "customer_id": "cliente2001",
        "amount": 250.00,
        "currency": "BRL",
        "status": "declined",
        "decline_code": "AUTH_DECLINED",
        "decline_reason": "Cartão bloqueado pelo emissor",
        "declined_at": "2026-10-20T12:40:00Z",
    },
}

# Datas relativas à data de referência (em dias), para que os registros
# sintéticos não fiquem desatualizados. Status e datas são coerentes:
# "scheduled" e "processing" têm liquidação prevista a partir da data de
# referência; "settled" teria liquidação até a data de referência.
SETTLEMENTS = {
    "cliente1988": [{
        "settlement_id": "settlement_001",
        "customer_id": "cliente1988",
        "transaction_id": "txn1001",
        "status": "scheduled",
        "amount": 149.90,
        "currency": "BRL",
        "sale_offset_days": -1,
        "settlement_offset_days": 1,
        "source": "synthetic_fixture",
        "simulated": True,
    }, {
        "settlement_id": "settlement_002",
        "customer_id": "cliente1988",
        "transaction_id": "txn1002",
        "status": "processing",
        "amount": 89.50,
        "currency": "BRL",
        "sale_offset_days": -3,
        "settlement_offset_days": 0,
        "source": "synthetic_fixture",
        "simulated": True,
    }],
    "cliente2001": [],
}


def settlement_reference_date() -> date:
    """Data de referência das liquidações simuladas.

    É o único ponto que lê o relógio do sistema; os testes a substituem.
    """
    return date.today()


def _materialize_settlement(record: dict, reference_date: date) -> dict:
    """Converte deslocamentos em dias para datas ISO, sem alterar o status."""
    materialized = record.copy()
    sale_offset = materialized.pop("sale_offset_days", None)
    settlement_offset = materialized.pop("settlement_offset_days", None)
    if sale_offset is not None:
        materialized["sale_date"] = (reference_date + timedelta(days=sale_offset)).isoformat()
    if settlement_offset is not None:
        materialized["estimated_settlement_date"] = (
            reference_date + timedelta(days=settlement_offset)
        ).isoformat()
    return materialized


def filter_settlement_records(records: list[dict], sale_date: str) -> list[dict]:
    """Mantém só os registros cuja data da venda é `sale_date` (ISO)."""
    return [record for record in records if record.get("sale_date") == sale_date]


def lookup_customer(user_id: str) -> dict:
    """Retrieve a customer by their user ID."""
    customer = CUSTOMERS.get(user_id)

    if customer is None:
        return {
            "found": False,
            "message": "Customer not found in the simulated database.",
        }

    return {"found": True, "customer": customer.copy()}


def lookup_transaction(
    transaction_id: str,
    user_id: str,
) -> dict:
    """Retrieve a transaction only if it belongs to the requesting customer."""
    transaction = TRANSACTIONS.get(transaction_id)

    if transaction is None or transaction["customer_id"] != user_id:
        return {
            "found": False,
            "message": "Transaction not found for this customer.",
        }

    return {"found": True, "transaction": transaction.copy()}

def lookup_settlement(
    user_id: str,
    sale_date: str | None = None,
    reference_date: date | None = None,
) -> dict:
    """Return synthetic settlement records for a known customer.

    The records are intentionally simulated and do not represent a real
    Getnet settlement integration. `sale_date` (ISO) filters by sale date.
    """
    customer = CUSTOMERS.get(user_id)

    if customer is None:
        return {
            "found": False,
            "simulated": True,
            "customer_id": user_id,
            "message": "Cliente não encontrado na base de dados simulada.",
        }

    reference = reference_date or settlement_reference_date()
    records = [
        _materialize_settlement(record, reference)
        for record in SETTLEMENTS.get(user_id, [])
    ]
    if sale_date is not None:
        records = filter_settlement_records(records, sale_date)

    if records:
        return {
            "found": True,
            "simulated": True,
            "customer_id": user_id,
            "reference_date": reference.isoformat(),
            "records": records,
            "message": "Há registros de liquidação disponíveis para este cliente.",
        }

    return {
        "found": True,
        "simulated": True,
        "customer_id": user_id,
        "reference_date": reference.isoformat(),
        "records": [],
        "message": (
            "Não há registros de liquidação para este cliente neste "
            "ambiente simulado."
        ),
    }


def register_customer_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register the customer support tools in the provided registry.

    This method is explicit and idempotent: repeated calls keep a single copy of
    each tool in the target registry.
    """
    target_registry = registry if registry is not None else tool_registry
    if not isinstance(target_registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry instance.")

    tool_definitions = (
        Tool(
            name="lookup_customer",
            description=(
                "Recupera o cadastro do cliente usando o user_id autenticado do backend. "
                "Não requer argumentos do usuário."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            trusted_context=("user_id",),
            handler=lookup_customer,
        ),
        Tool(
            name="lookup_transaction",
            description="Recupera uma transação apenas quando pertence ao cliente autenticado.",
            parameters={
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "Identificador da transação.",
                    }
                },
                "required": ["transaction_id"],
            },
            trusted_context=("user_id",),
            handler=lookup_transaction,
        ),
        Tool(
            name="lookup_settlement",
            description="Recupera registros simulados de liquidação para o cliente autenticado.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            trusted_context=("user_id",),
            handler=lookup_settlement,
        ),
    )

    for tool in tool_definitions:
        if target_registry.get(tool.name) is None:
            target_registry.register(tool)

    return target_registry

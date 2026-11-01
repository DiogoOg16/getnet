"""Tools for retrieving simulated customer and transaction data."""

from app.tools.registry import Tool, tool_registry

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

SETTLEMENTS = {
    "cliente1988": [{
        "settlement_id": "settlement_001",
        "customer_id": "cliente1988",
        "transaction_id": "txn1001",
        "status": "scheduled",
        "amount": 149.90,
        "currency": "BRL",
        "estimated_settlement_date": "2026-11-05",
        "source": "synthetic_fixture",
        "simulated": True,
    }, {
        "settlement_id": "settlement_002",
        "customer_id": "cliente1988",
        "transaction_id": "txn1002",
        "status": "processing",
        "amount": 89.50,
        "currency": "BRL",
        "estimated_settlement_date": "2026-11-12",
        "source": "synthetic_fixture",
        "simulated": True,
    }],
    "cliente2001": [],
}


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

def lookup_settlement(user_id: str) -> dict:
    """Return synthetic settlement records for a known customer.

    The records are intentionally simulated and do not represent a real
    Getnet settlement integration.
    """
    customer = CUSTOMERS.get(user_id)

    if customer is None:
        return {
            "found": False,
            "simulated": True,
            "customer_id": user_id,
            "message": "Cliente não encontrado na base de dados simulada.",
        }

    records = [record.copy() for record in SETTLEMENTS.get(user_id, [])]

    if records:
        return {
            "found": True,
            "simulated": True,
            "customer_id": user_id,
            "records": records,
            "message": "Há registros de liquidação disponíveis para este cliente.",
        }

    return {
        "found": True,
        "simulated": True,
        "customer_id": user_id,
        "records": [],
        "message": (
            "Não há registros de liquidação para este cliente neste "
            "ambiente simulado."
        ),
    }


def _register_customer_tools() -> None:
    """Register the customer support tools in the central provider-independent registry."""
    tool_registry.register(
        Tool(
            name="lookup_customer",
            description="Recupera um cliente pelo ID do usuário autenticado.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            trusted_context=("user_id",),
            handler=lookup_customer,
        )
    )

    tool_registry.register(
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
        )
    )

    tool_registry.register(
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
        )
    )


_register_customer_tools()

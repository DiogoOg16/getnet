"""Tools for retrieving simulated customer and transaction data."""

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
    "txn2001": {
        "transaction_id": "txn2001",
        "customer_id": "cliente2001",
        "amount": 250.00,
        "currency": "BRL",
        "status": "declined",
    },
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
    """Return simulated settlement guidance for a known customer.

    This tool does not access real Getnet settlement records or predict
    an actual deposit date.
    """
    customer = CUSTOMERS.get(user_id)

    if customer is None:
        return {
            "found": False,
            "simulated": True,
            "message": "Cliente não encontrado na base de dados simulada.",
        }

    return {
        "found": True,
        "simulated": True,
        "customer_id": user_id,
        "message": (
            "O prazo de recebimento depende do canal de pagamento e do "
            "produto contratado. Este ambiente utiliza dados simulados e "
            "não possui registros reais de recebimento nem permite confirmar "
            "a data de depósito das vendas."
        ),
    }

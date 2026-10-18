from app.tools.customer_tools import (
    lookup_customer,
    lookup_transaction,
)


class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    def answer(self, message: str, user_id: str) -> dict:
        text = message.casefold()

        transaction_id = next(
            (
                token.strip(".,!?;:")
                for token in message.split()
                if token.lower().startswith("txn")
            ),
            None,
        )

        if transaction_id:
            result = lookup_transaction(transaction_id, user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não encontrei essa transação para o cliente informado. "
                        "Confirme o identificador e tente novamente."
                    ),
                    "tool_used": "lookup_transaction",
                }

            transaction = result["transaction"]
            status_messages = {
                "approved": "aprovada",
                "pending": "pendente",
                "declined": "recusada",
            }
            status = status_messages.get(
                transaction["status"],
                transaction["status"],
            )

            return {
                "agent": "customer_support",
                "response": (
                    f"A transação {transaction['transaction_id']} está "
                    f"{status}. Valor: R$ {transaction['amount']:.2f}."
                ),
                "tool_used": "lookup_transaction",
            }

        if any(
            term in text
            for term in (
                "cliente",
                "minha conta",
                "meu cadastro",
                "meus dados",
                "meu perfil",
                "status da conta",
            )
        ):
            result = lookup_customer(user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não encontrei esse cliente na base simulada."
                    ),
                    "tool_used": "lookup_customer",
                }

            customer = result["customer"]
            return {
                "agent": "customer_support",
                "response": (
                    f"Encontrei o cadastro de {customer['name']}. "
                    f"Status da conta: {customer['account_status']}."
                ),
                "tool_used": "lookup_customer",
            }

        return {
            "agent": "customer_support",
            "response": (
                "Posso consultar dados cadastrais ou uma transação específica. "
                "Para consultar uma transação, informe seu identificador, "
                "por exemplo txn1001."
            ),
            "tool_used": None,
        }

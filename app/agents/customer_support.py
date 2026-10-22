from app.tools.customer_tools import (
    lookup_customer,
    lookup_transaction,
)


class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    def answer(self, message: str, user_id: str) -> dict:
        text = message.casefold()

        settlement_timing = any(
            term in text
            for term in (
                "quando o dinheiro",
                "when will the money",
                "be deposited",
                "yesterday's sales",
                "yesterday’s sales",
                "when will i receive",
                "quando vai cair",
                "prazo de recebimento",
                "prazo de deposito",
                "depositado",
                "recebimento",
                "vendas de ontem",
                "dinheiro das vendas",
                "quando o valor",
            )
        )

        transaction_id = next(
            (
                token.strip(".,!?;:")
                for token in message.split()
                if token.lower().startswith("txn")
            ),
            None,
        )

        if settlement_timing and not transaction_id:
            return {
                "agent": "customer_support",
                "response": (
                    "O prazo de recebimento depende do canal e do tipo de venda. "
                    "Em geral, o crédito costuma ocorrer em prazo de dias úteis, "
                    "mas a data exata pode variar conforme a operação e o produto. "
                    "Se quiser confirmar um caso específico, informe o identificador "
                    "da transação ou o canal em que a venda foi feita."
                ),
                "tool_used": "settlement_timeline",
            }

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

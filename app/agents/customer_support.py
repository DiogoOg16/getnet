from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)

class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    def answer(self, message: str, user_id: str) -> dict:
        text = message.casefold()
        declined_transaction = any(
            term in text
            for term in (
                "transaction decline",
                "transaction declined",
                "declined transaction",
                "transação recusada",
                "transacao recusada",
                "transação negada",
                "transacao negada",
                "cartão recusado",
                "cartao recusado",
            )
        )

        if declined_transaction:
            return {
                "agent": "customer_support",
                "response": (
                    "A transação parece ter sido recusada, mas ainda não "
                    "consultei uma operação específica. Confira se os dados "
                    "do cartão e as informações da venda estão corretos e "
                    "tente novamente, se apropriado. Se o problema persistir, "
                    "informe o identificador da transação (por exemplo, "
                    "txn2001) para que eu possa consultar o status."
                ),
                "tool_used": None,
            }

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
            result = lookup_settlement(user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não consegui localizar o cadastro na base simulada "
                        "para consultar as orientações de recebimento."
                    ),
                    "tool_used": "lookup_settlement",
                }

            return {
                "agent": "customer_support",
                "response": (
                    f"{result['message']} "
                    "Para verificar uma operação específica, informe o "
                    "identificador da transação, por exemplo txn1001."
                ),
                "tool_used": "lookup_settlement",
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

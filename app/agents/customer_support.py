
from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)


class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    @staticmethod
    def _extract_transaction_id(message: str) -> str | None:
        for token in message.split():
            candidate = token.strip(".,!?;:()[]{}").lower()
            if candidate.startswith("txn") and len(candidate) > 3:
                return candidate
        return None

    def answer(self, message: str, user_id: str) -> dict:
        text = message.casefold()

        transaction_id = self._extract_transaction_id(message)

        declined_transaction = any(
            term in text
            for term in (
                "recusad",
                "negad",
                "declin",
                "declined",
                "decline",
            )
        )

        # If a transaction ID is provided, always verify ownership and status.
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
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "waiting_for_user_input",
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

            response = (
                f"A transação {transaction['transaction_id']} está "
                f"{status}. Valor: R$ {transaction['amount']:.2f}."
            )

            if declined_transaction and transaction["status"] == "declined":
                response += (
                    " A base simulada não contém o motivo específico da recusa. "
                    "Consulte os detalhes da venda no sistema de origem ou "
                    "solicite atendimento especializado."
                )

            return {
                "agent": "customer_support",
                "response": response,
                "tool_used": "lookup_transaction",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": True,
                "awaiting_user_input": False,
                "step_status": "success",
            }

        if declined_transaction:
            return {
                "agent": "customer_support",
                "response": (
                    "Para verificar uma venda recusada, preciso do identificador "
                    "da transação (por exemplo, txn1001). Sem esse identificador, "
                    "não consigo confirmar o status nem o motivo da recusa."
                ),
                "tool_used": None,
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": False,
                "awaiting_user_input": True,
                "step_status": "waiting_for_user_input",
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

        if settlement_timing:
            result = lookup_settlement(user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não consegui localizar o cadastro na base simulada "
                        "para consultar as orientações de recebimento."
                    ),
                    "tool_used": "lookup_settlement",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": False,
                    "step_status": "failed",
                }

            return {
                "agent": "customer_support",
                "response": (
                    f"{result['message']} "
                    "Para verificar uma operação específica, informe o "
                    "identificador da transação, por exemplo txn1001."
                ),
                "tool_used": "lookup_settlement",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": True,
                "awaiting_user_input": False,
                "step_status": "success",
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
                    "response": "Não encontrei esse cliente na base simulada.",
                    "tool_used": "lookup_customer",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": False,
                    "step_status": "failed",
                }

            customer = result["customer"]
            return {
                "agent": "customer_support",
                "response": (
                    f"Encontrei o cadastro de {customer['name']}. "
                    f"Status da conta: {customer['account_status']}."
                ),
                "tool_used": "lookup_customer",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": True,
                "awaiting_user_input": False,
                "step_status": "success",
            }

        return {
            "agent": "customer_support",
            "response": (
                "Posso consultar dados cadastrais, recebimentos simulados "
                "ou uma transação específica. Para consultar uma transação, "
                "informe seu identificador, por exemplo txn1001."
            ),
            "tool_used": None,
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "awaiting_user_input": True,
            "step_status": "waiting_for_user_input",
        }

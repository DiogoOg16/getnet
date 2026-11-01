
from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)
from app.verified_facts import make_verified_fact


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
                    "verified_facts": [],
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

            if transaction["status"] == "declined":
                decline_reason = transaction.get("decline_reason")
                if decline_reason:
                    response += f" Motivo da recusa: {decline_reason}."
                else:
                    response += (
                        " Não há detalhes disponíveis sobre o motivo da recusa "
                        "neste registro."
                    )

            verified_facts = [
                make_verified_fact(
                    entity=transaction["transaction_id"],
                    name="status",
                    value=transaction["status"],
                    source_agent="customer_support",
                    source_tool="lookup_transaction",
                ),
                make_verified_fact(
                    entity=transaction["transaction_id"],
                    name="amount",
                    value=transaction["amount"],
                    source_agent="customer_support",
                    source_tool="lookup_transaction",
                ),
                make_verified_fact(
                    entity=transaction["transaction_id"],
                    name="currency",
                    value=transaction["currency"],
                    source_agent="customer_support",
                    source_tool="lookup_transaction",
                ),
            ]

            return {
                "agent": "customer_support",
                "response": response,
                "tool_used": "lookup_transaction",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": True,
                "awaiting_user_input": False,
                "step_status": "success",
                "verified_facts": verified_facts,
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
                "verified_facts": [],
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

            if result.get("records"):
                details = []
                for index, record in enumerate(result["records"], start=1):
                    status = record.get("status") or "não disponível"
                    amount = record.get("amount")
                    currency = record.get("currency")
                    date_value = record.get("estimated_settlement_date")

                    item_parts = [
                        f"Registro {index}: status {status}",
                    ]

                    if amount is not None:
                        item_parts.append(f"valor: R$ {float(amount):.2f}")
                    if currency:
                        item_parts.append(f"moeda: {currency}")
                    if date_value:
                        item_parts.append(f"data prevista: {date_value}")
                    else:
                        item_parts.append("data prevista: não disponível")

                    details.append("; ".join(item_parts))

                message = (
                    "Prazo de recebimento: "
                    + "; ".join(details)
                    + "."
                )
            else:
                message = result["message"]

            return {
                "agent": "customer_support",
                "response": (
                    f"{message} Para verificar uma operação específica, informe o "
                    "identificador da transação, por exemplo txn1001."
                ),
                "tool_used": "lookup_settlement",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": True,
                "awaiting_user_input": False,
                "step_status": "success",
                "verified_facts": [],
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
                    "verified_facts": [],
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
                "verified_facts": [],
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
            "verified_facts": [],
        }

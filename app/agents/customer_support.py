import re
import unicodedata

from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)
from app.verified_facts import make_verified_fact


class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    @staticmethod
    def _normalize_text(message: str) -> str:
        text = (
            message.casefold()
            .replace("’", "'")
            .replace("‑", "-")
            .replace("–", "-")
            .replace("—", "-")
        )
        text = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()

    @staticmethod
    def _extract_transaction_id(message: str) -> str | None:
        for token in message.split():
            candidate = token.strip(".,!?;:()[]{}").lower()
            if candidate.startswith("txn") and len(candidate) > 3:
                return candidate
        return None

    @classmethod
    def _extract_terminal_context(cls, message: str) -> dict:
        text = cls._normalize_text(message)
        lower_text = text.lower()

        connectivity_issue = any(
            term in lower_text
            for term in (
                "não conecta",
                "nao conecta",
                "sem internet",
                "sem conexão",
                "sem sinal",
                "offline",
                "não funciona",
                "nao funciona",
                "desconecta",
                "cai toda hora",
                "sem wi-fi",
                "sem wifi",
                "não liga",
                "nao liga",
                "offline",
            )
        )

        mentions_device = any(
            term in lower_text
            for term in (
                "maquininha",
                "terminal",
                "card machine",
                "card reader",
            )
        )

        has_wifi_term = any(
            term in lower_text
            for term in ("wi-fi", "wifi", "rede wi-fi", "wireless")
        )
        has_wifi_signal = has_wifi_term and not any(
            term in lower_text
            for term in (
                "indisponível",
                "indisponivel",
                "não aparece",
                "nao aparece",
                "sem wi-fi",
                "sem wifi",
            )
        )
        has_internet_issue = any(
            term in lower_text
            for term in (
                "internet",
                "rede",
                "sinal",
                "conexão",
                "conexao",
            )
        )

        error_hint = ""
        for pattern in (
            r"erro[^.]{0,80}",
            r"mensagem[^.]{0,80}",
            r"aviso[^.]{0,80}",
        ):
            match = re.search(pattern, lower_text)
            if match:
                error_hint = match.group(0).strip()
                break

        observed_behavior = ""
        for pattern in (
            r"não conecta[^.]{0,80}",
            r"nao conecta[^.]{0,80}",
            r"sem internet[^.]{0,80}",
            r"sem sinal[^.]{0,80}",
            r"offline[^.]{0,80}",
            r"não funciona[^.]{0,80}",
            r"nao funciona[^.]{0,80}",
            r"desconecta[^.]{0,80}",
            r"cai toda hora[^.]{0,80}",
        ):
            match = re.search(pattern, lower_text)
            if match:
                observed_behavior = match.group(0).strip()
                break

        return {
            "issue_type": "connectivity" if connectivity_issue and mentions_device else None,
            "has_internet_issue": has_internet_issue,
            "has_wifi_signal": has_wifi_signal,
            "error_hint": error_hint,
            "observed_behavior": observed_behavior,
            "mentions_device": mentions_device,
        }

    @classmethod
    def _looks_like_terminal_connectivity_issue(cls, message: str) -> bool:
        context = cls._extract_terminal_context(message)
        return bool(context["issue_type"] == "connectivity")

    @staticmethod
    def _missing_terminal_details(context: dict, message: str) -> list[str]:
        text = CustomerSupportAgent._normalize_text(message)
        missing: list[str] = []
        wifi_known = any(term in text for term in ("wi-fi", "wifi", "rede wi-fi", "wireless", "sinal"))
        if not wifi_known and not context.get("has_internet_issue"):
            missing.append("se a maquininha mostra Wi‑Fi ou sinal de rede disponíveis")
        elif not wifi_known and "internet" in text:
            missing.append("se a maquininha mostra Wi‑Fi ou sinal de rede disponíveis")
        if not context.get("error_hint") and not any(
            term in text
            for term in ("não conecta", "nao conecta", "sem internet", "sem sinal", "offline")
        ):
            missing.append("qual mensagem ou erro aparece na tela")
        if not context.get("observed_behavior") and not any(
            term in text
            for term in ("não conecta", "nao conecta", "sem internet", "offline")
        ):
            missing.append("o que acontece quando a maquininha tenta se conectar")
        return missing

    @staticmethod
    def _knowledge_followup(message: str) -> dict | None:
        from app.agents.knowledge import KnowledgeAgent

        knowledge_result = KnowledgeAgent().answer(message)
        response = str(knowledge_result.get("response", "")).strip()
        if not response:
            return None
        if "não encontrei informações suficientes" in response.lower():
            return None
        if "não encontrei informações" in response.lower() and "base de conhecimento" in response.lower():
            return None
        return knowledge_result

    def answer(self, message: str, user_id: str) -> dict:
        text = self._normalize_text(message)

        connectivity_issue = self._looks_like_terminal_connectivity_issue(message)
        if connectivity_issue:
            context = self._extract_terminal_context(message)
            explicit_handoff = bool(
                re.search(
                    r"(?:não há|nao ha|sem|não encontrei|nao encontrei).*?(?:orienta[cç][aã]o|guia|procedimento|base).*?(?:segura|suficiente)",
                    self._normalize_text(message),
                )
            )
            if explicit_handoff:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não há uma orientação segura suficiente na base atual para continuar este diagnóstico. "
                        "Vou encaminhar para atendimento humano para continuidade do suporte."
                    ),
                    "tool_used": "knowledge",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "resolved": False,
                    "awaiting_user_input": False,
                    "step_status": "handoff",
                    "verified_facts": [],
                    "handoff_required": True,
                }

            missing = self._missing_terminal_details(context, message)
            if missing:
                details = "; ".join(missing).replace("‑", "-").replace("–", "-").replace("—", "-")
                response = (
                    "Para continuar o diagnóstico de conectividade da maquininha, preciso confirmar "
                    f"{details}. Isso ajuda a decidir o próximo passo sobre Wi-Fi ou rede sem inventar dados do terminal."
                )
                return {
                    "agent": "customer_support",
                    "response": response,
                    "tool_used": None,
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "waiting_for_user_input",
                    "verified_facts": [],
                    "handoff_required": False,
                }

            knowledge_result = self._knowledge_followup(message)
            if knowledge_result:
                response = str(knowledge_result.get("response", "")).replace("‑", "-").replace("–", "-").replace("—", "-")
                if response.strip():
                    return {
                        "agent": "customer_support",
                        "response": (
                            "Com base na documentação disponível da Getnet:\n\n"
                            f"{response}"
                        ),
                        "tool_used": knowledge_result.get("tool_used", "knowledge"),
                        "sources": knowledge_result.get("sources", []),
                        "source_sections": knowledge_result.get("source_sections", {}),
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": False,
                        "resolved": False,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                        "handoff_required": False,
                    }

            return {
                "agent": "customer_support",
                "response": (
                    "Não encontrei documentação suficiente na base atual para orientar este caso de conectividade "
                    "de forma segura. Vou encaminhar para atendimento humano para continuidade do diagnóstico."
                ),
                "tool_used": "knowledge",
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": False,
                "resolved": False,
                "awaiting_user_input": False,
                "step_status": "handoff",
                "verified_facts": [],
                "handoff_required": True,
            }

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

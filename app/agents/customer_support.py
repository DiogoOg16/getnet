import re
import unicodedata
from typing import Any

from app.llm.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
)
from app.llm.ollama_function_calling import OllamaFunctionCallingLoop
from app.llm.ollama_tools import registry_to_ollama_tools
from app.tools.registry import ToolExecutor, ToolRegistry, tool_registry
from app.verified_facts import make_verified_fact

TERMINAL_CONNECTIVITY_FLOW = "terminal_connectivity"


class CustomerSupportAgent:
    """Handles customer-specific questions using support tools."""

    def __init__(
        self,
        *,
        client: OllamaClient | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
        loop: OllamaFunctionCallingLoop | None = None,
    ) -> None:
        self.client = client or OllamaClient()
        self.registry = registry if registry is not None else tool_registry
        if not isinstance(self.registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry instance.")
        self.executor = executor or ToolExecutor(self.registry)
        self.loop = loop or OllamaFunctionCallingLoop(
            client=self.client,
            registry=self.registry,
            executor=self.executor,
        )

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
                "won't connect",
                "wont connect",
                "can't connect",
                "cant connect",
                "cannot connect",
                "sem internet",
                "no internet",
                "sem conexão",
                "sem sinal",
                "offline",
                "não funciona",
                "nao funciona",
                "not working",
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
            r"won'?t connect[^.]{0,80}",
            r"can'?t connect[^.]{0,80}",
            r"cannot connect[^.]{0,80}",
            r"sem internet[^.]{0,80}",
            r"no internet[^.]{0,80}",
            r"sem sinal[^.]{0,80}",
            r"offline[^.]{0,80}",
            r"não funciona[^.]{0,80}",
            r"nao funciona[^.]{0,80}",
            r"not working[^.]{0,80}",
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

    def _authorized_tools(self, *, tool_names: list[str]) -> list[dict[str, Any]]:
        authorized = set(tool_names)
        return [
            tool
            for tool in registry_to_ollama_tools(self.registry)
            if tool.get("function", {}).get("name") in authorized
        ]

    def _execute_backend_tool(self, tool_name: str, arguments: dict[str, Any], user_id: str) -> Any:
        return self.executor.execute(tool_name, arguments, context={"user_id": user_id})

    @staticmethod
    def _tool_calling_instruction(allowed_tools: list[str]) -> str:
        tool_list = ", ".join(allowed_tools)
        return (
            "Você está em modo de execução operacional. "
            f"Ferramentas autorizadas nesta etapa: {tool_list}. "
            "Quando a solicitação exigir consulta operacional, você deve chamar a ferramenta autorizada. "
            "Se a ferramenta não exigir argumentos do usuário, envie arguments como objeto vazio. "
            "Não peça user_id, customer_id, identidade autenticada ou contexto interno ao usuário. "
            "Não invente dados e não responda como se a consulta tivesse sido executada sem chamar ferramenta."
        )

    def _function_calling_messages(self, message: str, allowed_tools: list[str] | None, *, retry: bool = False) -> list[dict[str, str]]:
        if not allowed_tools:
            return [{"role": "user", "content": message}]

        instruction = self._tool_calling_instruction(list(allowed_tools))
        if retry:
            instruction += (
                " Tentativa obrigatória de correção: a resposta anterior foi inválida por não chamar ferramenta. "
                "Nesta resposta, gere tool_calls agora usando uma das ferramentas autorizadas."
            )

        return [
            {
                "role": "system",
                "content": instruction,
            },
            {"role": "user", "content": message},
        ]

    def _run_function_calling_once(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        tool_payload: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return self.loop.run(
            messages,
            context={"user_id": user_id},
            tools=tool_payload,
        )

    @staticmethod
    def _is_infrastructure_tool_call_error(error: Exception) -> bool:
        return isinstance(
            error,
            (
                OllamaConnectionError,
                OllamaTimeoutError,
                ConnectionError,
                TimeoutError,
            ),
        )

    @staticmethod
    def _should_use_backend_fallback(loop_result: dict[str, Any]) -> bool:
        return bool(
            loop_result.get("status") == "tool_call_error"
            and loop_result.get("infrastructure_error") is True
        )

    def _run_function_calling(self, message: str, user_id: str, *, allowed_tools: list[str] | None = None) -> dict[str, Any]:
        tool_payload = self._authorized_tools(tool_names=list(allowed_tools) if allowed_tools else []) if allowed_tools else None
        messages = self._function_calling_messages(message, allowed_tools)
        try:
            result = self._run_function_calling_once(messages, user_id, tool_payload)
        except Exception as exc:  # pragma: no cover - exercised via tests using fake loop failures
            return {
                "status": "tool_call_error",
                "error": str(exc),
                "tool_results": [],
                "infrastructure_error": self._is_infrastructure_tool_call_error(exc),
            }

        if not isinstance(result, dict):
            return {
                "status": "invalid_result",
                "error": "Unexpected function-calling result payload.",
                "tool_results": [],
            }

        tool_results = result.get("tool_results")
        if not isinstance(tool_results, list):
            return {
                "status": "invalid_result",
                "error": "Tool-calling result is missing tool_results.",
                "tool_results": [],
            }

        if result.get("status") == "max_iterations_exceeded":
            return {
                "status": "max_iterations_exceeded",
                "error": "Function-calling loop exceeded the iteration limit.",
                "tool_results": tool_results,
            }

        if result.get("status") == "completed" and not tool_results and allowed_tools:
            retry_messages = self._function_calling_messages(message, allowed_tools, retry=True)
            try:
                retry_result = self._run_function_calling_once(retry_messages, user_id, tool_payload)
            except Exception as exc:  # pragma: no cover - exercised via tests using fake loop failures
                return {
                    "status": "tool_call_error",
                    "error": str(exc),
                    "tool_results": [],
                    "infrastructure_error": self._is_infrastructure_tool_call_error(exc),
                }

            if not isinstance(retry_result, dict):
                return {
                    "status": "invalid_result",
                    "error": "Unexpected function-calling result payload.",
                    "tool_results": [],
                }

            retry_tool_results = retry_result.get("tool_results")
            if not isinstance(retry_tool_results, list):
                return {
                    "status": "invalid_result",
                    "error": "Tool-calling result is missing tool_results.",
                    "tool_results": [],
                }

            retry_status = retry_result.get("status")
            if retry_status != "completed":
                normalized_retry = dict(retry_result)
                normalized_retry["status"] = (
                    str(retry_status) if retry_status is not None else "invalid_result"
                )
                normalized_retry["tool_results"] = retry_tool_results
                return normalized_retry

            tool_results = retry_tool_results

        if not tool_results:
            return {
                "status": "no_tool_calls",
                "tool_results": [],
            }

        return {
            "status": "tool_call_success",
            "tool_results": tool_results,
        }

    @staticmethod
    def _tool_payload_from_result(tool_result: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(tool_result, dict):
            return None

        payload = tool_result.get("result")
        if not isinstance(payload, dict):
            return None

        if payload.get("ok") is False:
            return None

        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            payload = nested_result

        if not isinstance(payload, dict):
            return None

        if any(key in payload for key in ("found", "transaction", "customer", "records", "message")):
            return payload
        return None

    @staticmethod
    def _verified_facts_from_tool_result(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if tool_name != "lookup_transaction":
            return []

        transaction = payload.get("transaction") if isinstance(payload, dict) else None
        if not isinstance(transaction, dict):
            return []

        facts: list[dict[str, Any]] = []
        for field_name, value in (
            ("status", transaction.get("status")),
            ("amount", transaction.get("amount")),
            ("currency", transaction.get("currency")),
        ):
            if value is None:
                continue
            try:
                facts.append(
                    make_verified_fact(
                        entity=str(transaction.get("transaction_id", "unknown")),
                        name=field_name,
                        value=value,
                        source_agent="customer_support",
                        source_tool="lookup_transaction",
                    )
                )
            except ValueError:
                continue
        return facts

    def escalate_terminal_connectivity(self, issue_message: str, reply: str) -> dict:
        """Encerra o diagnóstico depois que o usuário informou os detalhes pedidos.

        A base não tem procedimento de conectividade por modelo, então o caminho
        é determinístico: sem LLM, sem ferramentas e sem instruções inventadas.
        """
        return {
            "agent": "customer_support",
            "response": (
                "Entendi que o problema de conectividade da maquininha continua. "
                "Não encontrei documentação suficiente na base atual para orientar "
                "este caso de forma segura. Vou encaminhar para atendimento humano "
                "para continuidade do diagnóstico."
            ),
            "tool_used": None,
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "resolved": False,
            "awaiting_user_input": False,
            "step_status": "handoff",
            "verified_facts": [],
            "handoff_required": True,
            "handoff_message": f"{issue_message} | Complemento: {reply}",
            "handoff_flow": TERMINAL_CONNECTIVITY_FLOW,
        }

    def _connectivity_guidance(self, issue_message: str) -> dict:
        """Orienta pela base quando houver documentação ou encaminha ao atendimento."""
        knowledge_result = self._knowledge_followup(issue_message)
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
            "handoff_flow": TERMINAL_CONNECTIVITY_FLOW,
        }

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
                    "handoff_flow": TERMINAL_CONNECTIVITY_FLOW,
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
                    "pending_followup": {
                        "flow": TERMINAL_CONNECTIVITY_FLOW,
                        "original_message": message,
                    },
                }

            return self._connectivity_guidance(message)

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
            loop_result = self._run_function_calling(message, user_id, allowed_tools=["lookup_transaction"])
            loop_status = loop_result.get("status")
            if loop_status == "tool_call_error":
                if self._should_use_backend_fallback(loop_result):
                    result = self._execute_backend_tool("lookup_transaction", {"transaction_id": transaction_id}, user_id)

                    if not result["found"]:
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não encontrei essa transação para o cliente informado. "
                                "Confirme o identificador e tente novamente."
                            ),
                            "tool_used": "lookup_transaction",
                            "function_call_status": "no_tool_calls",
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
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": verified_facts,
                    }
                return {
                    "agent": "customer_support",
                    "response": "Não foi possível consultar a transação neste momento porque o serviço de ferramentas falhou.",
                    "tool_used": None,
                    "function_call_status": "tool_call_error",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "tool_call_error",
                    "verified_facts": [],
                }
            if loop_status == "max_iterations_exceeded":
                return {
                    "agent": "customer_support",
                    "response": "A consulta de transação excedeu o limite de tentativas. Tente novamente com um identificador válido.",
                    "tool_used": None,
                    "function_call_status": "max_iterations_exceeded",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "max_iterations_exceeded",
                    "verified_facts": [],
                }
            if loop_status == "invalid_result":
                return {
                    "agent": "customer_support",
                    "response": "A resposta da ferramenta de transação veio incompleta ou inválida, então não posso confirmar o status com segurança.",
                    "tool_used": None,
                    "function_call_status": "invalid_result",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "invalid_result",
                    "verified_facts": [],
                }
            if loop_status == "tool_call_success":
                recognized = False
                for tool_result in loop_result.get("tool_results") or []:
                    tool_name = tool_result.get("tool_name")
                    if tool_name != "lookup_transaction":
                        continue
                    recognized = True
                    payload = self._tool_payload_from_result(tool_result)
                    if payload is None:
                        return {
                            "agent": "customer_support",
                            "response": "A ferramenta de transação respondeu com dados inválidos e não posso confirmar a operação com segurança.",
                            "tool_used": None,
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }
                    if "found" in payload and not payload.get("found", False):
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não encontrei essa transação para o cliente informado. "
                                "Confirme o identificador e tente novamente."
                            ),
                            "tool_used": "lookup_transaction",
                            "function_call_status": "tool_call_success",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "waiting_for_user_input",
                            "verified_facts": [],
                        }
                    if "found" not in payload:
                        return {
                            "agent": "customer_support",
                            "response": "A ferramenta de transação respondeu sem a estrutura necessária para confirmar a operação.",
                            "tool_used": None,
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }

                    transaction = payload.get("transaction")
                    if not isinstance(transaction, dict):
                        return {
                            "agent": "customer_support",
                            "response": "A ferramenta de transação respondeu sem os dados obrigatórios da operação.",
                            "tool_used": None,
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }

                    required_fields = {"transaction_id", "status", "amount", "currency"}
                    missing = sorted(required_fields - set(transaction))
                    if missing:
                        return {
                            "agent": "customer_support",
                            "response": "A resposta da ferramenta de transação está incompleta para validar a operação.",
                            "tool_used": None,
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }

                    status_messages = {
                        "approved": "aprovada",
                        "pending": "pendente",
                        "declined": "recusada",
                    }
                    status = status_messages.get(transaction["status"], transaction["status"])

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

                    verified_facts = self._verified_facts_from_tool_result("lookup_transaction", payload)
                    return {
                        "agent": "customer_support",
                        "response": response,
                        "tool_used": "lookup_transaction",
                        "function_call_status": "tool_call_success",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": verified_facts,
                    }
                if recognized is False:
                    result = self._execute_backend_tool("lookup_transaction", {"transaction_id": transaction_id}, user_id)

                    if not result["found"]:
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não encontrei essa transação para o cliente informado. "
                                "Confirme o identificador e tente novamente."
                            ),
                            "tool_used": "lookup_transaction",
                            "function_call_status": "no_tool_calls",
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
                    status = status_messages.get(transaction["status"], transaction["status"])

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
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": verified_facts,
                    }

            result = self._execute_backend_tool("lookup_transaction", {"transaction_id": transaction_id}, user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não encontrei essa transação para o cliente informado. "
                        "Confirme o identificador e tente novamente."
                    ),
                    "tool_used": "lookup_transaction",
                    "function_call_status": "no_tool_calls",
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
                "function_call_status": "no_tool_calls",
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
                "function_call_status": "no_tool_calls",
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
            loop_result = self._run_function_calling(message, user_id, allowed_tools=["lookup_settlement"])
            loop_status = loop_result.get("status")
            if loop_status == "tool_call_error":
                if self._should_use_backend_fallback(loop_result):
                    result = self._execute_backend_tool("lookup_settlement", {}, user_id)

                    if not result["found"]:
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não consegui localizar o cadastro na base simulada "
                                "para consultar as orientações de recebimento."
                            ),
                            "tool_used": "lookup_settlement",
                            "function_call_status": "no_tool_calls",
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

                        message_text = (
                            "Prazo de recebimento: "
                            + "; ".join(details)
                            + "."
                        )
                    else:
                        message_text = result["message"]

                    return {
                        "agent": "customer_support",
                        "response": (
                            f"{message_text} Para verificar uma operação específica, informe o "
                            "identificador da transação, por exemplo txn1001."
                        ),
                        "tool_used": "lookup_settlement",
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }
                return {
                    "agent": "customer_support",
                    "response": "Não foi possível consultar o prazo de recebimento porque a ferramenta falhou.",
                    "tool_used": None,
                    "function_call_status": "tool_call_error",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "tool_call_error",
                    "verified_facts": [],
                }
            if loop_status == "max_iterations_exceeded":
                return {
                    "agent": "customer_support",
                    "response": "A consulta de recebimento excedeu o limite de tentativas e não posso confirmar o prazo com segurança.",
                    "tool_used": None,
                    "function_call_status": "max_iterations_exceeded",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "max_iterations_exceeded",
                    "verified_facts": [],
                }
            if loop_status == "invalid_result":
                return {
                    "agent": "customer_support",
                    "response": "A resposta da ferramenta de recebimento veio incompleta e não posso confirmar o prazo sem dados válidos.",
                    "tool_used": None,
                    "function_call_status": "invalid_result",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "invalid_result",
                    "verified_facts": [],
                }
            if loop_status == "tool_call_success":
                recognized = False
                for tool_result in loop_result.get("tool_results") or []:
                    tool_name = tool_result.get("tool_name")
                    if tool_name != "lookup_settlement":
                        continue
                    recognized = True
                    payload = self._tool_payload_from_result(tool_result)
                    if payload is None:
                        return {
                            "agent": "customer_support",
                            "response": "A ferramenta de recebimento respondeu com dados inválidos para confirmar o prazo.",
                            "tool_used": "lookup_settlement",
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }
                    result = payload
                    if not result.get("found"):
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não consegui localizar o cadastro na base simulada "
                                "para consultar as orientações de recebimento."
                            ),
                            "tool_used": "lookup_settlement",
                            "function_call_status": "tool_call_success",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": False,
                            "step_status": "failed",
                        }

                    if result.get("records"):
                        details = []
                        for index, record in enumerate(result["records"], start=1):
                            if not isinstance(record, dict):
                                return {
                                    "agent": "customer_support",
                                    "response": "A resposta de recebimento inclui registros incompletos e não pode ser usada com segurança.",
                                    "tool_used": "lookup_settlement",
                                    "function_call_status": "invalid_result",
                                    "flow_completed": True,
                                    "response_delivered": True,
                                    "issue_resolved": False,
                                    "awaiting_user_input": True,
                                    "step_status": "invalid_result",
                                    "verified_facts": [],
                                }
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

                        message_text = (
                            "Prazo de recebimento: "
                            + "; ".join(details)
                            + "."
                        )
                    else:
                        message_text = result.get("message", "Não há registros de liquidação disponíveis.")

                    return {
                        "agent": "customer_support",
                        "response": (
                            f"{message_text} Para verificar uma operação específica, informe o "
                            "identificador da transação, por exemplo txn1001."
                        ),
                        "tool_used": "lookup_settlement",
                        "function_call_status": "tool_call_success",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }
                if recognized is False:
                    result = self._execute_backend_tool("lookup_settlement", {}, user_id)

                    if not result.get("found"):
                        return {
                            "agent": "customer_support",
                            "response": (
                                "Não consegui localizar o cadastro na base simulada "
                                "para consultar as orientações de recebimento."
                            ),
                            "tool_used": "lookup_settlement",
                            "function_call_status": "no_tool_calls",
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

                            item_parts = [f"Registro {index}: status {status}"]
                            if amount is not None:
                                item_parts.append(f"valor: R$ {float(amount):.2f}")
                            if currency:
                                item_parts.append(f"moeda: {currency}")
                            if date_value:
                                item_parts.append(f"data prevista: {date_value}")
                            else:
                                item_parts.append("data prevista: não disponível")

                            details.append("; ".join(item_parts))

                        message_text = (
                            "Prazo de recebimento: "
                            + "; ".join(details)
                            + "."
                        )
                    else:
                        message_text = result.get("message", "Não há registros de liquidação disponíveis.")

                    return {
                        "agent": "customer_support",
                        "response": (
                            f"{message_text} Para verificar uma operação específica, informe o "
                            "identificador da transação, por exemplo txn1001."
                        ),
                        "tool_used": "lookup_settlement",
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }

            result = self._execute_backend_tool("lookup_settlement", {}, user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": (
                        "Não consegui localizar o cadastro na base simulada "
                        "para consultar as orientações de recebimento."
                    ),
                    "tool_used": "lookup_settlement",
                    "function_call_status": "no_tool_calls",
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

                message_text = (
                    "Prazo de recebimento: "
                    + "; ".join(details)
                    + "."
                )
            else:
                message_text = result["message"]

            return {
                "agent": "customer_support",
                "response": (
                    f"{message_text} Para verificar uma operação específica, informe o "
                    "identificador da transação, por exemplo txn1001."
                ),
                "tool_used": "lookup_settlement",
                "function_call_status": "no_tool_calls",
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
            loop_result = self._run_function_calling(message, user_id, allowed_tools=["lookup_customer"])
            loop_status = loop_result.get("status")
            if loop_status == "tool_call_error":
                if self._should_use_backend_fallback(loop_result):
                    result = self._execute_backend_tool("lookup_customer", {}, user_id)

                    if not result["found"]:
                        return {
                            "agent": "customer_support",
                            "response": "Não encontrei esse cliente na base simulada.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "no_tool_calls",
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
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }
                return {
                    "agent": "customer_support",
                    "response": "Não foi possível consultar o cadastro do cliente porque a ferramenta falhou.",
                    "tool_used": None,
                    "function_call_status": "tool_call_error",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "tool_call_error",
                    "verified_facts": [],
                }
            if loop_status == "max_iterations_exceeded":
                return {
                    "agent": "customer_support",
                    "response": "A consulta de cadastro excedeu o limite de tentativas e não posso confirmar a conta com segurança.",
                    "tool_used": None,
                    "function_call_status": "max_iterations_exceeded",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "max_iterations_exceeded",
                    "verified_facts": [],
                }
            if loop_status == "invalid_result":
                return {
                    "agent": "customer_support",
                    "response": "A resposta da ferramenta de cadastro veio incompleta e não posso confirmar os dados do cliente sem validação.",
                    "tool_used": None,
                    "function_call_status": "invalid_result",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "awaiting_user_input": True,
                    "step_status": "invalid_result",
                    "verified_facts": [],
                }
            if loop_status == "tool_call_success":
                recognized = False
                for tool_result in loop_result.get("tool_results") or []:
                    if tool_result.get("tool_name") != "lookup_customer":
                        continue
                    recognized = True
                    payload = self._tool_payload_from_result(tool_result)
                    if payload is None:
                        return {
                            "agent": "customer_support",
                            "response": "A ferramenta de cadastro respondeu com dados inválidos para validar a conta.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }
                    if not payload.get("found"):
                        return {
                            "agent": "customer_support",
                            "response": "Não encontrei esse cliente na base simulada.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "tool_call_success",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": False,
                            "step_status": "failed",
                            "verified_facts": [],
                        }

                    customer = payload.get("customer")
                    if not isinstance(customer, dict):
                        return {
                            "agent": "customer_support",
                            "response": "A resposta da ferramenta de cadastro não inclui os dados obrigatórios do cliente.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }
                    if not {"name", "account_status"}.issubset(customer):
                        return {
                            "agent": "customer_support",
                            "response": "A resposta da ferramenta de cadastro está incompleta para confirmar a conta do cliente.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "invalid_result",
                            "flow_completed": True,
                            "response_delivered": True,
                            "issue_resolved": False,
                            "awaiting_user_input": True,
                            "step_status": "invalid_result",
                            "verified_facts": [],
                        }
                    return {
                        "agent": "customer_support",
                        "response": (
                            f"Encontrei o cadastro de {customer['name']}. "
                            f"Status da conta: {customer['account_status']}."
                        ),
                        "tool_used": "lookup_customer",
                        "function_call_status": "tool_call_success",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }
                if recognized is False:
                    result = self._execute_backend_tool("lookup_customer", {}, user_id)

                    if not result["found"]:
                        return {
                            "agent": "customer_support",
                            "response": "Não encontrei esse cliente na base simulada.",
                            "tool_used": "lookup_customer",
                            "function_call_status": "no_tool_calls",
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
                        "function_call_status": "no_tool_calls",
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": True,
                        "awaiting_user_input": False,
                        "step_status": "success",
                        "verified_facts": [],
                    }

            result = self._execute_backend_tool("lookup_customer", {}, user_id)

            if not result["found"]:
                return {
                    "agent": "customer_support",
                    "response": "Não encontrei esse cliente na base simulada.",
                    "tool_used": "lookup_customer",
                    "function_call_status": "no_tool_calls",
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
                "function_call_status": "no_tool_calls",
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
            "function_call_status": "no_tool_calls",
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "awaiting_user_input": True,
            "step_status": "waiting_for_user_input",
            "verified_facts": [],
        }

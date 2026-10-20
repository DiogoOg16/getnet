import os

import requests

from app.rag.retriever import retrieve


class KnowledgeAgent:
    """Answers questions using retrieved documents and a local LLM."""

    def __init__(self):
        self.ollama_url = os.getenv(
            "OLLAMA_URL", "http://localhost:11434"
        )
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    def _generate(self, message: str, context: str) -> str:
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Você é um agente de suporte da Getnet. "
                            "Responda em português brasileiro, de forma "
                            "clara e direta. Use somente as informações "
                            "do contexto fornecido. Não invente regras, "
                            "taxas, procedimentos ou funcionalidades. "
                            "Se o contexto não responder à pergunta, "
                            "diga que não há informação suficiente."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Pergunta: {message}\n\n"
                            f"Contexto da base de conhecimento:\n{context}"
                        ),
                    },
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"].strip()

    def answer(self, message: str) -> dict:
        sources = retrieve(message)

        if not sources:
            return {
                "agent": "knowledge",
                "response": (
                    "Não encontrei informações suficientes na base de "
                    "conhecimento para responder com segurança. Consulte "
                    "a documentação oficial da Getnet ou o atendimento."
                ),
                "sources": [],
            }

        context = "\n\n".join(
            f"Documento: {source['title']}\n"
            f"Conteúdo: {source['content']}"
            for source in sources
        )

        try:
            answer = self._generate(message, context)
        except (requests.RequestException, ValueError, KeyError):
            answer = (
                "Não consegui gerar uma resposta agora. "
                "Tente novamente ou consulte a documentação oficial da Getnet."
            )

        return {
            "agent": "knowledge",
            "response": answer,
            "sources": [source["title"] for source in sources],
        }
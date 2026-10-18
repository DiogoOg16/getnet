from app.rag.retriever import retrieve


class KnowledgeAgent:
    """Answers product and service questions using retrieved documents."""

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
            f"{source['title']}: {source['content']}"
            for source in sources
        )

        return {
            "agent": "knowledge",
            "response": (
                "Encontrei informações relacionadas na base de conhecimento. "
                "Como esta base ainda é preliminar, confirme os detalhes "
                "na documentação oficial antes de tomar decisões.\n\n"
                f"{context}"
            ),
            "sources": [source["title"] for source in sources],
        }

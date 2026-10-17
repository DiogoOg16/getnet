from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="Getnet AI Agent",
    description="API para o sistema multiagente de suporte.",
    version="0.1.0",
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class ChatResponse(BaseModel):
    user_id: str
    message: str
    response: str


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # Resposta temporária: depois será substituída
    # pelo resultado do nosso sistema multiagente.
    return ChatResponse(
        user_id=request.user_id,
        message=request.message,
        response="API funcionando. Os agentes ainda serão implementados.",
    )
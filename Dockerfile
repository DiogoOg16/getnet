FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Só o código da aplicação: os testes ficam fora da imagem de produção.
COPY app ./app

# O código fica com o dono root (somente leitura para o usuário da aplicação);
# só /app/data, onde ficam memória de sessão e tickets, é gravável.
RUN addgroup --system app && \
    adduser --system --ingroup app --home /app --no-create-home app && \
    mkdir -p /app/data && \
    chown app:app /app/data

EXPOSE 8000

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

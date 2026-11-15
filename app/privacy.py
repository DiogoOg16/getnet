"""Identificação e mascaramento de dados pessoais (SEC-01, SEC-02).

Um só lugar define os padrões: o roteador usa CPF_PATTERN e
`contains_card_number` para detectar dado sensível colado na mensagem, e
`mask_sensitive` usa os mesmos
padrões antes de persistir texto, de entregá-lo aos agentes (e, portanto, ao
LLM) e de enviá-lo a serviços externos.

Escopo: e-mail, telefone (só com contexto), CNPJ, número de cartão e CPF.
Identificadores como `txn1003`, valores monetários, datas e códigos curtos
não casam com esses padrões.

Formatos aceitos:
- CPF: 11 dígitos, com ou sem ponto, espaço ou hífen (123.456.789-09,
  123 456 789 09, 12345678909).
- Cartão: 13 a 19 dígitos sem separador, ou grupos usuais com espaço, ponto ou
  hífen: 4-4-4-4 (opcionalmente + 1 a 3 dígitos) e 4-6-5 / 4-6-4.
  Datas (2026-11-11) e listas de valores (10 20 30) não formam esses grupos.
  Logo depois de uma palavra de cartão ("cartão", "crédito", "visa"...),
  também qualquer agrupamento de 3 a 6 dígitos com 13 a 19 dígitos no total
  (ex.: 4-4-4-3, 5-5-5, 6-6-4).
- Telefone: com +55, com DDD entre parênteses, ou logo depois de uma palavra
  de contexto ("telefone", "celular", "ligue", "meu número"...), com ou sem DDD.

Limitações conhecidas:
- 11 dígitos sem pontuação são tratados como CPF, mesmo que sejam um celular
  com DDD; o dado é mascarado de qualquer forma, só o rótulo pode estar errado.
- Telefone sem contexto (ex.: "98765-4321" sozinho) não é mascarado, para não
  confundir com outros números.
- Cartão em agrupamento incomum sem palavra de cartão por perto (ex.:
  "4111 1111 1111 111" sozinho) não é detectado.
- Outros números longos de 13 a 19 dígitos (ex.: protocolos) são mascarados
  como cartão ou CNPJ.
"""

from __future__ import annotations

import re
from typing import Any

# Padrões compartilhados com o roteador. Só grupos não capturantes: o roteador
# junta vários padrões numa alternância e grupos numerados quebrariam isso.
CPF_PATTERN = r"\b\d{3}[. ]?\d{3}[. ]?\d{3}[- ]?\d{2}\b"
CARD_PATTERN = (
    r"\b(?:"
    r"\d{13,19}"
    r"|\d{4}[ .-]?\d{4}[ .-]?\d{4}[ .-]?\d{4}(?:[ .-]?\d{1,3})?"
    r"|\d{4}[ .-]?\d{6}[ .-]?\d{4,5}"
    r")\b"
)

# Cartão em agrupamento incomum (ex.: 4-4-4-3, 5-5-5, 6-6-4): só logo depois
# de uma palavra de cartão, com conectores curtos, em grupos de 3 a 6 dígitos
# e 13 a 19 dígitos no total (o total é conferido em código). Datas e listas
# de valores têm grupos de 2 dígitos e não passam.
_CARD_KEYWORDS = (
    r"cart[aã]o|cart[oõ]es|card|cr[eé]dito|d[eé]bito"
    r"|visa|master(?:card)?|elo|amex|hipercard"
)
# Separadores possessivos (`++`, Python 3.11+): cada sequência de separadores
# é consumida inteira, sem retrocesso. Com `+` simples dentro do `*?`, o motor
# testava todas as divisões possíveis dos espaços e o tempo dobrava a cada
# espaço extra (ReDoS: ~2 s com 24 espaços depois de "cartão").
_CARD_FILLER = r"(?:[\s:,\-]++|(?:é|e|meu|minha|do|da|de|n[uú]mero|n[º°o]\.?)(?=[\s:,.\-]|$))*?"
_CARD_IN_CONTEXT = re.compile(
    r"(?i)(\b(?:" + _CARD_KEYWORDS + r")\b" + _CARD_FILLER + r")"
    r"((?<![\d.-])\d{3,6}(?:[ .-]\d{3,6}){2,5})(?![\d]|[ .-]\d)"
)
_CARD_MIN_DIGITS = 13
_CARD_MAX_DIGITS = 19

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_PHONE_INTERNATIONAL = re.compile(r"\+55[ -]?\(?\d{2}\)?[ -]?9?\d{4}[ -]?\d{4}\b")
_PHONE_AREA_CODE = re.compile(r"\(\d{2}\)[ -]?9?\d{4}[ -]?\d{4}\b")
# Palavra de contexto, depois só separadores e palavras curtas de ligação
# ("meu celular é", "ligue para", "telefone:"), depois o número, com ou sem DDD.
# "número" sozinho não basta ("número do pedido 1234567890"): só "meu número"
# e "número de telefone/do celular/do whatsapp" (estes dois últimos também
# casam pela própria palavra "celular"/"whatsapp").
_PHONE_KEYWORDS = (
    r"telefones?|tel|fones?|celular(?:es)?|cel|whatsapp|zap|phone|contato"
    r"|ligue|ligar|liga"
    r"|meus?\s+n[uú]meros?"
    r"|n[uú]meros?\s+d[eo]\s+(?:telefone|celular|whatsapp)"
)
# Mesmo cuidado com ReDoS: separadores possessivos. "número" é conector (depois
# de uma palavra de telefone: "me liga no número ..."), mas não palavra-chave.
_PHONE_FILLER = (
    r"(?:[\s:,\-]++|(?:é|eh|e|is|para|pra|pro|no|na|o|meu|minha|n[uú]mero)\b)*?"
)
# O número não pode continuar em outro grupo de 3+ dígitos: assim um cartão
# depois de "telefone" não é mascarado pela metade como telefone e fica para
# as regras de cartão (coerente com o roteador).
_PHONE_WITH_KEYWORD = re.compile(
    r"(?i)(\b(?:" + _PHONE_KEYWORDS + r")\b" + _PHONE_FILLER + r")"
    r"((?<!\d)(?:\d{2}[ -]?)?9?\d{4}[ -]?\d{4}\b(?!\d|[ .-]\d{3}))"
)
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_CARD = re.compile(CARD_PATTERN)
_CPF = re.compile(CPF_PATTERN)

EMAIL_MASK = "[EMAIL]"
PHONE_MASK = "[TELEFONE]"
CNPJ_MASK = "[CNPJ]"
CARD_MASK = "[CARTAO]"
CPF_MASK = "[CPF]"


def mask_sensitive(text: str) -> str:
    """Substitui os dados pessoais cobertos pelo escopo por marcadores.

    A ordem importa: e-mail e telefone primeiro (para que "+55 11 ..." não
    seja lido como cartão), CNPJ antes de cartão (14 dígitos), CPF por último.
    """
    if not text:
        return text
    masked = _EMAIL.sub(EMAIL_MASK, text)
    masked = _PHONE_INTERNATIONAL.sub(PHONE_MASK, masked)
    masked = _PHONE_AREA_CODE.sub(PHONE_MASK, masked)
    masked = _PHONE_WITH_KEYWORD.sub(lambda match: match.group(1) + PHONE_MASK, masked)
    masked = _CNPJ.sub(CNPJ_MASK, masked)
    masked = _CARD.sub(CARD_MASK, masked)
    masked = _CARD_IN_CONTEXT.sub(_mask_card_in_context, masked)
    masked = _CPF.sub(CPF_MASK, masked)
    return masked


def _digit_count(text: str) -> int:
    return sum(char.isdigit() for char in text)


def _is_card_length(text: str) -> bool:
    return _CARD_MIN_DIGITS <= _digit_count(text) <= _CARD_MAX_DIGITS


def _mask_card_in_context(match: re.Match) -> str:
    if _is_card_length(match.group(2)):
        return match.group(1) + CARD_MASK
    return match.group(0)


def contains_card_number(text: str) -> bool:
    """Detecção única de cartão, usada pelo roteador e coerente com o mascaramento.

    Verdadeiro se houver cartão em formato estrutural (13–19 dígitos, 4-4-4-4,
    4-6-5) ou em agrupamento incomum logo depois de uma palavra de cartão.
    """
    if not text:
        return False
    if _CARD.search(text):
        return True
    return any(_is_card_length(match.group(2)) for match in _CARD_IN_CONTEXT.finditer(text))


def mask_sensitive_data(value: Any) -> Any:
    """Aplica `mask_sensitive` a strings dentro de dicts e listas."""
    if isinstance(value, str):
        return mask_sensitive(value)
    if isinstance(value, dict):
        return {key: mask_sensitive_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_sensitive_data(item) for item in value]
    return value

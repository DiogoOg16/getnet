# Comparações da camada 2 — S06 e total (2026-11-18)

Calibração única para o S06 (decisão do usuário, opção b, rubrica literal): citar corretamente um
documento recuperado não impede C; distorcer ou generalizar a citação = P; abstenção que ainda
apresenta o procedimento = P; abstenção que não apresenta nada do contexto = I (G2).

## S06 por rodada

| Rodada | Contexto recuperado (top 3) | C | P | I | Rótulos |
|---|---|---|---|---|---|
| `939d2ba` (2026-11-08) | L46, L176, L158 (sem L145) | 0 | 10 | 0 | congelados |
| `df1ddbb` (2026-11-15), original | L46, L176, L158 (sem L145) | 2 | 0 | 8 | `labels_frozen.json`, inalterado |
| `df1ddbb`, revisão (b) | idem | 2 | 8 | 0 | `lotes/revisao_S06_decisoes.json` |
| `877163b` H1b (2026-11-17) | **L145**, L207, L46 | **5** | 2 | 3 | congelados, sha256 `46f32112…` |

Leitura:
- Com o mesmo contexto, `939d2ba` e `df1ddbb` revisado dão o mesmo quadro (nenhuma I; quase tudo P):
  sem L145 não há como explicar o conceito, e a rubrica prevê P como teto prático.
- O H1b muda o teto: com L145 no contexto, **5 de 10 ficam corretas** (antes 0 ou 2).
- O H1b também traz um modo de falha novo: **3 abstenções que não citam nada** (I, G2), embora L145 e L46
  estejam no contexto. É o mesmo gargalo de síntese do S04 (`rag07a-findings`): o documento certo
  está lá e o modelo diz que não há informação.
- **L207** (Antecipação Automática), que entrou no lugar de L176, é citado em 6 das 10 respostas;
  em 2 delas a citação é distorcida ou generalizada (as 2 P). Mesmo padrão da limitação registrada
  em Q10/Q18: o documento certo em 1º e um vizinho que puxa a resposta.

## Total dos 10 cenários oficiais (sem S05-V)

| Rodada | C | P | I | Observação |
|---|---|---|---|---|
| `939d2ba` | 32 | 48 | 6 | base |
| `df1ddbb`, original | 47 | 27 | 12 | relatório congelado |
| `df1ddbb`, S06 revisado (b) | 47 | 35 | 4 | mesma calibração em todas as rodadas |
| `df1ddbb` + S06 de `877163b` | **50** | **29** | **7** | combinação: os outros 9 cenários não foram rodados de novo |

A combinação da última linha é válida para a recuperação: entre `df1ddbb` e `877163b` só mudou o
retriever (H1b) e o código de avaliação, e o top 3 dos outros cenários oficiais não mudou (verificado
nas 61 consultas do fixture). A geração é estocástica, então os outros 9 cenários foram medidos em
outra rodada; não é uma execução única.

Por cenário em relação à base `939d2ba`: ganhos atribuíveis a mudanças de código em S08 (0 → 10 C,
ARCH-02 + P2) e S06 (0 → 5 C, H1b); S01 melhora (1 → 6 C) sem mudança de código dirigida a ele
(variação do modelo ou calibração); S04, S09 e S10 sem ganho; S02, S03, S05 e S07 corretos nas duas.

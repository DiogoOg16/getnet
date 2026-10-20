import os
import re

import requests

from app.rag.retriever import retrieve


class KnowledgeAgent:
    """Answers questions using retrieved documents and a local LLM."""

    SECTION_LABELS = {
        "customer_faq": "FAQ da Getnet",
        "faq": "FAQ",
        "technical_documentation": "Documentação técnica",
        "product_page": "Produtos e soluções",
        "general": "Geral",
        "pix": "Pix",
        "plugins": "Plugins",
        "get tap": "Get Tap",
        "maquininha": "Maquininha",
        "link de pagamento": "Link de Pagamento",
        "crediario": "Crediário",
        "conciliador": "Conciliador",
        "get conta": "Get Conta",
        "antecipacao": "Antecipação",
        "gestao de vendas": "Gestão de Vendas",
    }

    def __init__(self):
        self.ollama_url = os.getenv(
            "OLLAMA_URL", "http://localhost:11434"
        )
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    @classmethod
    def _group_sources_by_section(cls, sources: list[dict]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for source in sources:
            section_value = str(source.get("section") or source.get("category") or "Geral").strip()
            section_key = section_value.lower()
            section = cls.SECTION_LABELS.get(section_key, section_value)
            grouped.setdefault(section, [])
            title = source.get("title", "Documento sem título")
            if title not in grouped[section]:
                grouped[section].append(title)
        return grouped

    def _direct_answer(self, message: str, sources: list[dict]) -> str | None:
        query = message.lower().strip()
        titles = [source.get("title", "").lower() for source in sources]

        if "como acesso a minha get conta" in query or "acesso a minha get conta" in query:
            return (
                "Para acessar sua Get Conta, baixe o aplicativo Getnet Brasil ou acesse o Portal Minha Conta e faça login com CPF/CPNJ ou e-mail e senha cadastrados na Getnet. "
                "A documentação oficial confirma que o acesso pode ser feito pelo Aplicativo Getnet Brasil ou pelo Portal Minha Conta."
            )

        if "transferencia" in query or "transferência" in query:
            if "limite" in query or "limites" in query or "diarios" in query or "diários" in query:
                return (
                    "Na Get Conta, no aplicativo Getnet Brasil, vá em Transferência, preencha o valor e os dados da conta de destino e confirme a transferência. "
                    "Os limites documentados são: saque de R$ 1.000,00 por dia; transferências bancárias de R$ 2.000,00 por dia; transferências entre contas Getnet de R$ 1.000,00 por dia; e para boleto, o valor mínimo é R$ 10,00 e o máximo é R$ 1.000,00. "
                    "A operação exige saldo disponível na conta de pagamento."
                )

        if "tarifa de inatividade" in query or "inatividade" in query:
            return (
                "A tarifa de inatividade é cobrada quando a sua Get Conta permanece sem movimentações financeiras por 180 dias. "
                "Nessa situação, a cobrança é de R$ 10,00 por mês enquanto a conta estiver inativa, e o valor é descontado do saldo disponível. "
                "A conta volta a ficar ativa quando você realiza novas movimentações, como receber vendas, Pix, TED, pagamento de boleto, saque ou compras com o cartão Getnet Elo."
            )

        if "como estornar uma venda" in query or "estorno de uma venda" in query or "estornar uma venda" in query:
            return (
                "Para estornar uma venda na maquininha Getnet, a documentação oficial informa: "
                "1) acesse Menu > Mastercard/Visa ou Bandeiras > Suporte > Estorno; 2) informe a senha do lojista; 3) digite o valor da venda e siga os passos para passar, inserir ou digitar o cartão; 4) informe o tipo de transação, o número CV, a data da venda e o terminal de origem; 5) aguarde a impressão do comprovante. "
                "Se a venda foi realizada em outro dia, a orientação é entrar em contato com a Central de Relacionamento Getnet."
            )

        if "chargeback" in query:
            return (
                "Chargeback é a contestação de uma venda feita pelo banco quando o cliente questiona a transação. "
                "A documentação da Getnet explica que ele pode ocorrer por devolução da mercadoria, mercadoria não recebida, entrega com defeito, produto diferente do descrito, serviço não prestado adequadamente, transação não reconhecida ou não autorizada, duplicidade de transação, crédito não processado ou pagamento por meio alternativo. "
                "Em outras palavras, é um cancelamento da transação com débito na conta do estabelecimento e por isso a prevenção passa por manter a documentação, confirmar dados da venda e evitar transações ambíguas ou não reconhecidas."
            )

        if "configurar" in query and "wi" in query and "maquininha" in query:
            return (
                "Na base de conhecimento atual da Getnet, não há um artigo específico com o passo a passo exato de configuração de Wi-Fi para cada modelo de maquininha. "
                "O que a documentação confirma é que as maquininhas Getnet podem operar com conexão de internet e existem modelos com suporte a Wi-Fi, wifi e 3G/4G, e o diagnóstico correto deve ser feito com a rede, sinal e configuração do aparelho antes de qualquer teste de venda. "
                "Se a sua dúvida for sobre conexão sem internet, verifique a rede, o sinal e a autenticação do Wi-Fi do ponto de venda e, se necessário, consulte o atendimento oficial da Getnet para o modelo da sua maquininha."
            )

        if ("status" in query and "venda" in query) or "status das minhas vendas" in query:
            return (
                "Os possíveis status das suas vendas são: 1) Pré-Autorizada; 2) Autorizada; 3) Negada; "
                "4) Desfeita; 5) Estornada; 6) Cancelada; 7) Cancelada Parcial. "
                "Para vendas com Pix, os status são: Qr Code Criado, Qr Code Expirado, Paga, Negada, Enviada ao banco e Falha no repasse."
            )

        if "consultar minhas vendas" in query or ("consultar" in query and "venda" in query and "status" not in query):
            return (
                "Para consultar suas vendas, a documentação oficial aponta que você pode acessar o Aplicativo Getnet Brasil ou o Portal Minha Conta e verificar o extrato das vendas. "
                "É a forma oficial de acompanhar o histórico e o saldo das transações na Get Conta."
            )

        if "funcionalidades portal minha conta" in query or "app getnet brasil" in query or "portal minha conta" in query:
            return (
                "O Portal Minha Conta e o Aplicativo Getnet Brasil são os canais digitais oficiais para acompanhar o extrato, consultar vendas, gerenciar a Get Conta e acessar funcionalidades de movimentação e controle do seu negócio. "
                "A base confirma que as operações podem ser feitas pelo aplicativo ou pelo portal, conforme o fluxo da sua conta."
            )

        plugin_names = ("vtex", "magento", "shopify", "plugins digitais")
        error_map = {
            "adq 4-83": (
                "Erro ADQ 4-83: erro de integração com as bandeiras. "
                "Caso sua maquininha apresente um ‘Erro ADQ’ na tela, você mesmo pode solucioná-lo rapidamente. "
                "Verifique o código apresentado e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 4-91": (
                "Erro ADQ 4-91: erro na aprovação da venda. "
                "Caso sua maquininha apresente um ‘Erro ADQ’ na tela, você mesmo pode solucioná-lo rapidamente. "
                "Verifique o código apresentado e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 1-50": (
                "Erro ADQ 1-50: erro de leitura. "
                "Caso apareça um ‘Erro ADQ’ na tela da sua maquininha, você mesmo pode corrigir isso rapidamente. "
                "Verifique o código do erro e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 4-30": (
                "Erro ADQ 4-30: falha na comunicação na maquininha. "
                "Caso apareça um ‘Erro ADQ’ na tela da sua maquininha, você mesmo pode corrigir isso rapidamente. "
                "Verifique o código do erro e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 4-23": (
                "Erro ADQ 4-23: falha na transação. "
                "Ao visualizar um ‘Erro ADQ’ na tela da sua maquininha, você pode resolver isso rapidamente. "
                "Verifique o código do erro e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 4-27": (
                "Erro ADQ 4-27: erro na comunicação dos sistemas. "
                "Ao visualizar um ‘Erro ADQ’ na tela da sua maquininha, você pode resolver isso rapidamente. "
                "Verifique o código do erro e siga as instruções abaixo. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "idl 1-04": (
                "Erro IDL 1-04: erro de integração com as bandeiras/sistemas. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "idl 1-36": (
                "Erro IDL 1-36: problema na integração das bandeiras dos sistemas da Getnet. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "s-2074": (
                "Erro S-2074: erro de comunicação. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 1-02": (
                "Erro ADQ 1-02: ocorre quando não finaliza um procedimento iniciado na maquininha. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste."
            ),
            "adq 1-21": (
                "Erro ADQ 1-21: erro na transação. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste; 7. Clique na tecla de Função; 8. Insira o número 60; 9. A tela ficará verde confirmando a ação; "
                "10. Selecione a opção Configuração; 11. Depois Apagar memória; 12. Insira a Senha do Técnico; 13. A tela ficará verde confirmando a ação."
            ),
            "adq 3-30": (
                "Erro ADQ 3-30: erro de criptografia. "
                "Quando ocorre: Ao deixar de utilizar a maquininha por um período. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste; 7. Clique na tecla de Função; 8. Insira o número 60; 9. A tela ficará verde confirmando a ação; "
                "10. Selecione a opção Configuração; 11. Depois Apagar memória; 12. Insira a Senha do Técnico; 13. A tela ficará verde confirmando a ação."
            ),
            "adq 1-33": (
                "Erro ADQ 1-33: erro de leitura. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste; 7. Clique na tecla de Função; 8. Insira o número 60; 9. A tela ficará verde confirmando a ação; "
                "10. Selecione a opção Configuração; 11. Depois Apagar memória; 12. Insira a Senha do Técnico; 13. A tela ficará verde confirmando a ação."
            ),
            "adq 1-07": (
                "Erro ADQ 1-07: maquininha não inicializada. "
                "Quando ocorre: Ao tentar utilizar a maquininha. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 38; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção: Inicialização; 5. A tela ficará verde confirmando a ação, novamente; "
                "6. Em seguida, faça uma venda teste; 7. Clique na tecla de Função; 8. Insira o número 60; 9. A tela ficará verde confirmando a ação; "
                "10. Selecione a opção Configuração; 11. Depois Apagar memória; 12. Insira a Senha do Técnico; 13. A tela ficará verde confirmando a ação."
            ),
            "idl 1-08": (
                "Erro IDL 1-08: erro de integração com as bandeiras/cartão. "
                "Quando ocorre: Erro aparece sozinho (sem inserir o cartão). "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 60; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a opção Configuração; 5. Depois Apagar memória; 6. Insira a Senha do Técnico; 7. A tela ficará verde confirmando a ação, novamente; "
                "8. Selecione a Função 38; 9. Depois Inicialização; 10. A tela ficará verde confirmando a ação, novamente; 11. Então, faça uma venda teste."
            ),
            "adq 1-19": (
                "Erro ADQ 1-19: erro de conexão. "
                "Quando ocorre: No processamento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 59; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a Função 25; 5. A tela ficará verde confirmando a ação, novamente; 6. Insira a Senha do Operador; "
                "7. A tela ficará verde confirmando a ação, novamente; 8. Selecione a Função 46; 9. A tela ficará verde confirmando a ação, novamente; "
                "10. Faça uma venda teste."
            ),
            "adq 1-06": (
                "Erro ADQ 1-06: maquininha não configurada. "
                "Quando ocorre: Ao tentar utilizar a maquininha. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 59; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a Função 25; 5. A tela ficará verde confirmando a ação, novamente; 6. Insira a Senha do Operador; "
                "7. A tela ficará verde confirmando a ação, novamente; 8. Selecione a Função 46; 9. A tela ficará verde confirmando a ação, novamente; "
                "10. Faça uma venda teste."
            ),
            "adq 1-87": (
                "Erro ADQ 1-87: erro com o registro do CHIP. "
                "Quando ocorre: No momento da transação. "
                "Solução: 1. Confirme se o CHIP está devidamente inserido no terminal; 2. Clique na tecla de Função; 3. Insira o número 25; "
                "4. A tela ficará verde confirmando a ação; 5. Insira a Senha do Lojista; 6. Selecione a Função 46; 7. A tela ficará verde confirmando a ação; "
                "8. Selecione a Função 90; 9. A tela ficará verde confirmando a ação, novamente; 10. Faça uma venda teste."
            ),
            "nfc": (
                "Erro na leitora NFC: erro na realização de vendas por aproximação. "
                "Quando ocorre: Ao aproximar o cartão. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 82; 3. A tela ficará verde confirmando a ação; "
                "4. Insira a Senha do Operador; 5. Faça o teste do teclado; 6. Em seguida o teste do cartão; 7. Selecione a Função 38; "
                "8. A tela ficará verde confirmando a ação, novamente; 9. Selecione a opção Inicialização; 10. A tela ficará verde confirmando a ação, novamente; "
                "11. E faça uma venda teste."
            ),
            "adq 1-18": (
                "Erro ADQ 1-18: erro de comunicação. "
                "Quando ocorre: Maquininha com sinal fraco e não conclui a transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 25; 3. A tela ficará verde confirmando a ação; "
                "4. Insira a Senha do Operador; 5. A tela ficará verde confirmando a ação, novamente; 6. Selecione a Função 46; "
                "7. A tela ficará verde confirmando a ação, novamente; 8. E faça uma venda teste."
            ),
            "adq 1-84": (
                "Erro ADQ 1-84: problema de conexão. "
                "Quando ocorre: No processamento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 59; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a Função 25; 5. A tela ficará verde confirmando a ação, novamente; 6. Insira a Senha do Operador; "
                "7. A tela ficará verde confirmando a ação, novamente; 8. Selecione a Função 46; 9. A tela ficará verde confirmando a ação, novamente; "
                "10. Faça uma venda teste."
            ),
            "adq 1-85": (
                "Erro ADQ 1-85: problema de comunicação com a operadora. "
                "Quando ocorre: No processamento da transação. "
                "Solução: 1. Clique na tecla de Função; 2. Insira o número 59; 3. A tela ficará verde confirmando a ação; "
                "4. Selecione a Função 25; 5. A tela ficará verde confirmando a ação, novamente; 6. Insira a Senha do Operador; "
                "7. A tela ficará verde confirmando a ação, novamente; 8. Selecione a Função 46; 9. A tela ficará verde confirmando a ação, novamente; "
                "10. Faça uma venda teste."
            ),
        }

        if "habilitar o recebimento de vendas via pix" in query and "aplicativo" in query:
            return (
                "Para habilitar o recebimento de vendas via Pix no aplicativo Getnet Brasil: "
                "1) abra o aplicativo Getnet Brasil; 2) faça login; 3) acesse o menu de serviços; "
                "4) selecione Pix; 5) ative a opção de recebimento de vendas via Pix; 6) confirme a "
                "solicitação e mantenha a conta bancária vinculada para receber os pagamentos."
            )

        if "pix pelo portal" in query or "habilitar o pix pelo portal" in query:
            return (
                "Para habilitar o Pix pelo portal, acesse o Portal Getnet com login e senha, vá em “Vendas com Pix”, "
                "clique em “Habilitar Venda com Pix”, confirme a solicitação, aceite os termos e selecione o domicílio bancário. "
                "Depois, confirme a senha do login e acompanhe o pedido em “Produtos e Serviços” / “Meus pedidos”."
            )

        if "desabilitar" in query and "pix" in query and "aplicativo" in query:
            return (
                "Para desabilitar o recebimento de vendas via Pix no aplicativo Getnet Brasil: "
                "1) faça login; 2) entre em “Serviços”; 3) escolha “Pix”; 4) localize a conta habilitada; "
                "5) toque nos três pontinhos ao lado da conta; 6) escolha a opção para desabilitar o Pix e confirme."
            )

        if ("status" in query and "venda" in query) or "status das minhas vendas" in query:
            return (
                "Os possíveis status das suas vendas são: 1) Pré-Autorizada; 2) Autorizada; 3) Negada; "
                "4) Desfeita; 5) Estornada; 6) Cancelada; 7) Cancelada Parcial. "
                "Para vendas com Pix, os status são: Qr Code Criado, Qr Code Expirado, Paga, Negada, Enviada ao banco e Falha no repasse."
            )

        if "cadastro" in query or "cadastrar" in query:
            if "pix" in query or "chave" in query:
                return (
                    "Para cadastrar uma chave Pix na sua Get Conta, acesse o Aplicativo Getnet Brasil, vá em Conta > Pix > Minhas Chaves e selecione Cadastrar chave."
                )
            if "negocio" in query or "empresa" in query or "meu negócio" in query or "meu comercio" in query:
                return (
                    "No corpus atual da base Getnet, não há um artigo específico para o cadastro inicial de um negócio completo. "
                    "O que a documentação disponível confirma é que a ativação de produtos e serviços é feita pelos canais digitais da Getnet e, quando o assunto for Pix, o processo é feito em Conta > Pix > Minhas Chaves. "
                    "Se o objetivo for abrir um cadastro novo, a forma segura é usar os canais oficiais da Getnet e confirmar o fluxo dentro do portal/aplicativo do cliente."
                )

        if "biometr" in query and "pix" in query:
            return (
                "O pagamento com autenticação biométrica acontece em dois momentos: na vinculação inicial, o cliente vincula a conta ao app ou ao site, gera as chaves e define biometria ou PIN; nas compras seguintes, o pagamento é iniciado no app ou site, o cliente não precisa abrir o banco, a autenticação biométrica acontece localmente e o banco valida a transação em tempo real via Pix, com confirmação imediata."
            )

        if "get tap" in query and "pix" in query and ("habilitar" in query or "vender" in query):
            return (
                "Para habilitar e vender via Pix usando o Get Tap, primeiro acesse o aplicativo Getnet Brasil e faça login; "
                "entre em “Serviços”, selecione “Venda com Pix” e clique em “Habilitar”; escolha o banco para vincular a conta; "
                "com o Pix habilitado, abra o Get Tap, selecione a opção de venda e escolha Pix por QR Code ou aproximação."
            )

        if "qr code" in query and "pix" in query:
            for title in titles:
                if "vender via pix" in title or "venda com pix" in title or "pix na maquininha" in title:
                    return (
                        "Para vender via Pix por QR Code na maquininha: 1) inicie a máquina e selecione “Pagamento”; 2) digite o valor e prossiga; 3) escolha a opção Pix; 4) quando aparecer o QR Code, peça para o cliente ler o código no app bancário ou carteira digital; 5) finalize a transação e aguarde a confirmação da venda."
                    )

        if "plugin" in query or "plugins" in query:
            if any(term in query for term in ("vtex", "magento", "shopify")) or any(term in " ".join(titles) for term in plugin_names):
                return (
                    "A Getnet trabalha com plugins digitais como VTEX, MAGENTO e Shopify. As integrações incluem API V1 e API V2, além de funcionalidades como crédito à vista e parcelado, boleto, Pix, antifraude, cancelamento e estorno, softdescriptor e confirmação tardia."
                )

        if "maquininha" in query and "erro" in query:
            for code, text in error_map.items():
                if code in query:
                    return text
            return "O erro de maquininha pode estar relacionado a integração, comunicação, leitura ou configuração do aparelho. Verifique a tela da maquininha, a conexão e os dados de rede antes de prosseguir."

        return None

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
        query = message.lower().strip()

        if "configurar" in query and "wi" in query and "maquininha" in query:
            return {
                "agent": "knowledge",
                "response": (
                    "Na base de conhecimento atual da Getnet, não há um artigo específico com o passo a passo exato de configuração de Wi-Fi para cada modelo de maquininha. "
                    "O que a documentação confirma é que as maquininhas Getnet podem operar com conexão de internet e existem modelos com suporte a Wi-Fi, wifi e 3G/4G, e o diagnóstico correto deve ser feito com a rede, sinal e configuração do aparelho antes de qualquer teste de venda. "
                    "Se a sua dúvida for sobre conexão sem internet, verifique a rede, o sinal e a autenticação do Wi-Fi do ponto de venda e, se necessário, consulte o atendimento oficial da Getnet para o modelo da sua maquininha."
                ),
                "sources": [],
                "source_sections": {},
            }

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
                "source_sections": {},
            }

        direct_answer = self._direct_answer(message, sources)
        if direct_answer:
            return {
                "agent": "knowledge",
                "response": direct_answer,
                "sources": [source["title"] for source in sources],
                "source_sections": self._group_sources_by_section(sources),
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
            "source_sections": self._group_sources_by_section(sources),
        }
# 🔥 F.O.G.O. – Ferramenta Onisciente de Gestão e Operações

Projeto do **Desafio DSIN – Protocolo Prometeu (Etapa Bônus)**. O F.O.G.O. é uma central de operações para o trânsito e a segurança da cidade: cadastra equipamentos IoT e agentes, mostra em tempo real o que está acontecendo e prevê onde podem surgir problemas.

> Os dados e a telemetria deste projeto são **simulados** (uma cidade fictícia gerada automaticamente).

## ✨ O que o sistema faz

**1. Inventário**
- Cadastro de equipamentos com 12 tipos (radares, câmera, balança, cancela, totem, patinete, viatura, moto de agente etc.). Cada tipo tem seus próprios campos.
- Cadastro de agentes (agente de trânsito, guarda municipal, policial militar), com busca por **nome ou matrícula**.
- Localização completa (CEP, rua, referência, bairro, cidade/UF, coordenadas) e controle de manutenção (imediata ou agendada).

**2. Central de Operações**
- Mapa com **ícone por tipo de equipamento**; contorno na cor da situação (tracejado = fora de operação).
- Anel laranja = manutenção imediata, vencida ou em até 7 dias. Anel vermelho = equipamento **sem sinal**.
- Indicadores (equipamentos, operacionais, indisponíveis, disponibilidade, sem sinal, agentes ativos).
- Filtros por tipo, situação, bairro e **órgão responsável**, e busca por série, rua ou bairro.
- **Visão por região**: cada bairro aparece como normal, atenção ou crítico, com os motivos.
- **Telemetria**: equipamento que fica mais de 15 minutos sem enviar sinal vira alerta.
- Cadastro pela própria interface, com formulário que muda conforme o tipo escolhido.

**3. Cidade Preditiva**
- Risco de 0 a 100 por equipamento, sempre com os **motivos** explicados.
- Índice de risco por bairro, com tendência (30 dias contra os 30 anteriores).
- Mapa de calor por dia da semana e faixa de 4 horas.
- Previsão de eventos para os próximos 7 dias, por bairro.
- Detecção de comportamento fora do padrão (teste de Poisson).
- Recomendações de reforço de agentes e briefing em texto.
- **Validação com dados do passado** (backtesting), para mostrar se o método acerta mais que o acaso.

## 🚀 Como rodar

Requisitos: **Python 3.10 ou superior** e internet (para carregar o mapa).
```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Abra **http://localhost:8000** (interface) ou **http://localhost:8000/docs** (documentação da API).

Na primeira execução o banco `fogo.db` é criado com dados fictícios: 176 equipamentos, 36 agentes e cerca de 700 ocorrências de 6 meses. Para recomeçar, apague o arquivo `fogo.db`.

## 🧪 Testes

Não precisa instalar nada:

```bash
python -m unittest discover -s tests -v
```

São 53 testes: validação e cadastro, riscos, anomalias, mapa de calor, validação sem vazamento do futuro, telemetria, regiões, acessibilidade e contraste de cores.

## 🧠 Como as previsões funcionam

Estatística simples e explicável, sem caixa-preta.

- **Risco do equipamento (0 a 100):** soma de fatores com teto: tempo sem manutenção (até 30), manutenção agendada vencida (15), ocorrências nos últimos 90 dias (até 30) e 30 dias (até 10), situação atual (até 20) e histórico do bairro (até 10).
  Níveis: baixo (< 25), médio (25–44), alto (45–64) e crítico (65 ou mais).
- **Gravidade das ocorrências:** furto 2, vandalismo 1,5, falha 1, alerta 0,3.
- **Fora do padrão:** compara os últimos 14 dias com o histórico do próprio equipamento (Poisson, p < 0,02, pelo menos 3 ocorrências).
- **Validação:** treina só com dados anteriores a 30 dias atrás e confere nos 30 dias seguintes. Mede quanto das ocorrências caiu nos 20% de equipamentos apontados (o acaso daria 20%).

## 🏙️ Como cada região é classificada

| Situação | Quando acontece |
|---|---|
| **Crítica** | Disponibilidade abaixo de 75%, ou 2 ou mais equipamentos sem sinal, ou 20% ou mais em manutenção imediata |
| **Atenção** | Disponibilidade abaixo de 90%, ou algum equipamento sem sinal, com manutenção imediata ou vencida, ou nenhum agente em atividade |
| **Normal** | Nenhuma das anteriores |

As metas ficam em `app/operacao.py` e podem ser ajustadas.

## 📡 Telemetria

Cada equipamento envia sinal e bateria. Um simulador interno gera essas leituras a cada 20 segundos (desligue com a variável `FOGO_SIMULAR_TELEMETRIA=0`). Equipamento calado por mais de 15 minutos vira alerta, porque um equipamento quebrado não avisa que quebrou. A rota `POST /api/telemetria` já aceita leituras reais de dispositivos IoT.

Para a demonstração, use os botões "Simular equipamento sem sinal" e "Normalizar todos os sinais" no painel lateral.

## 🗂️ Estrutura

```
fogo/
├── app/
│   ├── catalogo.py     # tipos de equipamento, campos próprios e validação
│   ├── db.py           # tabelas do SQLite
│   ├── repo.py         # cadastro (criar, ler, atualizar, apagar)
│   ├── seed.py         # gera a cidade fictícia e o histórico
│   ├── telemetria.py   # leituras, alerta de "sem sinal" e simulador
│   ├── operacao.py     # classificação das regiões
│   ├── predict.py      # riscos, mapa de calor, previsões e validação
│   ├── main.py         # rotas da API
│   └── static/index.html  # interface (mapa, regiões, previsões, cadastro)
├── tests/              # testes automáticos
└── requirements.txt
```

## 🔌 API

| Método | Rota | Para quê |
|---|---|---|
| GET | `/api/tipos` | tipos, campos próprios e situações |
| GET/POST | `/api/equipamentos` | listar (com filtros) / cadastrar |
| GET/PATCH/DELETE | `/api/equipamentos/{id}` | consultar / atualizar / excluir |
| GET/POST | `/api/agentes` | listar (com filtros) / cadastrar |
| GET/PATCH/DELETE | `/api/agentes/{id}` | consultar / atualizar / excluir |
| GET | `/api/regioes` | situação de cada bairro |
| GET | `/api/telemetria/resumo` | equipamentos sem sinal |
| POST | `/api/telemetria` | receber leitura de um equipamento |
| GET | `/api/previsoes` | todas as previsões |
| POST/DELETE | `/api/demo/rajada` | simular / limpar falhas (demonstração) |
| POST | `/api/demo/telemetria` | simular / normalizar sem sinal (demonstração) |

Erros: `422` validação, `404` não encontrado, `409` série ou matrícula duplicada.

## ♿ Acessibilidade

Contraste de cores no padrão WCAG AA (conferido por teste automático), navegação por teclado, abas com setas, link "Pular para o conteúdo", rótulos em todos os campos, alternativa em texto ao mapa, cursor do mapa visível sobre qualquer fundo e respeito à opção "reduzir movimento". Não foi testado com leitor de tela real.

## ⚠️ Decisões e limitações

- Atributos por tipo ficam em JSON validado pelo catálogo: novo tipo de equipamento é só editar `catalogo.py`.
- Regras, banco (SQLite) e previsões usam apenas a biblioteca padrão do Python. O FastAPI só expõe as rotas.
- **Os dados são simulados**, com padrões plantados de propósito. Por isso a validação tende a ser otimista. Com dados reais o acerto seria menor.
- Só a última leitura de telemetria de cada equipamento é guardada, sem histórico.
- Um bairro com mais registros pode refletir mais fiscalização, e não necessariamente mais problemas. O sistema aponta risco, não certeza.
- Próximos passos: telemetria real, histórico de leituras e de mudanças de situação, importação de CSV e autenticação.

## 🤖 IA utilizada

Claude (Anthropic), em conversa no claude.ai, auxiliou na estrutura do projeto, no código, nos testes e na documentação.

## 🛠️ Tecnologias

Python · FastAPI · SQLite · Leaflet · OpenStreetMap · HTML, CSS e JavaScript

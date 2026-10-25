# F.O.G.O. – Ferramenta Onisciente de Gestão e Operações

Projeto do Desafio DSIN (Etapa Bônus), com as **três partes** do enunciado:

1. **Inventário** – cadastro de equipamentos (12 tipos, cada um com suas características) e agentes.
2. **Central de Operações** – mapa, indicadores, filtros, alertas e busca de equipamentos/agentes.
3. **Cidade Preditiva** – riscos, mapa de calor, previsão de 7 dias, anomalias, recomendações e validação.

## Como rodar
Windows: dê dois cliques em `iniciar.bat` (ou rode os comandos abaixo). Linux/Mac: `./iniciar.sh`.
```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```
Abra **http://localhost:8000** (interface) ou http://localhost:8000/docs (API).
Na primeira execução o banco `fogo.db` é criado e populado com uma cidade fictícia
(176 equipamentos, 36 agentes, ~700 ocorrências de 6 meses). Para recomeçar, apague `fogo.db`.
Requer Python 3.10+ e internet para carregar o mapa (Leaflet/OpenStreetMap).

## Testes (sem instalar nada)
```bash
python -m unittest discover -s tests -v
```
53 testes: validação e cadastro, riscos, anomalias, mapa de calor, validação sem vazamento do futuro, telemetria, regiões, acessibilidade e contraste.

## O que a interface faz
- **Operação em tempo real:** mapa com **ícone por tipo de equipamento** (e sigla da função nos agentes), contorno na cor da situação
  (tracejado = fora de operação) ou **cor por risco previsto**, KPIs (inclui “Sem sinal”), filtros (tipo, situação, bairro e
  **órgão responsável**), alertas clicáveis e detalhes ao clicar. **Anel laranja tracejado** = manutenção imediata, vencida ou em até 7 dias;
  **anel vermelho pontilhado** = equipamento sem sinal.
- **Regiões:** visão consolidada por bairro (normal / atenção / crítica) com disponibilidade, manutenção imediata, sem sinal,
  agentes ativos e o motivo de cada classificação. As regras ficam em `app/operacao.py` e aparecem na própria tela.
- **Cadastro:** formulários de equipamento (campos próprios mudam conforme o tipo), agente e atualização de situação,
  com coordenadas pelo centro do mapa ou clicando nele; erros aparecem na tela.
- **Telemetria:** cada equipamento envia sinal/bateria (simulado, tarefa de fundo a cada 20 s); quem fica mais de 15 min
  calado vira alerta “sem sinal”. Botões de demonstração no painel lateral.
- **Busca:** campo geral (série, rua, bairro…) e campo próprio de agentes por **nome ou matrícula**
  (sem diferenciar acentos/maiúsculas; Enter localiza no mapa), além de filtro por função e situação.
- **Previsões:** briefing do PROMETHEUS em texto, risco por bairro com tendência e agentes ativos,
  próximos 7 dias, mapa de calor dia × faixa de 4 h (cidade toda ou por bairro), recomendações de reforço,
  ranking de equipamentos com os **motivos** de cada risco, anomalias e a validação do método.
- **Demo:** o botão “Simular rajada de falhas” injeta falhas recentes (marcadas `[DEMO]`) num equipamento
  para mostrar a detecção de comportamento fora do padrão; “Limpar demo” remove.

## Como as previsões funcionam (`app/predict.py`)
Estatística simples e explicável, sem caixa-preta.
- **Risco do equipamento (0–100)** = tempo sem manutenção (até 30) + manutenção agendada vencida (15)
  + ocorrências nos últimos 90 dias (até 30) + ocorrências nos últimos 30 dias (até 10) + situação atual (até 20)
  + histórico do bairro (até 10). Níveis: baixo < 25 ≤ médio < 45 ≤ alto < 65 ≤ crítico.
- **Gravidade das ocorrências:** furto 2, vandalismo 1,5, falha 1, alerta 0,3.
- **Risco do bairro:** ocorrências ponderadas por equipamento instalado, relativo ao pior bairro; tendência = 30 dias vs 30 anteriores.
- **Próximos 7 dias:** ritmo do bairro (mistura de 180 e 60 dias) × fator do dia da semana.
- **Fora do padrão:** teste de Poisson comparando os últimos 14 dias com o histórico do próprio equipamento (p < 0,02, ≥ 3 ocorrências).
- **Validação (backtesting):** treina só com dados anteriores a 30 dias atrás e confere nos 30 dias seguintes.
  Mede quanto das ocorrências caiu nos 20% de equipamentos apontados (acaso = 20%) e quantos bairros críticos acertou.

## Acessibilidade, contraste e cursor do mapa
- **Contraste (WCAG AA):** todas as cores vêm de variáveis no topo de `index.html`; o teste `tests/test_acessibilidade.py`
  mede cada par texto/fundo (4,5:1 para texto, 3:1 para foco e bordas) e falha se alguém reduzir o contraste.
  Corrigidos: aba ativa, selos de risco (alto/médio/baixo), tendência em verde e texto do mapa de calor (agora sempre escuro).
  Conferido também no navegador, com os estilos renderizados de verdade: 0 falhas em 1.202 textos nas duas abas.
- **Cursor do mapa:** cruz com contorno branco e centro escuro (`--cursor-mapa`), visível em mapa claro, colorido ou escuro,
  inclusive durante o arrasto. Os marcadores têm cursor de “mão” e crescem ao passar o mouse.
- **Teclado e leitor de tela:** link “Pular para o conteúdo”; abas com setas; foco sempre visível (anel amarelo no painel
  escuro, azul no claro); alertas, agentes e equipamentos são botões; todos os campos têm rótulo; tabelas com legenda e
  cabeçalhos; região viva anuncia “Mostrando N equipamentos…”.
- **Alternativa ao mapa:** “Lista de equipamentos (alternativa em texto ao mapa)”, com situação e risco escritos.
  Cor nunca é a única pista: marcadores fora de operação têm contorno escuro, e valores e níveis aparecem escritos.
- **Outros:** respeita “reduzir movimento”; sem rolagem horizontal até 320 px (tabelas largas rolam dentro de si);
  alvos de toque ≥ 24 px; texto em unidades relativas (acompanha o zoom do navegador); a atualização automática pode ser
  pausada e não rouba o foco de quem está usando o teclado.
- **Limites (honestidade):** não foi testado com leitor de tela real (NVDA, JAWS, VoiceOver) nem com ferramenta
  automática como axe/Lighthouse; os marcadores de bolinha do Leaflet não recebem foco de teclado, por isso existe a lista em texto.

## API
| Método | Rota | Para quê |
|---|---|---|
| GET | `/api/tipos` | tipos, campos próprios, situações (monta formulários) |
| GET/POST | `/api/equipamentos` | listar (filtros `tipo, situacao, bairro, orgao, manutencao, q`) / cadastrar |
| GET/PATCH/DELETE | `/api/equipamentos/{id}` | consultar / atualizar parcialmente / excluir |
| GET/POST | `/api/agentes` | listar (filtros `funcao, situacao, orgao, q`) / cadastrar |
| GET/PATCH/DELETE | `/api/agentes/{id}` | idem |
| GET | `/api/previsoes` | todas as previsões da Parte 3 |
| GET | `/api/regioes` | visão consolidada por bairro (normal/atenção/crítica) |
| GET/POST | `/api/telemetria/resumo`, `/api/telemetria` | equipamentos sem sinal / receber leitura |
| POST | `/api/demo/telemetria` | `{"acao":"silenciar"\|"normalizar"}` (demonstração) |
| POST/DELETE | `/api/demo/rajada` | simular / limpar rajada de falhas (demonstração) |

Erros: `422` validação (`{"erros": [...]}`), `404` não encontrado, `409` série/matrícula duplicada.

## Decisões e limitações (honestidade)
- Atributos por tipo ficam em JSON validado por um catálogo (`app/catalogo.py`): novo tipo = editar só o catálogo.
- Só biblioteca padrão nas regras, no banco (SQLite) e nas previsões; FastAPI apenas expõe as rotas.
- **Os dados são simulados**, com padrões plantados de propósito (bairros de risco, manutenção atrasada, furtos à noite).
  Por isso a validação tende a ir bem; com dados reais o acerto seria menor.
- A telemetria é simulada (um simulador interno gera leituras; `FOGO_SIMULAR_TELEMETRIA=0` desliga). A tabela e a rota
  `POST /api/telemetria` já aceitam leituras reais de IoT. A página recarrega a cada 15 s.
- Só a última leitura de cada equipamento é guardada (sem histórico de telemetria).
- Com poucos eventos por bairro, as faixas de horário têm incerteza; cada recomendação informa a base usada.
- Próximos passos: telemetria real, histórico de mudanças de situação, importação CSV, autenticação.

## IA utilizada
Claude (Anthropic, modelo Claude Sonnet 5.5, via claude.ai) auxiliou na estrutura, na primeira versão do código,
nos testes e na documentação.
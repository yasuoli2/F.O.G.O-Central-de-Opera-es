"""Parte 3 – Cidade Preditiva.

Estatística simples e EXPLICÁVEL (só biblioteca padrão). Cada número devolvido traz o
motivo, para o gestor entender por que o sistema recomenda aquilo.

O que é previsto
  1. Risco de cada equipamento (0-100) com os motivos.
  2. Risco de cada bairro e sua tendência (últimos 30 dias x 30 dias anteriores).
  3. Onde/quando as ocorrências se concentram (mapa de calor dia da semana x faixa de 4 h).
  4. Número esperado de eventos (ocorrências e alertas) por bairro nos próximos 7 dias.
  5. Comportamento fora do padrão (rajada de ocorrências) por teste estatístico de Poisson.
  6. Recomendações de reforço e um briefing em texto.
  7. Validação (backtesting): o método é treinado só com o passado e conferido no último mês.

Gravidade das ocorrências (PESO_EVENTO): furto 2, vandalismo 1,5, falha 1, alerta 0,3.
Eventos de "manutenção" não são ocorrências e não entram na conta.
"""
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

PESO_EVENTO = {"falha": 1.0, "furto": 2.0, "vandalismo": 1.5, "alerta": 0.3}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
DIAS_PL = ["segundas", "terças", "quartas", "quintas", "sextas", "sábados", "domingos"]
DIAS_ART = ["as", "as", "as", "as", "as", "os", "os"]
FAIXAS = [(0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24)]
JANELA_DIAS = 180
SEM_PREVISAO = ("nao_instalado", "furtado", "desativado")   # nada a prever neles
DEMO_MARCA = "[DEMO]"


def rotulo_faixa(i):
    a, b = FAIXAS[i]
    return f"{a:02d}h–{b % 24:02d}h"


def nivel_risco(pontos):
    if pontos >= 65:
        return "critico"
    if pontos >= 45:
        return "alto"
    if pontos >= 25:
        return "medio"
    return "baixo"


def _pct(x):
    return f"{round(100 * x)}%"


def _num(x):
    return f"{x:.1f}".replace(".", ",")


# --------------------------------------------------------------------- dados
def _carregar(conn, hoje):
    eqs = [dict(r) for r in conn.execute(
        """SELECT id, tipo, numero_serie, marca, modelo, situacao, manutencao_tipo,
                  proxima_manutencao, ultima_manutencao, data_instalacao, bairro, latitude, longitude
           FROM equipamento""")]
    evs = []
    for r in conn.execute("SELECT equipamento_id, tipo, ocorrido_em FROM evento"):
        peso = PESO_EVENTO.get(r["tipo"])
        if not peso:
            continue
        try:
            dt = datetime.fromisoformat(r["ocorrido_em"])
        except ValueError:
            continue
        if dt.date() <= hoje:
            evs.append((r["equipamento_id"], dt, peso))
    ags = [dict(r) for r in conn.execute(
        "SELECT id, nome, situacao, latitude, longitude FROM agente")]
    return eqs, evs, ags


def _data(txt):
    try:
        return date.fromisoformat(txt) if txt else None
    except ValueError:
        return None


def _taxa_bairros(eqs, evs, ini, fim):
    """Gravidade das ocorrências por equipamento instalado, em cada bairro, no período [ini, fim)."""
    bairro_de = {e["id"]: e["bairro"] for e in eqs}
    n = defaultdict(int)
    for e in eqs:
        if e["situacao"] != "nao_instalado":
            n[e["bairro"]] += 1
    soma = defaultdict(float)
    for eid, dt, w in evs:
        if ini <= dt.date() < fim and eid in bairro_de:
            soma[bairro_de[eid]] += w
    return {b: soma[b] / n[b] for b in n if n[b]}


def _indice(taxas):
    """Converte taxas em índice 0-100 relativo ao bairro mais crítico."""
    topo = max(taxas.values(), default=0)
    return {b: (100 * t / topo if topo else 0.0) for b, t in taxas.items()}


# ----------------------------------------------------------- risco: equipamento
def risco_equipamentos(eqs, evs, hoje, idx_bairro):
    por_eq = defaultdict(list)
    for eid, dt, w in evs:
        por_eq[eid].append((dt.date(), w))
    saida = []
    for e in eqs:
        if e["situacao"] in SEM_PREVISAO:
            continue
        fatores, motivos = {}, []
        base = _data(e["ultima_manutencao"]) or _data(e["data_instalacao"])
        dias_sem = (hoje - base).days if base else None
        fatores["manutencao"] = 30 * min(dias_sem / 365, 1) if dias_sem is not None else 0.0
        if dias_sem is not None and dias_sem >= 180:
            motivos.append(f"Última manutenção há {dias_sem} dias")
        prox = _data(e["proxima_manutencao"])
        fatores["vencida"] = 0.0
        if e["manutencao_tipo"] == "agendada" and prox and prox < hoje:
            fatores["vencida"] = 15.0
            motivos.append(f"Manutenção agendada vencida há {(hoje - prox).days} dias")
        n90 = w90 = n30 = w30 = 0
        for d, w in por_eq.get(e["id"], []):
            idade = (hoje - d).days
            if idade < 90:
                n90 += 1
                w90 += w
            if idade < 30:
                n30 += 1
                w30 += w
        fatores["historico"] = 30 * min(w90 / 6, 1)
        fatores["recente"] = 10 * min(w30 / 3, 1)
        if n90:
            motivos.append(f"{n90} ocorrência(s) nos últimos 90 dias")
        if n30 >= 2:
            motivos.append(f"{n30} ocorrências só nos últimos 30 dias")
        fatores["situacao"] = {"mau_funcionamento": 20.0, "em_manutencao": 8.0}.get(e["situacao"], 0.0)
        if e["situacao"] == "mau_funcionamento":
            motivos.append("Já está em mau funcionamento")
        idx = idx_bairro.get(e["bairro"], 0.0)
        fatores["bairro"] = 10 * idx / 100
        if idx >= 70:
            motivos.append(f"Bairro {e['bairro']} com histórico de ocorrências elevado")
        pontos = min(100.0, sum(fatores.values()))
        saida.append({
            "id": e["id"], "tipo": e["tipo"], "numero_serie": e["numero_serie"], "bairro": e["bairro"],
            "situacao": e["situacao"], "risco": round(pontos, 1), "nivel": nivel_risco(pontos),
            "motivos": motivos or ["Sem fatores de risco relevantes"],
            "fatores": {k: round(v, 1) for k, v in fatores.items()},
        })
    saida.sort(key=lambda x: -x["risco"])
    return saida


# --------------------------------------------------------------- risco: bairros
def _bairro_do_agente(a, centros):
    if a["latitude"] is None or a["longitude"] is None or not centros:
        return None
    return min(centros, key=lambda b: (centros[b][0] - a["latitude"]) ** 2 + (centros[b][1] - a["longitude"]) ** 2)


def risco_bairros(eqs, evs, ags, hoje):
    taxa = _taxa_bairros(eqs, evs, hoje - timedelta(days=JANELA_DIAS), hoje + timedelta(days=1))
    idx = _indice(taxa)
    t30 = _taxa_bairros(eqs, evs, hoje - timedelta(days=30), hoje + timedelta(days=1))
    t60 = _taxa_bairros(eqs, evs, hoje - timedelta(days=60), hoje - timedelta(days=30))
    pos = defaultdict(list)
    for e in eqs:
        pos[e["bairro"]].append((e["latitude"], e["longitude"]))
    centros = {b: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)) for b, ps in pos.items()}
    ativos = defaultdict(int)
    for a in ags:
        if a["situacao"] == "em_atividade":
            b = _bairro_do_agente(a, centros)
            if b:
                ativos[b] += 1
    saida = []
    for b in taxa:
        ant, atual = t60.get(b, 0.0), t30.get(b, 0.0)
        variacao = round(100 * (atual - ant) / ant) if ant > 0 else None
        saida.append({"bairro": b, "indice": round(idx[b], 1), "nivel": nivel_risco(idx[b] * 0.8),
                      "equipamentos": sum(1 for e in eqs if e["bairro"] == b and e["situacao"] != "nao_instalado"),
                      "tendencia_pct": variacao, "agentes_ativos": ativos.get(b, 0)})
    saida.sort(key=lambda x: -x["indice"])
    return saida


# ------------------------------------------------------------ mapa de calor
def mapa_calor(eqs, evs, hoje):
    bairro_de = {e["id"]: e["bairro"] for e in eqs}
    ini = hoje - timedelta(days=JANELA_DIAS)
    mats = defaultdict(lambda: [[0.0] * len(FAIXAS) for _ in range(7)])
    for eid, dt, w in evs:
        if dt.date() < ini or eid not in bairro_de:
            continue
        f = dt.hour // 4
        mats["Cidade toda"][dt.weekday()][f] += w
        mats[bairro_de[eid]][dt.weekday()][f] += w
    mats.setdefault("Cidade toda", [[0.0] * len(FAIXAS) for _ in range(7)])
    return {b: [[round(v, 1) for v in lin] for lin in m] for b, m in mats.items()}


def recomendacao_bairro(bairro, mat, n_ev=0):
    total = sum(sum(lin) for lin in mat)
    if total < 5:
        return None
    por_faixa = [sum(mat[d][f] for d in range(7)) for f in range(len(FAIXAS))]
    por_dia = [sum(lin) for lin in mat]
    f = max(range(len(FAIXAS)), key=lambda i: por_faixa[i])
    d = max(range(7), key=lambda i: por_dia[i])
    return {
        "faixa": rotulo_faixa(f), "dia": DIAS[d],
        "pct_faixa": round(por_faixa[f] / total, 3), "pct_dia": round(por_dia[d] / total, 3),
        "texto": (f"Reforçar {bairro} entre {rotulo_faixa(f)}: essa faixa concentra {_pct(por_faixa[f] / total)} "
                  f"das ocorrências do bairro (seriam {_pct(1 / len(FAIXAS))} se fossem uniformes). "
                  f"O dia mais crítico são {DIAS_ART[d]} {DIAS_PL[d]} ({_pct(por_dia[d] / total)} contra {_pct(1 / 7)} esperado). "
                  f"Base: {n_ev} ocorrências em {JANELA_DIAS} dias."),
    }


# ------------------------------------------------------- previsão: 7 dias
def prever_proximos_dias(eqs, evs, hoje, dias=7):
    """Nº esperado de eventos por bairro e dia = ritmo do bairro (mistura de 180 e 60 dias) x fator do dia da semana."""
    bairro_de = {e["id"]: e["bairro"] for e in eqs}
    n180 = defaultdict(float)
    n60 = defaultdict(float)
    dow = [0.0] * 7
    for eid, dt, w in evs:
        b = bairro_de.get(eid)
        idade = (hoje - dt.date()).days
        if b is None or idade >= JANELA_DIAS:
            continue
        n180[b] += 1
        dow[dt.weekday()] += 1
        if idade < 60:
            n60[b] += 1
    total_dow = sum(dow)
    fator = [7 * d / total_dow if total_dow else 1.0 for d in dow]
    datas = [hoje + timedelta(days=i + 1) for i in range(dias)]
    saida = {}
    for b in {e["bairro"] for e in eqs}:
        semanal = 0.5 * (n180[b] / (JANELA_DIAS / 7)) + 0.5 * (n60[b] / (60 / 7))
        saida[b] = [round(semanal / 7 * fator[d.weekday()], 2) for d in datas]
    return {"datas": [d.isoformat() for d in datas], "dias": [DIAS[d.weekday()] for d in datas], "bairros": saida}


# ----------------------------------------------------- comportamento anômalo
def _poisson_cauda(k, lam):
    """P(X >= k) para X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    termo = math.exp(-lam)
    acum = termo
    for i in range(1, k):
        termo *= lam / i
        acum += termo
    return max(0.0, 1.0 - acum)


def anomalias(eqs, evs, hoje, janela=14, minimo=3, limiar=0.02):
    eq_de = {e["id"]: e for e in eqs}
    rec = defaultdict(int)
    ant = defaultdict(int)
    for eid, dt, _ in evs:
        idade = (hoje - dt.date()).days
        if idade < janela:
            rec[eid] += 1
        elif idade < JANELA_DIAS:
            ant[eid] += 1
    saida = []
    for eid, k in rec.items():
        e = eq_de.get(eid)
        if not e or k < minimo:
            continue
        esperado = max(ant[eid] / (JANELA_DIAS - janela) * janela, 0.3)
        p = _poisson_cauda(k, esperado)
        if p < limiar:
            saida.append({"id": eid, "tipo": e["tipo"], "numero_serie": e["numero_serie"], "bairro": e["bairro"],
                          "ocorrencias": k, "esperado": round(esperado, 1), "p_valor": round(p, 4),
                          "texto": (f"{k} ocorrências em {janela} dias; o normal para este equipamento "
                                    f"seria ≈ {_num(esperado)}.")})
    saida.sort(key=lambda x: x["p_valor"])
    return saida


# ------------------------------------------------------- validação (backtest)
def _spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        ordem = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[ordem[j + 1]] == v[ordem[i]]:
                j += 1
            for k in range(i, j + 1):
                r[ordem[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 2) if den else None


def validar(eqs, evs, hoje, janela_teste=30):
    """Treina só com eventos ANTERIORES à data de corte e confere contra os dias seguintes."""
    corte = hoje - timedelta(days=janela_teste)
    treino = [x for x in evs if x[1].date() < corte]
    teste = [x for x in evs if corte <= x[1].date() <= hoje]
    base = {"data_corte": corte.isoformat(), "dias_teste": janela_teste,
            "eventos_treino": len(treino), "eventos_teste": len(teste)}
    if len(treino) < 20 or len(teste) < 5:
        return {**base, "valido": False, "motivo": "Poucos eventos para validar com segurança."}

    # 1) bairros: o ranking do passado acerta o ranking do mês seguinte?
    t_tr = _taxa_bairros(eqs, treino, corte - timedelta(days=150), corte)
    t_te = _taxa_bairros(eqs, teste, corte, hoje + timedelta(days=1))
    comuns = sorted(t_tr)
    k = min(3, len(comuns))
    topo_tr = set(sorted(comuns, key=lambda b: -t_tr[b])[:k])
    topo_te = set(sorted(comuns, key=lambda b: -t_te.get(b, 0))[:k])
    acertos = len(topo_tr & topo_te)
    aleatorio = k * k / len(comuns) if comuns else 0
    bairros = {"k": k, "acertos": acertos, "acaso_esperado": round(aleatorio, 2),
               "spearman": _spearman([t_tr[b] for b in comuns], [t_te.get(b, 0) for b in comuns]),
               "previstos": sorted(topo_tr), "reais": sorted(topo_te)}

    # 2) equipamentos: os 20% mais arriscados concentram as ocorrências do mês seguinte?
    elegiveis = [e for e in eqs if e["situacao"] != "nao_instalado"
                 and (_data(e["data_instalacao"]) is None or _data(e["data_instalacao"]) < corte)]
    score = defaultdict(float)
    for eid, dt, w in treino:
        idade = (corte - dt.date()).days
        if idade < 90:
            score[eid] += w * (2.0 if idade < 30 else 1.0)
    real = defaultdict(float)
    for eid, dt, w in teste:
        real[eid] += w
    ordem = sorted(elegiveis, key=lambda e: -score[e["id"]])
    n_topo = max(1, math.ceil(0.2 * len(ordem)))
    topo = {e["id"] for e in ordem[:n_topo]}
    total_real = sum(real[e["id"]] for e in elegiveis)
    captura = sum(real[i] for i in topo) / total_real if total_real else 0
    com_ocorr = sum(1 for e in elegiveis if real[e["id"]] > 0) / len(elegiveis) if elegiveis else 0
    prec = sum(1 for i in topo if real[i] > 0) / n_topo
    equipamentos = {"grupo": n_topo, "captura": round(captura, 3), "captura_acaso": 0.2,
                    "lift": round(captura / 0.2, 2), "precisao": round(prec, 3),
                    "precisao_acaso": round(com_ocorr, 3)}
    return {**base, "valido": True, "bairros": bairros, "equipamentos": equipamentos,
            "aviso": ("Os dados deste projeto são simulados e o padrão de risco é estável por construção; "
                      "com dados reais o acerto tende a ser menor. O valor está em o método ser verificável.")}


# ---------------------------------------------------------------- briefing
def _briefing(hoje, eqs, evs, equip, bairros, prox, anom, valid, recs):
    linhas = [f"Bom dia. Hoje é {DIAS[hoje.weekday()]}, {hoje.strftime('%d/%m/%Y')}. Avaliei o risco de {len(equip)} "
              f"equipamentos com base em {len(evs)} eventos dos últimos {JANELA_DIAS} dias."]
    crit = [e for e in equip if e["nivel"] in ("critico", "alto")]
    if crit:
        top = ", ".join(f"{e['numero_serie']} ({e['bairro']})" for e in crit[:3])
        linhas.append(f"{len(crit)} equipamento(s) com risco alto ou crítico. Os mais urgentes: {top}.")
    else:
        linhas.append("Nenhum equipamento com risco alto ou crítico agora.")
    if bairros:
        b = bairros[0]
        tend = ""
        if b["tendencia_pct"] is not None:
            tend = f" Tendência: {'alta' if b['tendencia_pct'] > 0 else 'queda'} de {abs(b['tendencia_pct'])}% frente ao mês anterior."
        linhas.append(f"Bairro mais crítico: {b['bairro']}.{tend}")
    if prox["datas"]:
        melhor = max(prox["bairros"], key=lambda k: prox["bairros"][k][0], default=None)
        if melhor:
            linhas.append(f"Para amanhã ({prox['dias'][0]}), o maior número esperado de eventos é em {melhor}.")
    if anom:
        linhas.append(f"{len(anom)} equipamento(s) com comportamento fora do padrão: {anom[0]['numero_serie']} "
                      f"({anom[0]['ocorrencias']} ocorrências em 14 dias).")
    if recs:
        linhas.append("Recomendação principal: " + recs[0]["texto"])
    if valid.get("valido"):
        e, b = valid["equipamentos"], valid["bairros"]
        linhas.append(f"Confiança: no teste com o último mês, os 20% de equipamentos mais arriscados concentraram "
                      f"{_pct(e['captura'])} das ocorrências (o acaso daria 20%) e acertei {b['acertos']} de {b['k']} "
                      f"bairros críticos. Observação: os dados atuais são simulados.")
    return linhas


# ------------------------------------------------------------- orquestração
def previsoes(conn, hoje=None):
    hoje = hoje or date.today()
    eqs, evs, ags = _carregar(conn, hoje)
    taxa = _taxa_bairros(eqs, evs, hoje - timedelta(days=JANELA_DIAS), hoje + timedelta(days=1))
    idx = _indice(taxa)
    equip = risco_equipamentos(eqs, evs, hoje, idx)
    bairros = risco_bairros(eqs, evs, ags, hoje)
    calor = mapa_calor(eqs, evs, hoje)
    bairro_de = {e["id"]: e["bairro"] for e in eqs}
    n_por_bairro = defaultdict(int)
    for eid, dt, _ in evs:
        if (hoje - dt.date()).days < JANELA_DIAS and eid in bairro_de:
            n_por_bairro[bairro_de[eid]] += 1
    recs = []
    for b in bairros:
        if b["nivel"] in ("critico", "alto") or len(recs) < 3:
            r = recomendacao_bairro(b["bairro"], calor.get(b["bairro"], []) or [[0.0] * 6] * 7, n_por_bairro.get(b["bairro"], 0))
            if r:
                r["bairro"] = b["bairro"]
                r["nivel"] = b["nivel"]
                r["agentes_ativos"] = b["agentes_ativos"]
                if b["agentes_ativos"] == 0:
                    r["texto"] += " Hoje não há agente ativo próximo a esse bairro."
                recs.append(r)
        if len(recs) >= 5:
            break
    prox = prever_proximos_dias(eqs, evs, hoje)
    anom = anomalias(eqs, evs, hoje)
    valid = validar(eqs, evs, hoje)
    niveis = defaultdict(int)
    for e in equip:
        niveis[e["nivel"]] += 1
    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "hoje": hoje.isoformat(),
        "resumo": {"equipamentos_analisados": len(equip), "ocorrencias_analisadas": len(evs),
                   "janela_dias": JANELA_DIAS, "por_nivel": {k: niveis.get(k, 0) for k in ("critico", "alto", "medio", "baixo")}},
        "briefing": _briefing(hoje, eqs, evs, equip, bairros, prox, anom, valid, recs),
        "equipamentos": equip, "bairros": bairros, "mapa_calor": calor, "faixas": [rotulo_faixa(i) for i in range(len(FAIXAS))],
        "dias_semana": DIAS, "recomendacoes": recs, "proximos_dias": prox, "anomalias": anom, "validacao": valid,
        "pesos_evento": PESO_EVENTO,
    }


# -------------------------------------------------------------------- demo
def simular_rajada(conn, equipamento_id=None, n=4, hoje=None, semente=None):
    """Para demonstração: injeta uma rajada de falhas recentes num equipamento e devolve o registro.

    Os eventos são marcados com [DEMO] e podem ser removidos por limpar_rajada()."""
    hoje = hoje or date.today()
    rng = random.Random(semente)
    if equipamento_id is None:
        linhas = conn.execute("""SELECT id FROM equipamento WHERE situacao = 'operacional'
                                 AND id NOT IN (SELECT equipamento_id FROM evento WHERE descricao LIKE ?)""",
                              (f"{DEMO_MARCA}%",)).fetchall()
        if not linhas:
            return None
        equipamento_id = rng.choice(linhas)["id"]
    eq = conn.execute("SELECT id, numero_serie, bairro FROM equipamento WHERE id = ?", (equipamento_id,)).fetchone()
    if not eq:
        return None
    for _ in range(max(1, min(int(n), 12))):
        quando = datetime.combine(hoje - timedelta(days=rng.randint(0, 3)), datetime.min.time()).replace(
            hour=rng.randint(0, 23), minute=rng.randint(0, 59))
        conn.execute("INSERT INTO evento (equipamento_id, tipo, descricao, ocorrido_em) VALUES (?,?,?,?)",
                     (eq["id"], "falha", f"{DEMO_MARCA} rajada de falhas simulada", quando.isoformat(timespec="minutes")))
    return {"equipamento_id": eq["id"], "numero_serie": eq["numero_serie"], "bairro": eq["bairro"], "eventos": int(n)}


def limpar_rajada(conn):
    cur = conn.execute("DELETE FROM evento WHERE descricao LIKE ?", (f"{DEMO_MARCA}%",))
    return cur.rowcount

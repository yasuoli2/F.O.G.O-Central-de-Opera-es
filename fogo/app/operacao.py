"""Parte 2 – visão consolidada por região: quais bairros operam normalmente e quais exigem atenção.

Responde "como está a cidade agora?" por bairro, usando só dados em tempo real (não a previsão):
disponibilidade dos equipamentos, manutenção imediata ou vencida, equipamentos sem sinal e agentes em atividade.

As METAS abaixo são decisões de gestão, não verdades universais: ajuste-as à realidade da cidade.
Só a biblioteca padrão.
"""
from collections import defaultdict
from datetime import datetime

from . import telemetria

# Metas (fáceis de mudar). O painel mostra estas mesmas regras ao usuário.
META_DISPONIBILIDADE = 0.90        # abaixo disso a região pede atenção
DISPONIBILIDADE_CRITICA = 0.75     # abaixo disso a região é crítica
SEM_SINAL_CRITICO = 2              # equipamentos calados a partir dos quais a região é crítica
IMEDIATA_CRITICA = 0.20            # fração dos equipamentos instalados com manutenção imediata (crítico)
INDISPONIVEIS = ("mau_funcionamento", "em_manutencao", "desativado", "furtado")
ORDEM = {"critico": 0, "atencao": 1, "normal": 2}


def regras():
    return {
        "meta_disponibilidade_pct": round(100 * META_DISPONIBILIDADE),
        "disponibilidade_critica_pct": round(100 * DISPONIBILIDADE_CRITICA),
        "sem_sinal_critico": SEM_SINAL_CRITICO,
        "manutencao_imediata_critica_pct": round(100 * IMEDIATA_CRITICA),
        "texto": (f"Crítica: disponibilidade abaixo de {round(100 * DISPONIBILIDADE_CRITICA)}%, ou {SEM_SINAL_CRITICO} ou mais "
                  f"equipamentos sem sinal, ou {round(100 * IMEDIATA_CRITICA)}% ou mais com manutenção imediata. "
                  f"Atenção: disponibilidade abaixo de {round(100 * META_DISPONIBILIDADE)}%, ou algum equipamento sem sinal, "
                  f"com manutenção imediata ou com manutenção vencida, ou nenhum agente em atividade na região. "
                  f"Normal: nenhuma das anteriores."),
    }


def _mais_proximo(lat, lon, centros):
    if lat is None or lon is None or not centros:
        return None
    return min(centros, key=lambda b: (centros[b][0] - lat) ** 2 + (centros[b][1] - lon) ** 2)


def regioes(conn, agora=None, limite_min=telemetria.LIMITE_SILENCIO_MIN):
    agora = agora or datetime.now()
    hoje = agora.date()
    eqs = [dict(r) for r in conn.execute(
        "SELECT id, bairro, situacao, manutencao_tipo, proxima_manutencao, latitude, longitude FROM equipamento")]
    agentes = [dict(r) for r in conn.execute("SELECT situacao, latitude, longitude FROM agente")]
    mudos = defaultdict(int)
    bairro_de = {e["id"]: e["bairro"] for e in eqs}
    for item in telemetria.resumo(conn, agora, limite_min)["itens"]:
        mudos[bairro_de.get(item["id"])] += 1

    por = defaultdict(lambda: defaultdict(int))
    pos = defaultdict(list)
    for e in eqs:
        d = por[e["bairro"]]
        pos[e["bairro"]].append((e["latitude"], e["longitude"]))
        if e["situacao"] != "nao_instalado":
            d["instalados"] += 1
            if e["situacao"] == "operacional":
                d["operacionais"] += 1
            elif e["situacao"] in INDISPONIVEIS:
                d["indisponiveis"] += 1
        if e["manutencao_tipo"] == "imediata":
            d["imediata"] += 1
        elif e["manutencao_tipo"] == "agendada" and e["proxima_manutencao"]:
            try:
                dias = (datetime.fromisoformat(e["proxima_manutencao"]).date() - hoje).days
            except ValueError:
                continue
            if dias < 0:
                d["vencida"] += 1
            elif dias <= 7:
                d["proxima"] += 1
    centros = {b: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)) for b, ps in pos.items()}
    ativos = defaultdict(int)
    for a in agentes:
        if a["situacao"] == "em_atividade":
            b = _mais_proximo(a["latitude"], a["longitude"], centros)
            if b:
                ativos[b] += 1

    saida = []
    for b, d in por.items():
        inst, op = d["instalados"], d["operacionais"]
        disp = op / inst if inst else None
        sem = mudos.get(b, 0)
        motivos, critico, atencao = [], False, False
        if disp is not None:
            if disp < DISPONIBILIDADE_CRITICA:
                critico = True
                motivos.append(f"Disponibilidade de {round(100 * disp)}%, abaixo do mínimo de {round(100 * DISPONIBILIDADE_CRITICA)}%")
            elif disp < META_DISPONIBILIDADE:
                atencao = True
                motivos.append(f"Disponibilidade de {round(100 * disp)}%, abaixo da meta de {round(100 * META_DISPONIBILIDADE)}%")
        if sem >= SEM_SINAL_CRITICO:
            critico = True
        if sem:
            atencao = True
            motivos.append(f"{sem} equipamento(s) sem sinal")
        if inst and d["imediata"] / inst >= IMEDIATA_CRITICA:
            critico = True
        if d["imediata"]:
            atencao = True
            motivos.append(f"{d['imediata']} com manutenção imediata")
        if d["vencida"]:
            atencao = True
            motivos.append(f"{d['vencida']} com manutenção vencida")
        if ativos.get(b, 0) == 0:
            atencao = True
            motivos.append("Nenhum agente em atividade na região")
        status = "critico" if critico else "atencao" if atencao else "normal"
        saida.append({"bairro": b, "status": status, "motivos": motivos or ["Operando dentro das metas"],
                      "instalados": inst, "operacionais": op, "indisponiveis": d["indisponiveis"],
                      "disponibilidade": None if disp is None else round(disp, 3),
                      "manutencao_imediata": d["imediata"], "manutencao_vencida": d["vencida"],
                      "manutencao_proxima": d["proxima"], "sem_sinal": sem, "agentes_ativos": ativos.get(b, 0)})
    saida.sort(key=lambda r: (ORDEM[r["status"]], r["disponibilidade"] if r["disponibilidade"] is not None else 2, r["bairro"]))
    resumo = {k: sum(1 for r in saida if r["status"] == k) for k in ("critico", "atencao", "normal")}
    return {"gerado_em": agora.isoformat(timespec="seconds"), "resumo": resumo, "regras": regras(), "regioes": saida}

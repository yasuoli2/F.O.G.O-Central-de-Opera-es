"""Gera uma cidade fictícia com equipamentos, agentes e histórico de ocorrências.

O histórico NÃO é uniforme de propósito: bairros, horários e equipamentos com
manutenção atrasada falham mais. Assim a Parte 3 (previsões) tem padrões reais
para descobrir, e a demonstração fica convincente.
"""
import json
import random
from datetime import date, datetime, timedelta

CIDADE_UF = "Cidade Modelo/SP"
CENTRO = (-21.80, -47.60)  # troque para a sua cidade se quiser

# nome, deslocamento lat, deslocamento lon, peso (concentração de equipamentos), risco
BAIRROS = [
    ("Centro", 0.000, 0.000, 3.0, 1.4),
    ("Vila Esperança", 0.020, -0.018, 1.5, 1.8),
    ("Jardim das Palmeiras", -0.022, 0.015, 1.2, 0.8),
    ("Distrito Industrial", -0.030, -0.030, 1.3, 1.5),
    ("Parque Universitário", 0.025, 0.024, 1.4, 0.9),
    ("Zona Norte", 0.042, -0.004, 1.0, 1.6),
    ("Bela Vista", -0.010, 0.040, 1.0, 0.7),
    ("Terminal Rodoviário", 0.008, -0.036, 1.2, 1.7),
]
RUAS = ["Av. Brasil", "Rua das Flores", "Av. Getúlio Vargas", "Rua Sete de Setembro",
        "Av. Paulista Jr.", "Rua XV de Novembro", "Rua Bahia", "Av. dos Estados", "Rua do Comércio",
        "Rua Tiradentes", "Av. Independência", "Rua Santos Dumont"]
REFERENCIAS = ["número {n}", "oposto ao número {n}", "KM {k}", "S/N", "em frente ao Mercado do Tio",
               "ao lado da praça", "próximo ao ponto de ônibus"]

# tipo: (quantidade, marcas/modelos, órgão, fator de falha)
CATALOGO = {
    "radar_velocidade": (18, [("Fiscal-Tech", "FT-200"), ("Velocitas", "V9")], "Secretaria de Mobilidade", 1.0),
    "radar_semaforo": (12, [("Fiscal-Tech", "FT-310"), ("Velocitas", "S4")], "Secretaria de Mobilidade", 1.0),
    "radar_conversao": (6, [("Velocitas", "C2")], "Secretaria de Mobilidade", 1.0),
    "camera": (40, [("VisionPro", "VP-4K"), ("SecureEye", "SE-1080"), ("OptiCam", "O-720")], "Centro de Operações", 1.2),
    "balanca": (4, [("PesoMax", "PM-80")], "Secretaria de Mobilidade", 0.8),
    "veiculo_autonomo": (5, [("AutoPatrol", "AP-1")], "Secretaria de Mobilidade", 1.5),
    "cancela": (8, [("Barreira", "B-300")], "Secretaria de Mobilidade", 0.9),
    "veiculo_transporte": (20, [("Fiat", "Cronos"), ("Honda", "CG 160"), ("Mercedes", "Sprinter")], "Transporte Público", 1.0),
    "totem_estacionamento": (12, [("ParkTotem", "PT-2")], "Secretaria de Mobilidade", 1.3),
    "patinete": (25, [("Ride", "R-5"), ("Zippy", "Z-2")], "Mobilidade Compartilhada", 2.0),
    "moto_agente": (12, [("Honda", "XRE 300"), ("Yamaha", "Fazer 250")], "Secretaria de Mobilidade", 0.9),
    "viatura": (14, [("Chevrolet", "S10"), ("Toyota", "Hilux"), ("Ford", "Ranger")], "Guarda Municipal", 0.8),
}
PESO_SITUACAO = [("operacional", 72), ("mau_funcionamento", 8), ("em_manutencao", 6),
                 ("desativado", 4), ("nao_instalado", 5), ("furtado", 3)]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe", "Gabriela", "Hugo", "Isabela", "João",
         "Karina", "Lucas", "Marina", "Nicolas", "Olívia", "Paulo", "Renata", "Samuel", "Tatiana", "Vitor"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Santos", "Lima", "Pereira", "Costa", "Almeida", "Ferreira", "Rocha"]


def _alvo(rng, bairro):
    _, dlat, dlon, _, _ = bairro
    return (CENTRO[0] + dlat + rng.uniform(-0.008, 0.008), CENTRO[1] + dlon + rng.uniform(-0.008, 0.008))


def _hora(rng, tipo_evento, risco):
    """Falhas se espalham; furtos/vandalismo concentram na noite, mais em bairros de risco."""
    if tipo_evento in ("furto", "vandalismo"):
        pesos = [4 if (h >= 21 or h <= 4) else 1 for h in range(24)]
        if risco > 1.3:
            pesos = [p * (2 if (h >= 21 or h <= 4) else 1) for h, p in enumerate(pesos)]
    else:
        pesos = [3 if h in (7, 8, 17, 18, 19) else 1 for h in range(24)]
    return rng.choices(range(24), weights=pesos)[0]


def semear(conn, semente=42, forcar=False):
    """Popula o banco se estiver vazio. Devolve um resumo do que foi criado."""
    if not forcar and conn.execute("SELECT COUNT(*) FROM equipamento").fetchone()[0] > 0:
        return None
    rng = random.Random(semente)
    hoje = date.today()
    pesos_bairro = [b[3] for b in BAIRROS]
    situacoes, pesos_sit = zip(*PESO_SITUACAO)
    n_eq = 0
    eqs = []  # (id, tipo, bairro, risco, situacao, ultima_manut, instalacao, fator)

    for tipo, (qtd, modelos, orgao, fator) in CATALOGO.items():
        for i in range(qtd):
            b = rng.choices(BAIRROS, weights=pesos_bairro)[0]
            lat, lon = _alvo(rng, b)
            sit = rng.choices(situacoes, weights=pesos_sit)[0]
            marca, modelo = rng.choice(modelos)
            ref = rng.choice(REFERENCIAS).format(n=rng.randint(10, 999), k=rng.randint(1, 40))
            instalacao = None if sit == "nao_instalado" else hoje - timedelta(days=rng.randint(200, 1500))
            ultima = None
            if instalacao:
                ultima = hoje - timedelta(days=rng.choice([rng.randint(5, 90), rng.randint(90, 400)]))
            if sit in ("mau_funcionamento", "em_manutencao"):
                manut, prox = "imediata", None
            elif instalacao and rng.random() < 0.35:
                manut, prox = "agendada", hoje + timedelta(days=rng.randint(-5, 45))
            else:
                manut, prox = "nenhuma", None
            placa = "".join(rng.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=3)) + f"{rng.randint(1, 9)}{rng.choice('ABCDEFGH')}{rng.randint(10, 99)}"
            attrs = {
                "radar_velocidade": lambda: {"limite_kmh": rng.choice([40, 50, 60, 80]), "faixas": rng.randint(1, 4)},
                "radar_semaforo": lambda: {"faixas": rng.randint(1, 4)},
                "radar_conversao": lambda: {"tipo_infracao": rng.choice(["conversao_proibida", "retorno_proibido", "parada_faixa_pedestre"])},
                "camera": lambda: {"visao_noturna": rng.random() < 0.7, "resolucao": rng.choice(["720p", "1080p", "4K"]), "colorida": rng.random() < 0.85},
                "balanca": lambda: {"capacidade_ton": rng.choice([40, 60, 80])},
                "veiculo_autonomo": lambda: {"autonomia_km": rng.choice([80, 120, 200])},
                "cancela": lambda: {"tipo_acesso": rng.choice(["estacionamento", "via_restrita", "terminal"])},
                "veiculo_transporte": lambda: {"categoria": rng.choice(["taxi", "mototaxi", "escolar"]), "placa": placa},
                "totem_estacionamento": lambda: {"aceita_pix": rng.random() < 0.8, "vagas_atendidas": rng.randint(10, 120)},
                "patinete": lambda: {"bateria_pct": rng.randint(5, 100)},
                "moto_agente": lambda: {"placa": placa},
                "viatura": lambda: {"corporacao": rng.choice(["guarda_municipal", "policia_militar", "transito"]), "placa": placa},
            }[tipo]()
            serie = f"{tipo[:3].upper()}-{marca[:2].upper()}-{n_eq + 1:05d}"
            cur = conn.execute(
                """INSERT INTO equipamento (tipo, numero_serie, marca, modelo, situacao, manutencao_tipo,
                   proxima_manutencao, ultima_manutencao, data_instalacao, cep, bairro, cidade_uf, rua,
                   referencia, latitude, longitude, orgao, atributos)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tipo, serie, marca, modelo, sit, manut,
                 prox.isoformat() if prox else None, ultima.isoformat() if ultima else None,
                 instalacao.isoformat() if instalacao else None,
                 f"13{rng.randint(100, 999)}-{rng.randint(100, 999)}", b[0], CIDADE_UF,
                 rng.choice(RUAS), ref, round(lat, 6), round(lon, 6), orgao,
                 json.dumps(attrs, ensure_ascii=False)))
            n_eq += 1
            eqs.append((cur.lastrowid, tipo, b[0], b[4], sit, ultima, instalacao, fator))

    # Histórico de 180 dias. Mais manutenção atrasada e bairro de risco => mais ocorrências.
    n_ev = 0
    for eq_id, tipo, bairro, risco, sit, ultima, instalacao, fator in eqs:
        if not instalacao:
            continue
        dias_sem_manut = (hoje - ultima).days if ultima else 365
        taxa_mes = 0.25 * fator * risco * (1 + dias_sem_manut / 150) * (2.5 if sit == "mau_funcionamento" else 1)
        n = min(25, int(rng.expovariate(1 / max(taxa_mes * 6, 0.1))))   # 6 meses
        for _ in range(n):
            tipo_ev = rng.choices(["falha", "furto", "vandalismo", "alerta"],
                                  weights=[60, 6 * risco, 10 * risco, 24])[0]
            dia = hoje - timedelta(days=rng.randint(0, 179))
            peso_dia = {4: 1.6, 5: 1.8}.get(dia.weekday(), 1.0)       # sexta/sábado pesam mais
            if tipo_ev in ("furto", "vandalismo") and rng.random() > peso_dia / 1.8:
                continue
            quando = datetime.combine(dia, datetime.min.time()).replace(
                hour=_hora(rng, tipo_ev, risco), minute=rng.randint(0, 59))
            conn.execute("INSERT INTO evento (equipamento_id, tipo, descricao, ocorrido_em) VALUES (?,?,?,?)",
                         (eq_id, tipo_ev, f"{tipo_ev} registrado pela telemetria", quando.isoformat(timespec="minutes")))
            n_ev += 1

    # Agentes: em atividade ficam perto de algum bairro.
    viaturas = [e[0] for e in eqs if e[1] in ("viatura", "moto_agente")]
    n_ag = 0
    funcoes = [("agente_transito", "Secretaria de Mobilidade"), ("guarda_municipal", "Guarda Municipal"),
               ("policial_militar", "Polícia Militar")]
    for i in range(36):
        funcao, orgao = rng.choices(funcoes, weights=[4, 3, 3])[0]
        ativo = rng.random() < 0.7
        lat = lon = None
        if ativo:
            lat, lon = _alvo(rng, rng.choices(BAIRROS, weights=pesos_bairro)[0])
        conn.execute(
            """INSERT INTO agente (nome, matricula, funcao, orgao, situacao, latitude, longitude,
               ultima_posicao_em, equipamento_id) VALUES (?,?,?,?,?,?,?,?,?)""",
            (f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}", f"AG-{i + 1:04d}", funcao, orgao,
             "em_atividade" if ativo else rng.choice(["fora_de_servico", "fora_de_servico", "afastado"]),
             round(lat, 6) if lat else None, round(lon, 6) if lon else None,
             datetime.now().isoformat(timespec="seconds") if ativo else None,
             rng.choice(viaturas) if ativo and rng.random() < 0.6 else None))
        n_ag += 1
    return {"equipamentos": n_eq, "eventos": n_ev, "agentes": n_ag}


if __name__ == "__main__":
    from .db import iniciar, sessao
    iniciar()
    with sessao() as c:
        print(semear(c, forcar=False) or "Banco já populado; nada a fazer.")

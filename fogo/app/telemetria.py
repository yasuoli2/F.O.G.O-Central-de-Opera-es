"""Telemetria dos equipamentos IoT e o alerta de "sem sinal" (Parte 2).

Pergunta do enunciado: "se algo estiver acontecendo agora, PROMETHEUS perceberá?".
Um equipamento que quebra e para de avisar é o pior caso: ele não manda alerta nenhum. Por isso o sistema
guarda a ÚLTIMA leitura de cada equipamento e trata a AUSÊNCIA de leituras como um alerta.

  - registrar(): recebe uma leitura (aparelho real, via POST /api/telemetria).
  - sem_sinal()/resumo(): quem está calado há mais de LIMITE_SILENCIO_MIN minutos.
  - simulador(): na demonstração, faz os aparelhos "enviarem" sinal sozinhos; os marcados como mudos ficam calados.

Só a biblioteca padrão.
"""
import asyncio
import random
from datetime import datetime, timedelta

from .catalogo import ValidacaoErro
from .repo import NaoEncontrado

LIMITE_SILENCIO_MIN = 15
MONITORADOS = ("operacional", "mau_funcionamento")   # os demais não precisam (nem conseguem) reportar
STATUS = ("ok", "alerta", "falha")
INTERVALO_SIMULADOR_S = 20


def _agora(agora=None):
    return agora or datetime.now()


def _iso(d):
    return d.isoformat(timespec="seconds")


def _pct(d, campo, erros):
    v = d.get(campo)
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not 0 <= v <= 100:
        erros.append(f"{campo}: inteiro entre 0 e 100")
        return None
    return int(v)


def registrar(conn, dados, agora=None):
    """Grava uma leitura. Uma falha reportada vira ocorrência e marca o equipamento como em mau funcionamento."""
    if not isinstance(dados, dict):
        raise ValidacaoErro(["corpo: deve ser um objeto"])
    erros = []
    eq = None
    if dados.get("equipamento_id") is not None:
        if isinstance(dados["equipamento_id"], bool) or not isinstance(dados["equipamento_id"], int):
            erros.append("equipamento_id: deve ser um número inteiro")
        else:
            eq = conn.execute("SELECT id, situacao FROM equipamento WHERE id = ?", (dados["equipamento_id"],)).fetchone()
    elif dados.get("numero_serie"):
        eq = conn.execute("SELECT id, situacao FROM equipamento WHERE numero_serie = ?", (str(dados["numero_serie"]),)).fetchone()
    else:
        erros.append("informe equipamento_id ou numero_serie")
    sinal = _pct(dados, "sinal_pct", erros)
    bateria = _pct(dados, "bateria_pct", erros)
    status = dados.get("status", "ok")
    if status not in STATUS:
        erros.append(f"status: use um de {list(STATUS)}")
    if erros:
        raise ValidacaoErro(erros)
    if eq is None:
        raise NaoEncontrado("Equipamento não encontrado")

    agora = _agora(agora)
    conn.execute("""INSERT INTO telemetria (equipamento_id, recebido_em, sinal_pct, bateria_pct, status, mudo)
                    VALUES (?,?,?,?,?,0)
                    ON CONFLICT(equipamento_id) DO UPDATE SET recebido_em = excluded.recebido_em,
                    sinal_pct = excluded.sinal_pct, bateria_pct = excluded.bateria_pct,
                    status = excluded.status, mudo = 0""",
                 (eq["id"], _iso(agora), sinal, bateria, status))
    if status in ("falha", "alerta"):
        conn.execute("INSERT INTO evento (equipamento_id, tipo, descricao, ocorrido_em) VALUES (?,?,?,?)",
                     (eq["id"], status, "telemetria: " + status + " reportado pelo equipamento", _iso(agora)))
    if status == "falha" and eq["situacao"] == "operacional":
        conn.execute("""UPDATE equipamento SET situacao = 'mau_funcionamento', manutencao_tipo = 'imediata',
                        atualizado_em = datetime('now') WHERE id = ?""", (eq["id"],))
    return {"equipamento_id": eq["id"], "recebido_em": _iso(agora), "status": status}


def _monitorados(conn):
    marcas = ",".join("?" * len(MONITORADOS))
    return conn.execute(f"""SELECT e.id, e.numero_serie, e.tipo, e.bairro, e.situacao,
                                   t.recebido_em, t.mudo, (julianday('now') - julianday(e.criado_em)) * 1440 AS idade_min
                            FROM equipamento e LEFT JOIN telemetria t ON t.equipamento_id = e.id
                            WHERE e.situacao IN ({marcas}) ORDER BY e.id""", MONITORADOS).fetchall()


def resumo(conn, agora=None, limite_min=LIMITE_SILENCIO_MIN):
    """Quem está monitorado, quem tem sinal e quem está calado (com há quantos minutos)."""
    agora = _agora(agora)
    itens, com_sinal = [], 0
    linhas = _monitorados(conn)
    for r in linhas:
        if r["recebido_em"]:
            minutos = (agora - datetime.fromisoformat(r["recebido_em"])).total_seconds() / 60
        elif r["idade_min"] is not None and r["idade_min"] >= limite_min:
            minutos = None                       # cadastrado há tempo e nunca enviou nada
        else:
            com_sinal += 1                       # acabou de ser cadastrado: damos um prazo
            continue
        if minutos is not None and minutos <= limite_min:
            com_sinal += 1
            continue
        itens.append({"id": r["id"], "numero_serie": r["numero_serie"], "tipo": r["tipo"], "bairro": r["bairro"],
                      "minutos_sem_sinal": None if minutos is None else int(minutos),
                      "ultima_leitura": r["recebido_em"],
                      "texto": "nunca enviou leitura" if minutos is None else _texto_tempo(minutos)})
    itens.sort(key=lambda x: (x["minutos_sem_sinal"] is None, -(x["minutos_sem_sinal"] or 0)))   # mais antigo primeiro; "nunca enviou" por último
    return {"limite_min": limite_min, "monitorados": len(linhas), "com_sinal": com_sinal,
            "sem_sinal": len(itens), "itens": itens}


def _texto_tempo(minutos):
    m = int(minutos)
    return f"sem sinal há {m} min" if m < 120 else f"sem sinal há {m // 60} h"


# ------------------------------------------------------------------- demonstração
def semear(conn, agora=None, semente=7, mudos=3):
    """Dá uma leitura inicial a cada equipamento monitorado; alguns ficam mudos de propósito. Só se a tabela está vazia."""
    if conn.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0] > 0:
        return 0
    agora = _agora(agora)
    rng = random.Random(semente)
    ids = [r["id"] for r in _monitorados(conn)]
    silenciosos = set(rng.sample(ids, min(mudos, len(ids))))
    for eid in ids:
        if eid in silenciosos:
            quando = agora - timedelta(minutes=rng.randint(130, 600))
            conn.execute("INSERT INTO telemetria (equipamento_id, recebido_em, sinal_pct, bateria_pct, status, mudo) "
                         "VALUES (?,?,?,?,?,1)", (eid, _iso(quando), rng.randint(5, 30), rng.randint(10, 60), "ok"))
        else:
            quando = agora - timedelta(seconds=rng.randint(0, 120))
            conn.execute("INSERT INTO telemetria (equipamento_id, recebido_em, sinal_pct, bateria_pct, status, mudo) "
                         "VALUES (?,?,?,?,?,0)", (eid, _iso(quando), rng.randint(55, 100), rng.randint(40, 100), "ok"))
    return len(ids)


def tick(conn, agora=None, semente=None):
    """Uma rodada de leituras simuladas: todos os monitorados que NÃO estão mudos enviam sinal."""
    agora = _agora(agora)
    rng = random.Random(semente)
    semear(conn, agora)
    enviados = 0
    for r in _monitorados(conn):
        if r["mudo"]:
            continue
        conn.execute("""INSERT INTO telemetria (equipamento_id, recebido_em, sinal_pct, bateria_pct, status, mudo)
                        VALUES (?,?,?,?,'ok',0)
                        ON CONFLICT(equipamento_id) DO UPDATE SET recebido_em = excluded.recebido_em,
                        sinal_pct = excluded.sinal_pct, bateria_pct = COALESCE(excluded.bateria_pct, bateria_pct), mudo = 0""",
                     (r["id"], _iso(agora), rng.randint(55, 100), rng.randint(40, 100)))
        enviados += 1
    return enviados


def silenciar(conn, equipamento_id=None, agora=None, semente=None):
    """Demonstração: faz um equipamento parar de enviar sinal (há 2 h). Sem id, sorteia um que esteja com sinal."""
    agora = _agora(agora)
    semear(conn, agora)
    rng = random.Random(semente)
    if equipamento_id is None:
        vivos = [r for r in _monitorados(conn) if not r["mudo"]]
        if not vivos:
            return None
        escolhido = rng.choice(vivos)
    else:
        escolhido = next((r for r in _monitorados(conn) if r["id"] == equipamento_id), None)
        if escolhido is None:
            return None
    conn.execute("UPDATE telemetria SET mudo = 1, recebido_em = ? WHERE equipamento_id = ?",
                 (_iso(agora - timedelta(hours=2)), escolhido["id"]))
    return {"equipamento_id": escolhido["id"], "numero_serie": escolhido["numero_serie"], "bairro": escolhido["bairro"]}


def normalizar(conn, agora=None):
    """Demonstração: todos os equipamentos monitorados voltam a enviar sinal."""
    agora = _agora(agora)
    semear(conn, agora)
    conn.execute("UPDATE telemetria SET mudo = 0")
    return tick(conn, agora)


async def simulador(abrir_sessao, intervalo=INTERVALO_SIMULADOR_S):
    """Tarefa de fundo: simula os aparelhos enviando sinal. `abrir_sessao` é o gerenciador de contexto de db.sessao."""
    def uma_rodada():
        with abrir_sessao() as conn:
            tick(conn)
    while True:
        try:
            await asyncio.to_thread(uma_rodada)
        except Exception:                      # a simulação nunca deve derrubar o servidor
            pass
        await asyncio.sleep(intervalo)

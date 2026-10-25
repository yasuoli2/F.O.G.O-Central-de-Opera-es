"""Operações de cadastro (CRUD) de equipamentos e agentes."""
import json

from .catalogo import validar_agente, validar_equipamento

EQ_COLS = ["tipo", "numero_serie", "marca", "modelo", "situacao", "manutencao_tipo",
           "proxima_manutencao", "ultima_manutencao", "data_instalacao", "cep", "bairro",
           "cidade_uf", "rua", "referencia", "latitude", "longitude", "orgao"]
AG_COLS = ["nome", "matricula", "funcao", "orgao", "situacao", "latitude", "longitude",
           "equipamento_id"]


class NaoEncontrado(Exception):
    pass


def _eq(row):
    d = dict(row)
    d["atributos"] = json.loads(d["atributos"] or "{}")
    return d


# ---------------------------------------------------------------- equipamentos
def listar_equipamentos(conn, tipo=None, situacao=None, bairro=None, orgao=None,
                        manutencao=None, q=None, limite=500, deslocamento=0):
    where, args = [], []
    for col, val in (("tipo", tipo), ("situacao", situacao), ("bairro", bairro),
                     ("orgao", orgao), ("manutencao_tipo", manutencao)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if q:
        where.append("(numero_serie LIKE ? OR marca LIKE ? OR modelo LIKE ? OR rua LIKE ?)")
        args += [f"%{q}%"] * 4
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM equipamento{cond}", args).fetchone()[0]
    limite = max(1, min(int(limite), 2000))
    rows = conn.execute(f"SELECT * FROM equipamento{cond} ORDER BY id LIMIT ? OFFSET ?",
                        args + [limite, max(0, int(deslocamento))]).fetchall()
    return {"total": total, "itens": [_eq(r) for r in rows]}


def obter_equipamento(conn, eq_id):
    row = conn.execute("SELECT * FROM equipamento WHERE id = ?", (eq_id,)).fetchone()
    if not row:
        raise NaoEncontrado(f"Equipamento {eq_id} não encontrado")
    return _eq(row)


def _gravar_equipamento(conn, dados, eq_id=None):
    v = validar_equipamento(dados)
    valores = [v[c] for c in EQ_COLS]
    atributos = json.dumps(v["atributos"], ensure_ascii=False)
    if eq_id is None:
        cols = ", ".join(EQ_COLS + ["atributos"])
        marcas = ", ".join("?" * (len(EQ_COLS) + 1))
        cur = conn.execute(f"INSERT INTO equipamento ({cols}) VALUES ({marcas})", valores + [atributos])
        return obter_equipamento(conn, cur.lastrowid)
    sets = ", ".join(f"{c} = ?" for c in EQ_COLS) + ", atributos = ?, atualizado_em = datetime('now')"
    conn.execute(f"UPDATE equipamento SET {sets} WHERE id = ?", valores + [atributos, eq_id])
    return obter_equipamento(conn, eq_id)


def criar_equipamento(conn, dados):
    return _gravar_equipamento(conn, dados)


def atualizar_equipamento(conn, eq_id, mudancas):
    """Atualização parcial: mescla com o registro atual e valida o resultado inteiro."""
    atual = obter_equipamento(conn, eq_id)
    mesclado = {**atual, **{k: v for k, v in mudancas.items() if k != "atributos"}}
    if "atributos" in mudancas:
        mesclado["atributos"] = mudancas["atributos"]
    elif "tipo" in mudancas and mudancas["tipo"] != atual["tipo"]:
        mesclado["atributos"] = {}          # outro tipo: atributos antigos não valem
    if "situacao" in mudancas and "manutencao_tipo" not in mudancas:
        # A situação mudou e a manutenção não foi informada: ajusta de forma coerente.
        if mudancas["situacao"] in ("mau_funcionamento", "em_manutencao"):
            mesclado["manutencao_tipo"] = "imediata"
        elif atual["manutencao_tipo"] == "imediata":
            mesclado["manutencao_tipo"] = "nenhuma"
    return _gravar_equipamento(conn, mesclado, eq_id)


def excluir_equipamento(conn, eq_id):
    obter_equipamento(conn, eq_id)
    conn.execute("DELETE FROM equipamento WHERE id = ?", (eq_id,))


# --------------------------------------------------------------------- agentes
def listar_agentes(conn, funcao=None, situacao=None, orgao=None, q=None):
    where, args = [], []
    for col, val in (("funcao", funcao), ("situacao", situacao), ("orgao", orgao)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if q:
        where.append("(nome LIKE ? OR matricula LIKE ?)")
        args += [f"%{q}%"] * 2
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(f"SELECT * FROM agente{cond} ORDER BY id", args).fetchall()
    return {"total": len(rows), "itens": [dict(r) for r in rows]}


def obter_agente(conn, ag_id):
    row = conn.execute("SELECT * FROM agente WHERE id = ?", (ag_id,)).fetchone()
    if not row:
        raise NaoEncontrado(f"Agente {ag_id} não encontrado")
    return dict(row)


def _gravar_agente(conn, dados, ag_id=None):
    v = validar_agente(dados)
    valores = [v[c] for c in AG_COLS]
    if ag_id is None:
        cols = ", ".join(AG_COLS)
        marcas = ", ".join("?" * len(AG_COLS))
        cur = conn.execute(f"INSERT INTO agente ({cols}) VALUES ({marcas})", valores)
        ag_id = cur.lastrowid
    else:
        sets = ", ".join(f"{c} = ?" for c in AG_COLS) + ", atualizado_em = datetime('now')"
        conn.execute(f"UPDATE agente SET {sets} WHERE id = ?", valores + [ag_id])
    if v["latitude"] is not None:
        conn.execute("UPDATE agente SET ultima_posicao_em = datetime('now') WHERE id = ?", (ag_id,))
    return obter_agente(conn, ag_id)


def criar_agente(conn, dados):
    return _gravar_agente(conn, dados)


def atualizar_agente(conn, ag_id, mudancas):
    atual = obter_agente(conn, ag_id)
    return _gravar_agente(conn, {**atual, **mudancas}, ag_id)


def excluir_agente(conn, ag_id):
    obter_agente(conn, ag_id)
    conn.execute("DELETE FROM agente WHERE id = ?", (ag_id,))


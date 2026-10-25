"""API do F.O.G.O. Rotas finas: a lógica está em catalogo.py, repo.py (cadastro) e predict.py (previsões)."""
import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import catalogo, operacao, predict, repo, telemetria
from .db import iniciar, sessao
from .seed import semear

STATIC = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(_app):
    iniciar()
    with sessao() as conn:
        semear(conn)          # só popula se o banco estiver vazio
        telemetria.tick(conn)  # dá uma leitura inicial a cada equipamento (os "mudos" da demonstração continuam mudos)
    tarefa = None
    if os.environ.get("FOGO_SIMULAR_TELEMETRIA", "1") == "1":     # defina 0 para desligar a simulação
        tarefa = asyncio.create_task(telemetria.simulador(sessao))
    yield
    if tarefa:
        tarefa.cancel()


app = FastAPI(title="F.O.G.O. – Ferramenta Onisciente de Gestão e Operações", lifespan=lifespan)


@app.exception_handler(catalogo.ValidacaoErro)
def _validacao(_req, exc):
    return JSONResponse({"erros": exc.erros}, status_code=422)


@app.exception_handler(repo.NaoEncontrado)
def _nao_encontrado(_req, exc):
    return JSONResponse({"erro": str(exc)}, status_code=404)


@app.exception_handler(sqlite3.IntegrityError)
def _integridade(_req, exc):
    msg = "Já existe um registro com esse número de série/matrícula" if "UNIQUE" in str(exc) \
        else "Referência inválida (equipamento inexistente?)"
    return JSONResponse({"erro": msg}, status_code=409)


# ------------------------------------------------------------------ metadados
@app.get("/api/tipos")
def tipos():
    """Tudo que o formulário precisa: tipos (com campos próprios), situações e listas fixas."""
    return {
        "tipos": {k: {"rotulo": v["rotulo"], "campos": v["campos"], "movel": k in catalogo.MOVEIS}
                  for k, v in catalogo.TIPOS.items()},
        "situacoes": catalogo.SITUACOES,
        "manutencoes": catalogo.MANUTENCOES,
        "funcoes_agente": catalogo.FUNCOES_AGENTE,
        "situacoes_agente": catalogo.SITUACOES_AGENTE,
    }


# ---------------------------------------------------------------- equipamentos
@app.get("/api/equipamentos")
def listar_equipamentos(tipo: str | None = None, situacao: str | None = None, bairro: str | None = None,
                        orgao: str | None = None, manutencao: str | None = None, q: str | None = None,
                        limite: int = Query(500, ge=1, le=2000), deslocamento: int = Query(0, ge=0)):
    with sessao() as conn:
        return repo.listar_equipamentos(conn, tipo, situacao, bairro, orgao, manutencao, q, limite, deslocamento)


@app.post("/api/equipamentos", status_code=201)
def criar_equipamento(dados: dict = Body(...)):
    with sessao() as conn:
        return repo.criar_equipamento(conn, dados)


@app.get("/api/equipamentos/{eq_id}")
def obter_equipamento(eq_id: int):
    with sessao() as conn:
        return repo.obter_equipamento(conn, eq_id)


@app.patch("/api/equipamentos/{eq_id}")
def atualizar_equipamento(eq_id: int, mudancas: dict = Body(...)):
    with sessao() as conn:
        return repo.atualizar_equipamento(conn, eq_id, mudancas)


@app.delete("/api/equipamentos/{eq_id}", status_code=204)
def excluir_equipamento(eq_id: int):
    with sessao() as conn:
        repo.excluir_equipamento(conn, eq_id)


# --------------------------------------------------------------------- agentes
@app.get("/api/agentes")
def listar_agentes(funcao: str | None = None, situacao: str | None = None,
                   orgao: str | None = None, q: str | None = None):
    with sessao() as conn:
        return repo.listar_agentes(conn, funcao, situacao, orgao, q)


@app.post("/api/agentes", status_code=201)
def criar_agente(dados: dict = Body(...)):
    with sessao() as conn:
        return repo.criar_agente(conn, dados)


@app.get("/api/agentes/{ag_id}")
def obter_agente(ag_id: int):
    with sessao() as conn:
        return repo.obter_agente(conn, ag_id)


@app.patch("/api/agentes/{ag_id}")
def atualizar_agente(ag_id: int, mudancas: dict = Body(...)):
    with sessao() as conn:
        return repo.atualizar_agente(conn, ag_id, mudancas)


@app.delete("/api/agentes/{ag_id}", status_code=204)
def excluir_agente(ag_id: int):
    with sessao() as conn:
        repo.excluir_agente(conn, ag_id)


# ------------------------------------------------- operação: regiões e telemetria
@app.get("/api/regioes")
def regioes():
    """Visão consolidada: quais bairros operam normalmente e quais exigem atenção."""
    with sessao() as conn:
        return operacao.regioes(conn)


@app.get("/api/telemetria/resumo")
def telemetria_resumo(limite_min: int = Query(telemetria.LIMITE_SILENCIO_MIN, ge=1, le=1440)):
    """Quais equipamentos estão sem enviar sinal há mais de `limite_min` minutos."""
    with sessao() as conn:
        return telemetria.resumo(conn, limite_min=limite_min)


@app.post("/api/telemetria", status_code=201)
def telemetria_registrar(dados: dict = Body(...)):
    """Recebe uma leitura de um equipamento IoT: {numero_serie|equipamento_id, sinal_pct, bateria_pct, status}."""
    with sessao() as conn:
        return telemetria.registrar(conn, dados)


@app.post("/api/demo/telemetria")
def demo_telemetria(dados: dict | None = Body(None)):
    """Demonstração: {"acao": "silenciar"} faz um equipamento parar de enviar sinal; {"acao": "normalizar"} restaura todos."""
    acao = (dados or {}).get("acao", "silenciar")
    with sessao() as conn:
        if acao == "silenciar":
            r = telemetria.silenciar(conn, (dados or {}).get("equipamento_id"))
            if r is None:
                raise repo.NaoEncontrado("Nenhum equipamento disponível para silenciar")
            return r
        if acao == "normalizar":
            return {"restaurados": telemetria.normalizar(conn)}
    raise catalogo.ValidacaoErro(["acao: use 'silenciar' ou 'normalizar'"])


# ------------------------------------------------------------------ previsões
@app.get("/api/previsoes")
def previsoes():
    """Parte 3: riscos, mapa de calor, previsão de 7 dias, anomalias, recomendações e validação."""
    with sessao() as conn:
        return predict.previsoes(conn)


@app.post("/api/demo/rajada", status_code=201)
def demo_rajada(dados: dict | None = Body(None)):
    """Demonstração: injeta uma rajada de falhas recentes (marcadas [DEMO]) para ver a detecção de anomalia."""
    dados = dados or {}
    with sessao() as conn:
        r = predict.simular_rajada(conn, dados.get("equipamento_id"), int(dados.get("quantidade", 4)))
    if r is None:
        raise repo.NaoEncontrado("Nenhum equipamento disponível para a simulação")
    return r


@app.delete("/api/demo/rajada")
def demo_limpar():
    with sessao() as conn:
        return {"removidos": predict.limpar_rajada(conn)}


# ------------------------------------------------------------------- interface
@app.get("/", include_in_schema=False)
def raiz():
    index = os.path.join(STATIC, "index.html")
    return FileResponse(index) if os.path.exists(index) else RedirectResponse("/docs")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

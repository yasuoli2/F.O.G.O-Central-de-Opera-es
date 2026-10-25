"""Acesso ao SQLite (biblioteca padrão)."""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("FOGO_DB", os.path.join(os.path.dirname(__file__), "..", "fogo.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipamento (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo                TEXT NOT NULL,
    numero_serie        TEXT NOT NULL UNIQUE,
    marca               TEXT NOT NULL,
    modelo              TEXT NOT NULL,
    situacao            TEXT NOT NULL,
    manutencao_tipo     TEXT NOT NULL DEFAULT 'nenhuma',
    proxima_manutencao  TEXT,
    ultima_manutencao   TEXT,
    data_instalacao     TEXT,
    cep                 TEXT,
    bairro              TEXT NOT NULL,
    cidade_uf           TEXT NOT NULL,
    rua                 TEXT NOT NULL,
    referencia          TEXT NOT NULL DEFAULT 'S/N',
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    orgao               TEXT,
    atributos           TEXT NOT NULL DEFAULT '{}',
    criado_em           TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_eq_situacao ON equipamento(situacao);
CREATE INDEX IF NOT EXISTS ix_eq_bairro   ON equipamento(bairro);
CREATE INDEX IF NOT EXISTS ix_eq_tipo     ON equipamento(tipo);

CREATE TABLE IF NOT EXISTS agente (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    matricula       TEXT NOT NULL UNIQUE,
    funcao          TEXT NOT NULL,
    orgao           TEXT,
    situacao        TEXT NOT NULL DEFAULT 'fora_de_servico',
    latitude        REAL,
    longitude       REAL,
    ultima_posicao_em TEXT,
    equipamento_id  INTEGER REFERENCES equipamento(id) ON DELETE SET NULL,
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Última leitura de telemetria de cada equipamento (uma linha por equipamento: o espaço não cresce).
-- "mudo" é usado só na demonstração: simula um aparelho que parou de enviar sinal.
CREATE TABLE IF NOT EXISTS telemetria (
    equipamento_id  INTEGER PRIMARY KEY REFERENCES equipamento(id) ON DELETE CASCADE,
    recebido_em     TEXT NOT NULL,
    sinal_pct       INTEGER,
    bateria_pct     INTEGER,
    status          TEXT NOT NULL DEFAULT 'ok',
    mudo            INTEGER NOT NULL DEFAULT 0
);

-- Histórico de ocorrências: base da Parte 3 (previsões).
CREATE TABLE IF NOT EXISTS evento (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    equipamento_id  INTEGER NOT NULL REFERENCES equipamento(id) ON DELETE CASCADE,
    tipo            TEXT NOT NULL,
    descricao       TEXT,
    ocorrido_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ev_eq   ON evento(equipamento_id);
CREATE INDEX IF NOT EXISTS ix_ev_data ON evento(ocorrido_em);
"""


def conectar(path=None):
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iniciar(path=None):
    with sessao(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def sessao(path=None):
    """Abre conexão, faz commit no sucesso, rollback no erro e sempre fecha."""
    conn = conectar(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

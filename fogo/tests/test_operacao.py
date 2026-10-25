import asyncio
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from app import catalogo, operacao, repo, telemetria
from app.db import iniciar, sessao

AGORA = datetime(2026, 10, 24, 14, 0, 0)


def eq(serie, bairro="Centro", **extra):
    d = {"tipo": "radar_velocidade", "numero_serie": serie, "marca": "Fiscal-Tech", "modelo": "FT-200",
         "situacao": "operacional", "cep": "13500000", "bairro": bairro, "cidade_uf": "Cidade Modelo/SP",
         "rua": "Av. Brasil", "referencia": "S/N", "latitude": -21.8, "longitude": -47.6,
         "atributos": {"limite_kmh": 60}}
    d.update(extra)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        iniciar(self.path)

    def tearDown(self):
        os.remove(self.path)

    def velho(self, c, eid):
        """Faz o cadastro 'parecer antigo' (o prazo de carência para enviar a 1ª leitura já passou)."""
        c.execute("UPDATE equipamento SET criado_em = datetime('now', '-2 days') WHERE id = ?", (eid,))


class TestRegistrar(Base):
    def test_validacoes(self):
        with sessao(self.path) as c:
            repo.criar_equipamento(c, eq("A"))
            for dados in ({}, {"numero_serie": "A", "sinal_pct": 120}, {"numero_serie": "A", "bateria_pct": -1},
                          {"numero_serie": "A", "status": "quebrado"}, {"equipamento_id": "1"}, {"numero_serie": "A", "sinal_pct": 5.5}):
                with self.subTest(dados=dados), self.assertRaises(catalogo.ValidacaoErro):
                    telemetria.registrar(c, dados, AGORA)
            with self.assertRaises(repo.NaoEncontrado):
                telemetria.registrar(c, {"numero_serie": "NAO-EXISTE"}, AGORA)
            with self.assertRaises(catalogo.ValidacaoErro):
                telemetria.registrar(c, "texto", AGORA)

    def test_leitura_substitui_a_anterior(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, eq("A"))["id"]
            telemetria.registrar(c, {"numero_serie": "A", "sinal_pct": 80, "bateria_pct": 90}, AGORA - timedelta(hours=1))
            telemetria.registrar(c, {"equipamento_id": eid, "sinal_pct": 40}, AGORA)
            linhas = c.execute("SELECT * FROM telemetria").fetchall()
        self.assertEqual(len(linhas), 1)
        self.assertEqual((linhas[0]["sinal_pct"], linhas[0]["recebido_em"]), (40, AGORA.isoformat(timespec="seconds")))

    def test_falha_vira_ocorrencia_e_mau_funcionamento(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, eq("A"))["id"]
            telemetria.registrar(c, {"numero_serie": "A", "status": "falha"}, AGORA)
            e = repo.obter_equipamento(c, eid)
            evs = c.execute("SELECT tipo FROM evento WHERE equipamento_id = ?", (eid,)).fetchall()
        self.assertEqual((e["situacao"], e["manutencao_tipo"]), ("mau_funcionamento", "imediata"))
        self.assertEqual([x["tipo"] for x in evs], ["falha"])

    def test_alerta_so_registra_ocorrencia(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, eq("A"))["id"]
            telemetria.registrar(c, {"numero_serie": "A", "status": "alerta"}, AGORA)
            self.assertEqual(repo.obter_equipamento(c, eid)["situacao"], "operacional")
            self.assertEqual(c.execute("SELECT tipo FROM evento").fetchone()["tipo"], "alerta")


class TestSilencio(Base):
    def test_limite_de_minutos(self):
        with sessao(self.path) as c:
            a = repo.criar_equipamento(c, eq("RECENTE"))["id"]
            b = repo.criar_equipamento(c, eq("ATRASADO", bairro="Zona Norte"))["id"]
            telemetria.registrar(c, {"equipamento_id": a}, AGORA - timedelta(minutes=5))
            telemetria.registrar(c, {"equipamento_id": b}, AGORA - timedelta(minutes=20))
            r = telemetria.resumo(c, AGORA, limite_min=15)
            self.assertEqual((r["monitorados"], r["com_sinal"], r["sem_sinal"]), (2, 1, 1))
            self.assertEqual(r["itens"][0]["numero_serie"], "ATRASADO")
            self.assertEqual(r["itens"][0]["texto"], "sem sinal há 20 min")
            self.assertEqual(telemetria.resumo(c, AGORA, limite_min=30)["sem_sinal"], 0)     # o limite é parâmetro
            self.assertEqual(telemetria._texto_tempo(300), "sem sinal há 5 h")

    def test_quem_nunca_enviou_e_quem_acabou_de_ser_cadastrado(self):
        with sessao(self.path) as c:
            antigo = repo.criar_equipamento(c, eq("ANTIGO"))["id"]
            repo.criar_equipamento(c, eq("NOVO"))
            self.velho(c, antigo)
            r = telemetria.resumo(c, AGORA)
        self.assertEqual([i["numero_serie"] for i in r["itens"]], ["ANTIGO"])
        self.assertEqual(r["itens"][0]["texto"], "nunca enviou leitura")
        self.assertEqual(r["com_sinal"], 1)               # o NOVO tem prazo de carência

    def test_so_monitora_quem_deveria_reportar(self):
        with sessao(self.path) as c:
            for i, s in enumerate(("em_manutencao", "desativado", "furtado", "nao_instalado")):
                eid = repo.criar_equipamento(c, eq(f"X{i}", situacao=s))["id"]
                self.velho(c, eid)
            self.assertEqual(telemetria.resumo(c, AGORA)["monitorados"], 0)

    def test_ordena_do_mais_antigo_e_deixa_o_nunca_para_o_fim(self):
        with sessao(self.path) as c:
            ids = [repo.criar_equipamento(c, eq(f"E{i}"))["id"] for i in range(3)]
            telemetria.registrar(c, {"equipamento_id": ids[0]}, AGORA - timedelta(minutes=30))
            telemetria.registrar(c, {"equipamento_id": ids[1]}, AGORA - timedelta(hours=5))
            self.velho(c, ids[2])
            nomes = [i["numero_serie"] for i in telemetria.resumo(c, AGORA)["itens"]]
        self.assertEqual(nomes, ["E1", "E0", "E2"])


class TestSimulacao(Base):
    def popular(self, c, n=12):
        for i in range(n):
            repo.criar_equipamento(c, eq(f"S{i:02d}", bairro=("Centro", "Zona Norte")[i % 2]))

    def test_semear_deixa_alguns_mudos_e_so_roda_uma_vez(self):
        with sessao(self.path) as c:
            self.popular(c)
            self.assertEqual(telemetria.semear(c, AGORA, mudos=3), 12)
            self.assertEqual(telemetria.semear(c, AGORA), 0)
            r = telemetria.resumo(c, AGORA)
        self.assertEqual(r["sem_sinal"], 3)

    def test_tick_mantem_os_vivos_e_nao_ressuscita_os_mudos(self):
        with sessao(self.path) as c:
            self.popular(c)
            telemetria.semear(c, AGORA - timedelta(hours=1), mudos=3)         # tudo envelhece 1 h
            enviados = telemetria.tick(c, AGORA, semente=1)
            r = telemetria.resumo(c, AGORA)
        self.assertEqual(enviados, 9)
        self.assertEqual(r["sem_sinal"], 3)

    def test_silenciar_e_normalizar(self):
        with sessao(self.path) as c:
            self.popular(c)
            telemetria.tick(c, AGORA)
            self.assertEqual(telemetria.resumo(c, AGORA)["sem_sinal"], 3)
            info = telemetria.silenciar(c, agora=AGORA, semente=2)
            self.assertIn("numero_serie", info)
            self.assertEqual(telemetria.resumo(c, AGORA)["sem_sinal"], 4)
            telemetria.tick(c, AGORA)                                          # o recém-silenciado continua calado
            self.assertEqual(telemetria.resumo(c, AGORA)["sem_sinal"], 4)
            self.assertIsNone(telemetria.silenciar(c, equipamento_id=99999, agora=AGORA))
            telemetria.normalizar(c, AGORA)
            self.assertEqual(telemetria.resumo(c, AGORA)["sem_sinal"], 0)

    def test_simulador_assincrono_alimenta_o_banco_e_pode_ser_cancelado(self):
        with sessao(self.path) as c:
            self.popular(c, 5)

        async def rodar():
            tarefa = asyncio.create_task(telemetria.simulador(lambda: sessao(self.path), intervalo=0.05))
            await asyncio.sleep(0.4)
            tarefa.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await tarefa
        asyncio.run(rodar())
        with sessao(self.path) as c:
            n = c.execute("SELECT COUNT(*) FROM telemetria").fetchone()[0]
        self.assertEqual(n, 5)


class TestRegioes(Base):
    def montar(self, c):
        # Norte: 10 equipamentos, todos operacionais, com agente perto → NORMAL
        for i in range(10):
            repo.criar_equipamento(c, eq(f"N{i}", bairro="Norte", latitude=-21.70, longitude=-47.60))
        # Sul: 4 equipamentos, metade quebrada → CRÍTICA (disponibilidade 50%)
        for i in range(2):
            repo.criar_equipamento(c, eq(f"SO{i}", bairro="Sul", latitude=-21.90, longitude=-47.60))
        for i in range(2):
            repo.criar_equipamento(c, eq(f"SM{i}", bairro="Sul", latitude=-21.90, longitude=-47.60, situacao="mau_funcionamento"))
        # Leste: 10 equipamentos, 8 operacionais (80%) → ATENÇÃO (abaixo da meta de 90%)
        for i in range(8):
            repo.criar_equipamento(c, eq(f"L{i}", bairro="Leste", latitude=-21.80, longitude=-47.50))
        for i in range(2):
            repo.criar_equipamento(c, eq(f"LD{i}", bairro="Leste", latitude=-21.80, longitude=-47.50, situacao="desativado"))
        repo.criar_agente(c, {"nome": "Ana", "matricula": "A1", "funcao": "guarda_municipal", "situacao": "em_atividade",
                              "latitude": -21.70, "longitude": -47.60})
        repo.criar_agente(c, {"nome": "Beto", "matricula": "A2", "funcao": "guarda_municipal", "situacao": "em_atividade",
                              "latitude": -21.80, "longitude": -47.50})
        repo.criar_agente(c, {"nome": "Caio", "matricula": "A3", "funcao": "guarda_municipal", "situacao": "em_atividade",
                              "latitude": -21.90, "longitude": -47.60})
        telemetria.semear(c, AGORA, mudos=0)      # cenário controlado: ninguém mudo, a menos que o teste peça
        telemetria.tick(c, AGORA)

    def test_classificacao(self):
        with sessao(self.path) as c:
            self.montar(c)
            r = operacao.regioes(c, AGORA)
        por = {x["bairro"]: x for x in r["regioes"]}
        self.assertEqual({b: x["status"] for b, x in por.items()}, {"Norte": "normal", "Sul": "critico", "Leste": "atencao"})
        self.assertEqual(por["Sul"]["disponibilidade"], 0.5)
        self.assertEqual((por["Sul"]["instalados"], por["Sul"]["operacionais"], por["Sul"]["indisponiveis"]), (4, 2, 2))
        self.assertEqual(por["Leste"]["indisponiveis"], 2)
        self.assertEqual(por["Norte"]["motivos"], ["Operando dentro das metas"])
        self.assertEqual(r["resumo"], {"critico": 1, "atencao": 1, "normal": 1})
        self.assertEqual([x["bairro"] for x in r["regioes"]], ["Sul", "Leste", "Norte"])     # mais grave primeiro

    def test_agentes_por_regiao_e_regra_do_agente_ausente(self):
        with sessao(self.path) as c:
            self.montar(c)
            c.execute("UPDATE agente SET situacao = 'fora_de_servico' WHERE matricula = 'A1'")
            por = {x["bairro"]: x for x in operacao.regioes(c, AGORA)["regioes"]}
        self.assertEqual(por["Norte"]["agentes_ativos"], 0)
        self.assertEqual(por["Norte"]["status"], "atencao")                                  # operacional, mas sem agente
        self.assertIn("Nenhum agente em atividade na região", por["Norte"]["motivos"])
        self.assertEqual(por["Leste"]["agentes_ativos"], 1)

    def test_sem_sinal_e_manutencao_contam(self):
        with sessao(self.path) as c:
            self.montar(c)
            ids = [r["id"] for r in c.execute("SELECT id FROM equipamento WHERE bairro = 'Norte' LIMIT 2")]
            for i in ids:
                c.execute("UPDATE telemetria SET mudo = 1, recebido_em = ? WHERE equipamento_id = ?",
                          ((AGORA - timedelta(hours=3)).isoformat(timespec="seconds"), i))
            self.assertEqual({x["bairro"]: x for x in operacao.regioes(c, AGORA)["regioes"]}["Norte"]["status"], "critico")
            ontem = (date(2026, 10, 24) - timedelta(days=3)).isoformat()
            alvo = repo.criar_equipamento(c, eq("VENC", bairro="Leste", manutencao_tipo="agendada", proxima_manutencao=ontem))
            por = {x["bairro"]: x for x in operacao.regioes(c, AGORA)["regioes"]}
        self.assertEqual(por["Norte"]["sem_sinal"], 2)
        self.assertEqual(por["Leste"]["manutencao_vencida"], 1)

    def test_regras_e_banco_vazio(self):
        with sessao(self.path) as c:
            r = operacao.regioes(c, AGORA)
        self.assertEqual((r["regioes"], r["resumo"]), ([], {"critico": 0, "atencao": 0, "normal": 0}))
        self.assertIn("90%", r["regras"]["texto"])
        self.assertIn("75%", r["regras"]["texto"])


if __name__ == "__main__":
    unittest.main()

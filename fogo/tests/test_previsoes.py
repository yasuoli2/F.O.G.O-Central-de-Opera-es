import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from app import predict, repo
from app.db import iniciar, sessao
from app.seed import semear

HOJE = date(2026, 10, 22)


def equipamento_valido(**extra):
    d = {"tipo": "radar_velocidade", "numero_serie": "T-0001", "marca": "Fiscal-Tech", "modelo": "FT-200",
         "situacao": "operacional", "cep": "13500000", "bairro": "Centro", "cidade_uf": "Cidade Modelo/SP",
         "rua": "Av. Brasil", "referencia": "número 181", "latitude": -21.8, "longitude": -47.6,
         "atributos": {"limite_kmh": 60}}
    d.update(extra)
    return d


def evento(c, eid, dias_atras, tipo="falha", hora=10):
    quando = datetime.combine(HOJE - timedelta(days=dias_atras), datetime.min.time()).replace(hour=hora)
    c.execute("INSERT INTO evento (equipamento_id, tipo, descricao, ocorrido_em) VALUES (?,?,?,?)",
              (eid, tipo, "teste", quando.isoformat(timespec="minutes")))


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        iniciar(self.path)

    def tearDown(self):
        os.remove(self.path)


class TestRisco(Base):
    def test_equipamento_com_historico_e_manutencao_velha_supera_o_limpo(self):
        with sessao(self.path) as c:
            ruim = repo.criar_equipamento(c, equipamento_valido(
                numero_serie="RUIM", ultima_manutencao=(HOJE - timedelta(days=400)).isoformat()))["id"]
            bom = repo.criar_equipamento(c, equipamento_valido(
                numero_serie="BOM", ultima_manutencao=(HOJE - timedelta(days=10)).isoformat()))["id"]
            for d in (2, 5, 9, 20, 40):
                evento(c, ruim, d)
            r = {e["numero_serie"]: e for e in predict.previsoes(c, HOJE)["equipamentos"]}
        self.assertGreater(r["RUIM"]["risco"], r["BOM"]["risco"] + 30)
        self.assertTrue(any("400 dias" in m for m in r["RUIM"]["motivos"]))
        self.assertTrue(0 <= r["BOM"]["risco"] <= 100)
        self.assertEqual(r["BOM"]["nivel"], "baixo")

    def test_nao_instalado_e_furtado_ficam_de_fora(self):
        with sessao(self.path) as c:
            repo.criar_equipamento(c, equipamento_valido(numero_serie="A", situacao="nao_instalado"))
            repo.criar_equipamento(c, equipamento_valido(numero_serie="B", situacao="furtado"))
            self.assertEqual(predict.previsoes(c, HOJE)["equipamentos"], [])

    def test_banco_vazio_nao_quebra(self):
        with sessao(self.path) as c:
            r = predict.previsoes(c, HOJE)
        self.assertEqual(r["equipamentos"], [])
        self.assertFalse(r["validacao"]["valido"])
        self.assertTrue(r["briefing"])


class TestAnomaliaEDemo(Base):
    def test_rajada_e_detectada_e_limpa(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, equipamento_valido(numero_serie="X"))["id"]
            evento(c, eid, 100)                               # histórico calmo
            self.assertEqual(predict.anomalias(*predict._carregar(c, HOJE)[:2], HOJE), [])
            info = predict.simular_rajada(c, eid, n=6, hoje=HOJE, semente=1)
            self.assertEqual(info["numero_serie"], "X")
            achados = predict.anomalias(*predict._carregar(c, HOJE)[:2], HOJE)
            self.assertEqual([a["id"] for a in achados], [eid])
            self.assertEqual(predict.limpar_rajada(c), 6)
            self.assertEqual(predict.anomalias(*predict._carregar(c, HOJE)[:2], HOJE), [])

    def test_poisson(self):
        self.assertAlmostEqual(predict._poisson_cauda(1, 1.0), 1 - 2.718281828 ** -1, places=6)
        self.assertEqual(predict._poisson_cauda(0, 5), 1.0)
        self.assertLess(predict._poisson_cauda(8, 1.0), 0.001)


class TestComSeed(Base):
    def setUp(self):
        super().setUp()
        with sessao(self.path) as c:
            semear(c)
            self.r = predict.previsoes(c)

    def test_estrutura_e_limites(self):
        r = self.r
        for chave in ("briefing", "equipamentos", "bairros", "mapa_calor", "recomendacoes",
                      "proximos_dias", "anomalias", "validacao", "faixas", "dias_semana"):
            self.assertIn(chave, r)
        self.assertTrue(all(0 <= e["risco"] <= 100 and e["motivos"] for e in r["equipamentos"]))
        riscos = [e["risco"] for e in r["equipamentos"]]
        self.assertEqual(riscos, sorted(riscos, reverse=True))
        self.assertEqual(sum(r["resumo"]["por_nivel"].values()), len(r["equipamentos"]))
        self.assertEqual(r["bairros"][0]["indice"], 100.0)

    def test_mapa_calor_e_proximos_dias(self):
        m = self.r["mapa_calor"]["Cidade toda"]
        self.assertEqual((len(m), len(m[0])), (7, 6))
        pd = self.r["proximos_dias"]
        self.assertEqual(len(pd["datas"]), 7)
        self.assertTrue(all(len(v) == 7 and min(v) >= 0 for v in pd["bairros"].values()))

    def test_recomendacao_menciona_faixa_e_base(self):
        self.assertTrue(self.r["recomendacoes"])
        txt = self.r["recomendacoes"][0]["texto"]
        self.assertIn("Reforçar", txt)
        self.assertIn("Base:", txt)
        self.assertNotIn("são as sábados", " ".join(x["texto"] for x in self.r["recomendacoes"]))

    def test_validacao_bate_melhor_que_o_acaso(self):
        v = self.r["validacao"]
        self.assertTrue(v["valido"])
        self.assertGreater(v["equipamentos"]["captura"], v["equipamentos"]["captura_acaso"])
        self.assertGreaterEqual(v["bairros"]["acertos"], 2)

    def test_validacao_nao_usa_o_futuro(self):
        """Despejar eventos DEPOIS da data de corte não pode mudar o que o treino previu."""
        with sessao(self.path) as c:
            hoje = date.today()
            eqs, evs, _ = predict._carregar(c, hoje)
            corte = hoje - timedelta(days=30)
            antes = predict.validar(eqs, evs, hoje)
            # um bairro "calmo" recebe uma avalanche de eventos só no período de teste
            alvo = next(e for e in eqs if e["bairro"] not in antes["bairros"]["previstos"]
                        and e["situacao"] != "nao_instalado")
            futuro = datetime.combine(corte + timedelta(days=2), datetime.min.time())
            extra = [(alvo["id"], futuro, 2.0)] * 200
            depois = predict.validar(eqs, evs + extra, hoje)
        self.assertEqual(antes["eventos_treino"], depois["eventos_treino"])
        self.assertEqual(depois["eventos_teste"], antes["eventos_teste"] + 200)
        self.assertEqual(antes["bairros"]["previstos"], depois["bairros"]["previstos"])
        self.assertNotEqual(antes["bairros"]["reais"], depois["bairros"]["reais"])   # o teste muda, o treino não


class TestRecomendacao(unittest.TestCase):
    def test_concordancia_e_poucos_dados(self):
        mat = [[0.0] * 6 for _ in range(7)]
        self.assertIsNone(predict.recomendacao_bairro("X", mat))
        mat[5][5] = 10.0
        t = predict.recomendacao_bairro("X", mat)["texto"]
        self.assertIn("20h–00h", t)
        self.assertIn("os sábados", t)
        mat = [[0.0] * 6 for _ in range(7)]
        mat[4][1] = 10.0
        self.assertIn("as sextas", predict.recomendacao_bairro("X", mat)["texto"])


if __name__ == "__main__":
    unittest.main()

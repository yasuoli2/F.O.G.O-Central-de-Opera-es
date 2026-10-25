import os
import tempfile
import unittest

from app import catalogo, repo
from app.db import iniciar, sessao
from app.seed import semear


def equipamento_valido(**extra):
    d = {"tipo": "radar_velocidade", "numero_serie": "T-0001", "marca": "Fiscal-Tech", "modelo": "FT-200",
         "situacao": "operacional", "cep": "13500000", "bairro": "Centro", "cidade_uf": "Cidade Modelo/SP",
         "rua": "Av. Brasil", "referencia": "número 181", "latitude": -21.8, "longitude": -47.6,
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


class TestValidacao(unittest.TestCase):
    def test_valido_normaliza_cep_e_manutencao(self):
        v = catalogo.validar_equipamento(equipamento_valido())
        self.assertEqual(v["cep"], "13500-000")
        self.assertEqual(v["manutencao_tipo"], "nenhuma")

    def test_mau_funcionamento_gera_manutencao_imediata(self):
        v = catalogo.validar_equipamento(equipamento_valido(situacao="mau_funcionamento"))
        self.assertEqual(v["manutencao_tipo"], "imediata")

    def test_atributo_obrigatorio_do_tipo(self):
        with self.assertRaises(catalogo.ValidacaoErro) as e:
            catalogo.validar_equipamento(equipamento_valido(atributos={}))
        self.assertIn("atributos.limite_kmh", e.exception.erros[0])

    def test_atributo_de_outro_tipo_rejeitado(self):
        with self.assertRaises(catalogo.ValidacaoErro):
            catalogo.validar_equipamento(equipamento_valido(atributos={"limite_kmh": 60, "visao_noturna": True}))

    def test_limites_e_formatos(self):
        casos = [dict(latitude=120), dict(cep="123"), dict(cidade_uf="SemBarra"), dict(tipo="foguete"),
                 dict(situacao="quebrado"), dict(atributos={"limite_kmh": 500}),
                 dict(manutencao_tipo="agendada"), dict(ultima_manutencao="31/12/2025")]
        for extra in casos:
            with self.subTest(extra=extra), self.assertRaises(catalogo.ValidacaoErro):
                catalogo.validar_equipamento(equipamento_valido(**extra))

    def test_camera_booleanos(self):
        ok = equipamento_valido(tipo="camera", atributos={"visao_noturna": True, "resolucao": "4K", "colorida": False})
        self.assertTrue(catalogo.validar_equipamento(ok)["atributos"]["visao_noturna"])
        ruim = equipamento_valido(tipo="camera", atributos={"visao_noturna": "sim", "resolucao": "4K", "colorida": False})
        with self.assertRaises(catalogo.ValidacaoErro):
            catalogo.validar_equipamento(ruim)

    def test_agente(self):
        with self.assertRaises(catalogo.ValidacaoErro):
            catalogo.validar_agente({"nome": "A", "matricula": "1", "funcao": "x"})
        with self.assertRaises(catalogo.ValidacaoErro):
            catalogo.validar_agente({"nome": "A", "matricula": "1", "funcao": "guarda_municipal", "latitude": 1})


class TestCrud(Base):
    def test_ciclo_completo_equipamento(self):
        with sessao(self.path) as c:
            criado = repo.criar_equipamento(c, equipamento_valido())
            eid = criado["id"]
            self.assertEqual(criado["atributos"], {"limite_kmh": 60})
            novo = repo.atualizar_equipamento(c, eid, {"situacao": "mau_funcionamento"})
            self.assertEqual((novo["situacao"], novo["manutencao_tipo"]), ("mau_funcionamento", "imediata"))
            volta = repo.atualizar_equipamento(c, eid, {"situacao": "operacional"})
            self.assertEqual(volta["manutencao_tipo"], "nenhuma")
            self.assertEqual(volta["numero_serie"], "T-0001")           # campos não enviados ficam
            trocado = repo.atualizar_equipamento(c, eid, {"tipo": "camera", "atributos":
                         {"visao_noturna": True, "resolucao": "1080p", "colorida": True}})
            self.assertEqual(trocado["tipo"], "camera")
            repo.excluir_equipamento(c, eid)
            with self.assertRaises(repo.NaoEncontrado):
                repo.obter_equipamento(c, eid)

    def test_serie_duplicada(self):
        import sqlite3
        with sessao(self.path) as c:
            repo.criar_equipamento(c, equipamento_valido())
        with self.assertRaises(sqlite3.IntegrityError), sessao(self.path) as c:
            repo.criar_equipamento(c, equipamento_valido())

    def test_update_invalido_nao_altera(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, equipamento_valido())["id"]
            with self.assertRaises(catalogo.ValidacaoErro):
                repo.atualizar_equipamento(c, eid, {"latitude": 999})
            self.assertEqual(repo.obter_equipamento(c, eid)["latitude"], -21.8)

    def test_agente_e_vinculo_com_equipamento(self):
        with sessao(self.path) as c:
            eid = repo.criar_equipamento(c, equipamento_valido(tipo="viatura", numero_serie="V-1",
                       atributos={"corporacao": "guarda_municipal", "placa": "ABC1D23"}))["id"]
            a = repo.criar_agente(c, {"nome": "Ana Silva", "matricula": "AG-9", "funcao": "guarda_municipal",
                                      "situacao": "em_atividade", "latitude": -21.8, "longitude": -47.6,
                                      "equipamento_id": eid})
            self.assertIsNotNone(a["ultima_posicao_em"])
            repo.excluir_equipamento(c, eid)                           # ON DELETE SET NULL
            self.assertIsNone(repo.obter_agente(c, a["id"])["equipamento_id"])


class TestSeedEFiltros(Base):
    def test_seed_cria_dados_validos_e_so_roda_uma_vez(self):
        with sessao(self.path) as c:
            r = semear(c)
            self.assertGreater(r["equipamentos"], 100)
            self.assertGreater(r["eventos"], 100)
            self.assertIsNone(semear(c))                                # idempotente
            # todo equipamento semeado precisa passar na validação oficial
            for e in repo.listar_equipamentos(c, limite=2000)["itens"]:
                catalogo.validar_equipamento(e)
            for a in repo.listar_agentes(c)["itens"]:
                catalogo.validar_agente(a)

    def test_filtros(self):
        with sessao(self.path) as c:
            semear(c)
            todos = repo.listar_equipamentos(c, limite=2000)
            cams = repo.listar_equipamentos(c, tipo="camera", limite=2000)
            self.assertTrue(0 < cams["total"] < todos["total"])
            self.assertTrue(all(e["tipo"] == "camera" for e in cams["itens"]))
            op = repo.listar_equipamentos(c, situacao="operacional", bairro="Centro", limite=2000)
            self.assertTrue(all(e["situacao"] == "operacional" and e["bairro"] == "Centro" for e in op["itens"]))
            self.assertEqual(len(repo.listar_equipamentos(c, limite=5)["itens"]), 5)
            self.assertGreater(repo.listar_agentes(c, situacao="em_atividade")["total"], 0)


if __name__ == "__main__":
    unittest.main()

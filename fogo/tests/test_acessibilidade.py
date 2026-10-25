"""Acessibilidade (WCAG 2.1 AA) e contraste das páginas estáticas. Só biblioteca padrão."""
import glob
import os
import re
import unittest
from html.parser import HTMLParser


STATIC = os.path.join(os.path.dirname(__file__), "..", "app", "static")


def ler(nome):
    with open(os.path.join(STATIC, nome), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ contraste
def _lum(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def razao(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def misturar(fg, bg, alfa):
    fg, bg = fg.lstrip("#"), bg.lstrip("#")
    return "#" + "".join("%02x" % round(int(fg[i:i + 2], 16) * alfa + int(bg[i:i + 2], 16) * (1 - alfa)) for i in (0, 2, 4))


def variaveis(css):
    bloco = re.search(r":root\s*\{(.*?)\n?\}", css, re.S).group(1)
    return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*(?:;|$)", bloco))


# (texto, fundo, mínimo): 4,5 para texto normal; 3,0 para foco e bordas de componentes (WCAG 1.4.11)
PARES_INDEX = [
    ("aside-fg", "aside-bg", 4.5), ("aside-fg", "aside-card", 4.5), ("aside-muted", "aside-bg", 4.5),
    ("aside-muted", "aside-card", 4.5), ("aside-link", "aside-bg", 4.5), ("tabs-fg", "aside-card", 4.5),
    ("acento-fg", "acento-bg", 4.5), ("branco", "n-critico", 4.5), ("branco", "n-alto", 4.5),
    ("branco", "n-medio", 4.5), ("branco", "n-baixo", 4.5), ("n-baixo", "card-bg", 4.5),
    ("tendencia-alta", "card-bg", 4.5), ("tendencia-queda", "card-bg", 4.5), ("muted", "painel-bg", 4.5),
    ("muted", "card-bg", 4.5), ("muted", "stat-bg", 4.5), ("fg", "painel-bg", 4.5), ("fg", "rec-bg", 4.5),
    ("aviso-fg", "aviso-bg", 4.5), ("ok-fg", "ok-bg", 4.5), ("link", "card-bg", 4.5), ("link", "painel-bg", 4.5),
    ("campo-fg", "campo-bg", 4.5), ("campo-placeholder", "campo-bg", 4.5), ("branco", "fg", 4.5),
    ("foco-escuro", "aside-bg", 3.0), ("foco-escuro", "tabs-bg", 3.0), ("foco-claro", "painel-bg", 3.0),
    ("foco-claro", "card-bg", 3.0), ("borda", "card-bg", 3.0), ("borda", "aside-bg", 3.0),
]

class TestContraste(unittest.TestCase):
    def _checar(self, vars_, pares):
        for fg, bg, minimo in pares:
            with self.subTest(par=f"{fg} sobre {bg}"):
                a = vars_.get(fg, fg)
                b = vars_.get(bg, bg)
                self.assertRegex(a, r"^#[0-9a-fA-F]{6}$", f"variável --{fg} não encontrada")
                self.assertRegex(b, r"^#[0-9a-fA-F]{6}$", f"variável --{bg} não encontrada")
                self.assertGreaterEqual(razao(a, b), minimo, f"{a} sobre {b} = {razao(a, b):.2f}")

    def test_pagina_principal(self):
        self._checar(variaveis(ler("index.html")), PARES_INDEX)

    def test_mapa_de_calor_texto_escuro_em_todas_as_intensidades(self):
        html = ler("index.html")
        v = variaveis(html)
        alfa_max = float(re.search(r"ALPHA_MAX\s*=\s*([0-9.]+)", html).group(1))
        for i in range(0, 101, 5):
            alfa = 0.08 + (alfa_max - 0.08) * i / 100
            fundo = misturar(v["calor"], v["card-bg"], alfa)
            with self.subTest(intensidade=i):
                self.assertGreaterEqual(razao(v["fg"], fundo), 4.5, f"{fundo}")

    def test_o_teste_de_contraste_pega_erros(self):
        """Garante que a medição funciona: branco sobre o laranja antigo (#f97316) tem que reprovar."""
        self.assertLess(razao("#ffffff", "#f97316"), 4.5)
        self.assertLess(razao("#ffffff", "#eab308"), 3.0)


# ------------------------------------------------------------------ estrutura
class Estrutura(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.labels_for, self.ids, self.campos = [], set(), set(), []
        self.dentro_label = 0
        self.imgs_sem_alt, self.tabindex_pos, self.h1 = [], [], 0
        self.lang = None
        self.title = ""
        self._em_title = False
        self.botoes_vazios = []
        self._btn = None
        self.links_vazios = []
        self._a = None
        self.skip = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self._em_title = True
        if tag == "h1":
            self.h1 += 1
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "label":
            self.dentro_label += 1
            if "for" in a:
                self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            self.campos.append((tag, a, self.dentro_label > 0))
        if tag == "img" and "alt" not in a:
            self.imgs_sem_alt.append(a)
        if "tabindex" in a and a["tabindex"].lstrip("-").isdigit() and int(a["tabindex"]) > 0:
            self.tabindex_pos.append(a)
        if tag == "a" and a.get("class") == "pular" and a.get("href", "").startswith("#"):
            self.skip = True
        if tag == "button":
            self._btn = [a, ""]
        if tag == "a":
            self._a = [a, ""]

    def handle_endtag(self, tag):
        if tag == "title":
            self._em_title = False
        if tag == "label":
            self.dentro_label -= 1
        if tag == "button" and self._btn:
            a, txt = self._btn
            if not txt.strip() and not a.get("aria-label"):
                self.botoes_vazios.append(a)
            self._btn = None
        if tag == "a" and self._a:
            a, txt = self._a
            if not txt.strip() and not a.get("aria-label"):
                self.links_vazios.append(a)
            self._a = None

    def handle_data(self, d):
        if self._em_title:
            self.title += d
        if self._btn:
            self._btn[1] += d
        if self._a:
            self._a[1] += d


def analisar(nome):
    p = Estrutura()
    p.feed(ler(nome))
    return p


PAGINAS = ["index.html"]


class TestEstrutura(unittest.TestCase):
    def test_basico_de_cada_pagina(self):
        for nome in PAGINAS:
            p = analisar(nome)
            with self.subTest(pagina=nome):
                self.assertEqual(p.lang, "pt-BR")
                self.assertTrue(p.title.strip())
                self.assertEqual(p.h1, 1, "deve haver exatamente um <h1>")
                self.assertTrue(p.skip, "falta o link 'Pular para o conteúdo'")
                self.assertEqual(p.tabindex_pos, [], "tabindex positivo atrapalha a ordem do teclado")
                self.assertEqual(p.imgs_sem_alt, [])
                self.assertEqual(p.botoes_vazios, [], "botão sem texto acessível")
                self.assertEqual(p.links_vazios, [], "link sem texto acessível")

    def test_todo_campo_tem_rotulo(self):
        for nome in PAGINAS:
            p = analisar(nome)
            for tag, a, em_label in p.campos:
                with self.subTest(pagina=nome, campo=a.get("id")):
                    ok = em_label or a.get("id") in p.labels_for or a.get("aria-label") or a.get("aria-labelledby")
                    self.assertTrue(ok, f"<{tag} id={a.get('id')}> sem rótulo")


    def test_abas_seguem_o_padrao_aria(self):
        html = ler("index.html")
        for trecho in ('role="tablist"', 'role="tab"', 'role="tabpanel"', 'aria-selected', 'aria-controls', 'aria-labelledby'):
            self.assertIn(trecho, html)
        self.assertIn('role="status"', html)                                # região viva para anúncios
        self.assertIn("<caption", html)                                     # tabelas com legenda




class TestCssAcessivel(unittest.TestCase):
    def test_foco_nunca_e_removido(self):
        for nome in ("index.html",):
            css = ler(nome)
            with self.subTest(arquivo=nome):
                self.assertNotRegex(css, r"outline\s*:\s*(none|0)\b")
                self.assertIn(":focus-visible", css)

    def test_respeita_movimento_reduzido(self):
        for nome in ("index.html",):
            self.assertIn("prefers-reduced-motion", ler(nome))
        self.assertIn("REDUZ", ler("index.html"))

    def test_texto_nao_fica_pequeno_demais(self):
        for nome in ("index.html",):
            for valor, unidade in re.findall(r"font-size\s*:\s*([0-9.]+)(px|rem)", ler(nome)):
                px = float(valor) * (16 if unidade == "rem" else 1)
                with self.subTest(arquivo=nome, tamanho=valor + unidade):
                    self.assertGreaterEqual(px, 13, "texto menor que 13 px")

    def test_tamanhos_em_unidades_relativas_no_corpo(self):
        self.assertRegex(ler("index.html"), r"body\{[^}]*font:0\.9375rem")


class TestCursorDoMapa(unittest.TestCase):
    def test_cursor_proprio_com_contorno_e_alternativa(self):
        html = ler("index.html")
        m = re.search(r"--cursor-mapa:url\(\"data:image/svg\+xml,(.*?)\"\)\s*16 16,\s*crosshair", html, re.S)
        self.assertIsNotNone(m, "cursor do mapa não definido com ponto ativo e alternativa")
        svg = m.group(1)
        self.assertIn("stroke='white'", svg)               # contorno claro
        self.assertIn("%230f172a", svg)                    # traço escuro: visível em fundo claro e escuro
        self.assertNotIn("<", svg)                         # codificado como URL

    def test_leaflet_nao_sobrescreve_o_cursor(self):
        html = ler("index.html")
        self.assertRegex(html, r"\.leaflet-container\.leaflet-grab[^{]*\{cursor:var\(--cursor-mapa\)!important\}")
        self.assertIn(".leaflet-dragging .leaflet-grab", html)
        self.assertRegex(html, r"\.leaflet-interactive[^{]*\{cursor:pointer!important\}")

    def test_realce_ao_passar_o_mouse_independe_do_cursor(self):
        self.assertIn(".leaflet-marker-icon:hover .pino", ler("index.html"))   # realce por CSS, não depende do cursor



if __name__ == "__main__":
    unittest.main()

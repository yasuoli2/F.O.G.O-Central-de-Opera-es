"""Catálogo de tipos, situações e regras de validação do F.O.G.O.

Só usa a biblioteca padrão: pode ser testado sem instalar nada.
"""
from datetime import date

SITUACOES = {
    "nao_instalado": "Ainda não instalado",
    "operacional": "Operacional",
    "mau_funcionamento": "Mau funcionamento",
    "em_manutencao": "Em manutenção",
    "desativado": "Desativado",
    "furtado": "Furtado",
}
MANUTENCOES = {"nenhuma": "Nenhuma", "imediata": "Imediata", "agendada": "Agendada/periódica"}
FUNCOES_AGENTE = {
    "agente_transito": "Agente de trânsito",
    "guarda_municipal": "Guarda municipal",
    "policial_militar": "Policial militar",
}
SITUACOES_AGENTE = {"em_atividade": "Em atividade", "fora_de_servico": "Fora de serviço", "afastado": "Afastado"}
TIPOS_EVENTO = {
    "falha": "Falha",
    "furto": "Furto",
    "vandalismo": "Vandalismo",
    "manutencao": "Manutenção realizada",
    "alerta": "Alerta",
}


def _campo(nome, rotulo, tipo, obrigatorio=True, opcoes=None, minimo=None, maximo=None):
    return {"nome": nome, "rotulo": rotulo, "tipo": tipo, "obrigatorio": obrigatorio,
            "opcoes": opcoes, "minimo": minimo, "maximo": maximo}


# Cada tipo declara as "outras características" próprias dele.
# O front-end usa /api/tipos para montar o formulário dinamicamente.
TIPOS = {
    "radar_velocidade": {"rotulo": "Radar de velocidade", "campos": [
        _campo("limite_kmh", "Velocidade máxima (km/h)", "inteiro", minimo=10, maximo=120),
        _campo("faixas", "Faixas monitoradas", "inteiro", obrigatorio=False, minimo=1, maximo=8)]},
    "radar_semaforo": {"rotulo": "Radar de semáforo", "campos": [
        _campo("faixas", "Faixas monitoradas", "inteiro", obrigatorio=False, minimo=1, maximo=8)]},
    "radar_conversao": {"rotulo": "Radar de conversão/retorno proibido", "campos": [
        _campo("tipo_infracao", "Infração fiscalizada", "opcao",
               opcoes=["conversao_proibida", "retorno_proibido", "parada_faixa_pedestre"])]},
    "camera": {"rotulo": "Câmera de videomonitoramento", "campos": [
        _campo("visao_noturna", "Visão noturna", "booleano"),
        _campo("resolucao", "Resolução", "opcao", opcoes=["720p", "1080p", "4K"]),
        _campo("colorida", "Imagem colorida", "booleano")]},
    "balanca": {"rotulo": "Balança de caminhão", "campos": [
        _campo("capacidade_ton", "Capacidade (t)", "numero", minimo=1, maximo=200)]},
    "veiculo_autonomo": {"rotulo": "Veículo autônomo de fiscalização", "campos": [
        _campo("autonomia_km", "Autonomia (km)", "numero", obrigatorio=False, minimo=1, maximo=1000)]},
    "cancela": {"rotulo": "Cancela automatizada", "campos": [
        _campo("tipo_acesso", "Tipo de acesso", "opcao", opcoes=["estacionamento", "via_restrita", "terminal"])]},
    "veiculo_transporte": {"rotulo": "Veículo de transporte", "campos": [
        _campo("categoria", "Categoria", "opcao", opcoes=["taxi", "mototaxi", "escolar"]),
        _campo("placa", "Placa", "texto")]},
    "totem_estacionamento": {"rotulo": "Totem de estacionamento rotativo", "campos": [
        _campo("aceita_pix", "Aceita PIX", "booleano"),
        _campo("vagas_atendidas", "Vagas atendidas", "inteiro", obrigatorio=False, minimo=1, maximo=500)]},
    "patinete": {"rotulo": "Patinete elétrico compartilhado", "campos": [
        _campo("bateria_pct", "Bateria (%)", "inteiro", minimo=0, maximo=100)]},
    "moto_agente": {"rotulo": "Moto de agente de trânsito", "campos": [
        _campo("placa", "Placa", "texto")]},
    "viatura": {"rotulo": "Viatura", "campos": [
        _campo("corporacao", "Corporação", "opcao", opcoes=["guarda_municipal", "policia_militar", "transito"]),
        _campo("placa", "Placa", "texto")]},
}

# Equipamentos que se movem: a localização é a da base de operação.
MOVEIS = {"veiculo_autonomo", "veiculo_transporte", "patinete", "moto_agente", "viatura"}


class ValidacaoErro(Exception):
    def __init__(self, erros):
        super().__init__("; ".join(erros))
        self.erros = erros


def _vazio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _data(valor, nome, erros):
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except ValueError:
        erros.append(f"{nome}: use o formato AAAA-MM-DD")
        return None


def _validar_atributos(tipo, atributos, erros):
    if not isinstance(atributos, dict):
        erros.append("atributos: deve ser um objeto")
        return {}
    campos = {c["nome"]: c for c in TIPOS[tipo]["campos"]}
    for chave in atributos:
        if chave not in campos:
            erros.append(f"atributos.{chave}: não existe para o tipo '{tipo}'")
    limpo = {}
    for nome, c in campos.items():
        v = atributos.get(nome)
        if _vazio(v):
            if c["obrigatorio"]:
                erros.append(f"atributos.{nome}: obrigatório para '{tipo}'")
            continue
        t = c["tipo"]
        if t == "booleano":
            if not isinstance(v, bool):
                erros.append(f"atributos.{nome}: deve ser verdadeiro ou falso")
                continue
        elif t in ("inteiro", "numero"):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (t == "inteiro" and int(v) != v):
                erros.append(f"atributos.{nome}: deve ser {'inteiro' if t == 'inteiro' else 'numérico'}")
                continue
            if c["minimo"] is not None and v < c["minimo"] or c["maximo"] is not None and v > c["maximo"]:
                erros.append(f"atributos.{nome}: fora do intervalo {c['minimo']}–{c['maximo']}")
                continue
            v = int(v) if t == "inteiro" else float(v)
        elif t == "opcao":
            if v not in c["opcoes"]:
                erros.append(f"atributos.{nome}: use um de {c['opcoes']}")
                continue
        else:
            v = str(v).strip()
        limpo[nome] = v
    return limpo


def validar_equipamento(d):
    """Valida um equipamento COMPLETO e devolve o dicionário limpo (ou levanta ValidacaoErro)."""
    erros, o = [], {}

    for k in ("numero_serie", "marca", "modelo", "rua", "bairro", "cidade_uf"):
        if _vazio(d.get(k)):
            erros.append(f"{k}: obrigatório")
        else:
            o[k] = str(d[k]).strip()

    tipo = d.get("tipo")
    if tipo not in TIPOS:
        erros.append(f"tipo: use um de {sorted(TIPOS)}")
    o["tipo"] = tipo

    situacao = d.get("situacao", "operacional")
    if situacao not in SITUACOES:
        erros.append(f"situacao: use um de {sorted(SITUACOES)}")
    o["situacao"] = situacao

    if o.get("cidade_uf") and "/" not in o["cidade_uf"]:
        erros.append("cidade_uf: use o formato Cidade/UF")

    cep = d.get("cep")
    if _vazio(cep):
        o["cep"] = None
    else:
        digitos = "".join(ch for ch in str(cep) if ch.isdigit())
        if len(digitos) != 8:
            erros.append("cep: deve ter 8 dígitos")
        else:
            o["cep"] = f"{digitos[:5]}-{digitos[5:]}"

    o["referencia"] = "S/N" if _vazio(d.get("referencia")) else str(d["referencia"]).strip()
    o["orgao"] = None if _vazio(d.get("orgao")) else str(d["orgao"]).strip()

    for k, lim in (("latitude", 90), ("longitude", 180)):
        try:
            v = float(d.get(k))
            if abs(v) > lim:
                raise ValueError
            o[k] = v
        except (TypeError, ValueError):
            erros.append(f"{k}: número entre -{lim} e {lim}")

    manut = d.get("manutencao_tipo")
    if _vazio(manut):
        manut = "imediata" if situacao in ("mau_funcionamento", "em_manutencao") else "nenhuma"
    if manut not in MANUTENCOES:
        erros.append(f"manutencao_tipo: use um de {sorted(MANUTENCOES)}")
    o["manutencao_tipo"] = manut

    for k in ("proxima_manutencao", "ultima_manutencao", "data_instalacao"):
        o[k] = None if _vazio(d.get(k)) else _data(d[k], k, erros)
    if manut == "agendada" and not o["proxima_manutencao"]:
        erros.append("proxima_manutencao: obrigatória quando a manutenção é agendada")

    o["atributos"] = _validar_atributos(tipo, d.get("atributos", {}), erros) if tipo in TIPOS else {}

    if erros:
        raise ValidacaoErro(erros)
    return o


def validar_agente(d):
    erros, o = [], {}
    for k in ("nome", "matricula"):
        if _vazio(d.get(k)):
            erros.append(f"{k}: obrigatório")
        else:
            o[k] = str(d[k]).strip()
    if d.get("funcao") not in FUNCOES_AGENTE:
        erros.append(f"funcao: use um de {sorted(FUNCOES_AGENTE)}")
    o["funcao"] = d.get("funcao")
    situacao = d.get("situacao", "fora_de_servico")
    if situacao not in SITUACOES_AGENTE:
        erros.append(f"situacao: use um de {sorted(SITUACOES_AGENTE)}")
    o["situacao"] = situacao
    o["orgao"] = None if _vazio(d.get("orgao")) else str(d["orgao"]).strip()

    for k, lim in (("latitude", 90), ("longitude", 180)):
        if _vazio(d.get(k)):
            o[k] = None
            continue
        try:
            v = float(d[k])
            if abs(v) > lim:
                raise ValueError
            o[k] = v
        except (TypeError, ValueError):
            erros.append(f"{k}: número entre -{lim} e {lim}")
    if (o.get("latitude") is None) != (o.get("longitude") is None):
        erros.append("latitude e longitude devem ser informadas juntas")

    eq = d.get("equipamento_id")
    if _vazio(eq):
        o["equipamento_id"] = None
    elif isinstance(eq, bool) or not isinstance(eq, int):
        erros.append("equipamento_id: deve ser um número inteiro")
    else:
        o["equipamento_id"] = eq
    if erros:
        raise ValidacaoErro(erros)
    return o

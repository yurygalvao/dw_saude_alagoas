"""Configura o Metabase do zero: usuário admin, conexão com o Oracle, perguntas e painel.

Roda sozinho no serviço metabase-init do docker compose. Pode ser executado várias
vezes: atualiza o que já existe pelo nome, sem duplicar.
"""
import json
import os
import time
import urllib.error
import urllib.request

URL = os.getenv("MB_URL", "http://localhost:3000") + "/api"
EMAIL = os.getenv("MB_EMAIL", "dwalagoas@dwalagoas.com")
SENHA = os.getenv("MB_PASSWORD", "dw_password_123")
BANCO = "DW Saúde Alagoas"
COLECAO = "DW Saúde Alagoas"
PAINEL = "SUS Alagoas - Painel de Indicadores Estratégicos"
ORACLE = {
    "host": os.getenv("ORACLE_HOST", "oracle"),
    "port": int(os.getenv("ORACLE_PORT", "1521")),
    "service-name": os.getenv("ORACLE_SERVICE", "FREEPDB1"),
    "user": os.getenv("ORACLE_USER", "DW_ALAGOAS"),
    "password": os.getenv("ORACLE_PASSWORD", "dw_password_123"),
}
BRL = {"number_style": "currency", "currency": "BRL", "currency_style": "symbol"}
sessao = None


def api(metodo, caminho, corpo=None):
    req = urllib.request.Request(URL + caminho, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None)
    req.add_header("Content-Type", "application/json")
    if sessao:
        req.add_header("X-Metabase-Session", sessao)
    with urllib.request.urlopen(req, timeout=120) as r:
        txt = r.read()
        return json.loads(txt) if txt else None


def aguardar_metabase(limite=900):
    inicio = time.time()
    while time.time() - inicio < limite:
        try:
            if api("GET", "/health").get("status") == "ok":
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(10)
    raise TimeoutError("metabase não respondeu")


def configurar_admin():
    global sessao
    props = api("GET", "/session/properties")
    if not props.get("has-user-setup"):
        api("POST", "/setup", {
            "token": props["setup-token"],
            "user": {"first_name": "DW", "last_name": "Alagoas", "email": EMAIL,
                     "password": SENHA, "site_name": BANCO},
            "prefs": {"site_name": BANCO, "site_locale": "pt_BR", "allow_tracking": False},
        })
        print("usuário admin criado:", EMAIL)
    sessao = api("POST", "/session", {"username": EMAIL, "password": SENHA})["id"]


def configurar_banco():
    bancos = api("GET", "/database")["data"]
    for b in bancos:
        if b.get("is_sample"):
            api("DELETE", f"/database/{b['id']}")
    banco = next((b for b in bancos if b["name"] == BANCO), None)
    if banco:
        return banco["id"]
    banco = api("POST", "/database", {"engine": "oracle", "name": BANCO, "details": ORACLE})
    print("conexão com o oracle criada")
    return banco["id"]


def arquivar_exemplos():
    for c in api("GET", "/collection"):
        if c.get("name") == "Examples" and not c.get("archived"):
            api("PUT", f"/collection/{c['id']}", {"archived": True})


def colecao():
    c = next((c for c in api("GET", "/collection")
              if c.get("name") == COLECAO and not c.get("archived")), None)
    return (c or api("POST", "/collection", {"name": COLECAO, "color": "#509EE3"}))["id"]


ANO = "[[AND NR_ANO = {{ano}}]]"

# titulo, tipo de gráfico, sql, configuração visual, usa o filtro de ano, posição (col, linha, largura, altura)
CARDS = [
    ("Gasto SUS total (SIH + SIA)", "scalar",
     f"SELECT SUM(VL_TOTAL) AS VL_TOTAL FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO}",
     {"column_settings": {'["name","VL_TOTAL"]': BRL}, "scalar.compact_primary_number": True},
     True, (0, 0, 6, 3)),
    ("Internações", "scalar",
     f"SELECT SUM(QTD_INTERNACOES) AS QTD FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO}",
     {}, True, (6, 0, 6, 3)),
    ("Procedimentos ambulatoriais", "scalar",
     f"SELECT SUM(QTD_AMBULATORIAL) AS QTD FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO}",
     {"scalar.compact_primary_number": True}, True, (12, 0, 6, 3)),
    ("Custo médio por internação", "scalar",
     f"SELECT ROUND(SUM(VL_HOSPITALAR) / NULLIF(SUM(QTD_INTERNACOES), 0), 2) AS VL "
     f"FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO}",
     {"column_settings": {'["name","VL"]': BRL}}, True, (18, 0, 6, 3)),

    ("P01 · Custo mensal: ambulatorial x hospitalar", "bar",
     f"SELECT ANO_MES, SUM(VL_AMBULATORIAL) AS AMBULATORIAL, SUM(VL_HOSPITALAR) AS HOSPITALAR "
     f"FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO} GROUP BY ANO_MES ORDER BY ANO_MES",
     {"graph.dimensions": ["ANO_MES"], "graph.metrics": ["AMBULATORIAL", "HOSPITALAR"],
      "stackable.stack_type": "stacked", "graph.x_axis.title_text": "Competência",
      "graph.y_axis.title_text": "R$"}, True, (0, 3, 16, 6)),
    ("P01 · Municípios com maior custo", "table",
     f"SELECT NOME_MUNICIPIO AS MUNICIPIO, REGIAO_SAUDE, SUM(QTD_TOTAL) AS ATENDIMENTOS, "
     f"SUM(VL_TOTAL) AS VL_TOTAL FROM MART_P01_CUSTO_VOLUME_MUNICIPIO WHERE 1=1 {ANO} "
     f"GROUP BY NOME_MUNICIPIO, REGIAO_SAUDE ORDER BY VL_TOTAL DESC",
     {"column_settings": {'["name","VL_TOTAL"]': BRL}}, True, (16, 3, 8, 6)),

    ("P02 · Top 5 especialidades por macrorregião", "bar",
     "SELECT NOME_ESPECIALIDADE AS ESPECIALIDADE, MACRORREGIAO, QTD_INTERNACOES "
     "FROM MART_P02_TOP_ESPECIALIDADES ORDER BY MACRORREGIAO, NR_RANKING",
     {"graph.dimensions": ["ESPECIALIDADE", "MACRORREGIAO"], "graph.metrics": ["QTD_INTERNACOES"],
      "graph.show_values": True}, False, (0, 9, 12, 6)),
    ("P03 · Tempo médio de permanência por especialidade (dias)", "row",
     f"SELECT NOME_ESPECIALIDADE AS ESPECIALIDADE, "
     f"ROUND(SUM(QTD_DIAS_PERMANENCIA) / NULLIF(SUM(QTD_INTERNACOES), 0), 1) AS MEDIA_DIAS "
     f"FROM MART_P03_PERMANENCIA_ESPECIALIDADE WHERE 1=1 {ANO} "
     f"GROUP BY NOME_ESPECIALIDADE ORDER BY MEDIA_DIAS DESC",
     {"graph.dimensions": ["ESPECIALIDADE"], "graph.metrics": ["MEDIA_DIAS"],
      "graph.show_values": True}, True, (12, 9, 12, 6)),

    ("P04 · Taxa de ocupação por hospital (%)", "table",
     "SELECT NOME_ESTABELECIMENTO AS HOSPITAL, NOME_MUNICIPIO AS MUNICIPIO, "
     "ROUND(AVG(QTD_LEITOS_SUS)) AS LEITOS_SUS, "
     "ROUND(100 * SUM(QTD_PACIENTES_DIA) / NULLIF(SUM(QTD_LEITOS_DIA), 0), 1) AS PCT_OCUPACAO "
     "FROM MART_P04_OCUPACAO_HOSPITALAR WHERE 1=1 "
     "[[AND SUBSTR(ANO_MES, 1, 4) = TO_CHAR({{ano}})]] "
     "GROUP BY NOME_ESTABELECIMENTO, NOME_MUNICIPIO HAVING AVG(QTD_LEITOS_SUS) >= 10 "
     "ORDER BY PCT_OCUPACAO DESC",
     {"column_settings": {'["name","PCT_OCUPACAO"]': {"show_mini_bar": True}}}, True, (0, 15, 12, 7)),
    ("P05 · Procedimentos com maior variação de custo entre hospitais", "table",
     "SELECT NOME_PROCEDIMENTO AS PROCEDIMENTO, COUNT(*) AS HOSPITAIS, "
     "MIN(VL_CUSTO_MEDIO) AS MENOR_CUSTO, MAX(VL_CUSTO_MEDIO) AS MAIOR_CUSTO, "
     "MAX(VL_CUSTO_MEDIO_ESTADO) AS MEDIA_ESTADO, "
     "ROUND(MAX(VL_CUSTO_MEDIO) / NULLIF(MIN(VL_CUSTO_MEDIO), 0), 1) AS VEZES "
     "FROM MART_P05_CUSTO_PROCEDIMENTO WHERE QTD_INTERNACOES >= 10 AND VL_CUSTO_MEDIO > 0 "
     "GROUP BY NOME_PROCEDIMENTO HAVING COUNT(*) >= 3 ORDER BY VEZES DESC",
     {"column_settings": {'["name","MENOR_CUSTO"]': BRL, '["name","MAIOR_CUSTO"]': BRL,
                          '["name","MEDIA_ESTADO"]': BRL}}, False, (12, 15, 12, 7)),

    ("P06 · Perfil das internações de urgência (faixa etária x sexo)", "bar",
     "SELECT FAIXA_ETARIA, NOME_SEXO AS SEXO, QTD_INTERNACOES FROM MART_P06_PERFIL_URGENCIA "
     "ORDER BY FAIXA_ETARIA",
     {"graph.dimensions": ["FAIXA_ETARIA", "SEXO"], "graph.metrics": ["QTD_INTERNACOES"],
      "stackable.stack_type": "stacked"}, False, (0, 22, 12, 6)),
    ("P07 · Internações por doenças respiratórias (CID J) por mês", "line",
     f"SELECT NR_MES AS MES, TO_CHAR(NR_ANO) AS ANO, QTD_INTERNACOES "
     f"FROM MART_P07_RESPIRATORIAS_MENSAL WHERE 1=1 {ANO} ORDER BY NR_MES",
     {"graph.dimensions": ["MES", "ANO"], "graph.metrics": ["QTD_INTERNACOES"],
      "graph.show_values": True, "graph.x_axis.scale": "ordinal"}, True, (12, 22, 12, 6)),

    ("P08 · % das internações dos polos vindas do interior", "bar",
     f"SELECT POLO, ROUND(AVG(PCT), 1) AS PCT_INTERIOR FROM ("
     f"SELECT NR_ANO, MUNICIPIO_DESTINO AS POLO, SUM(PCT_INTERNACOES_DESTINO) AS PCT "
     f"FROM MART_P08_FLUXO_POLOS WHERE 1=1 {ANO} GROUP BY NR_ANO, MUNICIPIO_DESTINO) "
     f"GROUP BY POLO ORDER BY POLO",
     {"graph.dimensions": ["POLO"], "graph.metrics": ["PCT_INTERIOR"], "graph.show_values": True,
      "graph.y_axis.title_text": "% das internações do polo"}, True, (0, 28, 8, 7)),
    ("P08 · Municípios do interior que mais enviam pacientes aos polos", "bar",
     f"WITH f AS (SELECT MUNICIPIO_ORIGEM, MUNICIPIO_DESTINO AS POLO, SUM(QTD_INTERNACOES) AS INTERNACOES "
     f"FROM MART_P08_FLUXO_POLOS WHERE 1=1 {ANO} GROUP BY MUNICIPIO_ORIGEM, MUNICIPIO_DESTINO), "
     f"top AS (SELECT MUNICIPIO_ORIGEM, SUM(INTERNACOES) AS TOTAL FROM f GROUP BY MUNICIPIO_ORIGEM "
     f"ORDER BY TOTAL DESC FETCH FIRST 15 ROWS ONLY) "
     f"SELECT f.MUNICIPIO_ORIGEM, f.POLO, f.INTERNACOES FROM f JOIN top t ON t.MUNICIPIO_ORIGEM = f.MUNICIPIO_ORIGEM "
     f"ORDER BY t.TOTAL DESC, f.POLO",
     {"graph.dimensions": ["MUNICIPIO_ORIGEM", "POLO"], "graph.metrics": ["INTERNACOES"],
      "stackable.stack_type": "stacked", "graph.x_axis.title_text": "Município de residência"},
     True, (8, 28, 16, 7)),
    ("P09 · Hospitais hub: municípios de origem dos pacientes", "row",
     "SELECT NOME_ESTABELECIMENTO || ' (' || MUNICIPIO_HOSPITAL || ')' AS HOSPITAL, "
     "COUNT(DISTINCT COD_IBGE_ORIGEM) AS MUNICIPIOS_ORIGEM "
     "FROM MART_P09_HUBS_HOSPITALARES GROUP BY COD_CNES, NOME_ESTABELECIMENTO, MUNICIPIO_HOSPITAL "
     "ORDER BY MUNICIPIOS_ORIGEM DESC FETCH FIRST 15 ROWS ONLY",
     {"graph.dimensions": ["HOSPITAL"], "graph.metrics": ["MUNICIPIOS_ORIGEM"],
      "graph.show_values": True}, False, (0, 35, 14, 9)),
    ("P10 · Onde o paciente é internado (fluxo entre regiões)", "pie",
     "SELECT TIPO_FLUXO, SUM(QTD_INTERNACOES) AS QTD FROM MART_P10_TRANSBORDO_REGIOES "
     "GROUP BY TIPO_FLUXO ORDER BY QTD DESC",
     {"pie.dimension": "TIPO_FLUXO", "pie.metric": "QTD"}, False, (14, 35, 10, 9)),
    ("P10 · Transbordo: internações fora da região de residência", "table",
     "SELECT REGIAO_ORIGEM, REGIAO_DESTINO, INTERNACOES, PCT_DA_ORIGEM FROM ("
     "SELECT REGIAO_ORIGEM, REGIAO_DESTINO, SUM(QTD_INTERNACOES) AS INTERNACOES, "
     "ROUND(100 * RATIO_TO_REPORT(SUM(QTD_INTERNACOES)) OVER (PARTITION BY REGIAO_ORIGEM), 1) AS PCT_DA_ORIGEM "
     "FROM MART_P10_TRANSBORDO_REGIOES WHERE TIPO_FLUXO <> 'OUTRO ESTADO' "
     "GROUP BY REGIAO_ORIGEM, REGIAO_DESTINO) "
     "WHERE REGIAO_ORIGEM <> REGIAO_DESTINO ORDER BY INTERNACOES DESC",
     {"column_settings": {'["name","PCT_DA_ORIGEM"]': {"show_mini_bar": True, "suffix": "%"}}},
     False, (0, 44, 24, 7)),
]


def criar_painel(banco, col):
    existentes = {c["name"]: c["id"] for c in api("GET", f"/collection/{col}/items?models=card")["data"]}
    tag = {"ano": {"id": "tag-ano", "name": "ano", "display-name": "Ano", "type": "number"}}
    dashcards = []
    for i, (nome, tipo, sql, visual, usa_ano, (x, y, w, h)) in enumerate(CARDS):
        corpo = {"name": nome, "display": tipo, "collection_id": col, "visualization_settings": visual,
                 "dataset_query": {"database": banco, "type": "native",
                                   "native": {"query": sql, "template-tags": tag if usa_ano else {}}}}
        card = (api("PUT", f"/card/{existentes[nome]}", corpo) if nome in existentes
                else api("POST", "/card", corpo))
        filtro = [{"parameter_id": "ano", "card_id": card["id"],
                   "target": ["variable", ["template-tag", "ano"]]}] if usa_ano else []
        dashcards.append({"id": -(i + 1), "card_id": card["id"], "col": x, "row": y,
                          "size_x": w, "size_y": h, "parameter_mappings": filtro,
                          "visualization_settings": {}})

    # perguntas que saíram do script são arquivadas, para a coleção não acumular sobras
    nomes = {c[0] for c in CARDS}
    for nome, card_id in existentes.items():
        if nome not in nomes:
            api("PUT", f"/card/{card_id}", {"archived": True})

    painel = next((d for d in api("GET", "/dashboard") if d["name"] == PAINEL), None)
    if not painel:
        painel = api("POST", "/dashboard", {"name": PAINEL, "collection_id": col})
    api("PUT", f"/dashboard/{painel['id']}", {
        "collection_id": col,
        "description": "Indicadores do SUS em Alagoas (SIH, SIA e CNES), 2023-2024.",
        "parameters": [{"id": "ano", "name": "Ano", "slug": "ano", "type": "number/=",
                        "sectionId": "number"}],
        "dashcards": dashcards,
    })
    return painel["id"]


if __name__ == "__main__":
    aguardar_metabase()
    configurar_admin()
    banco = configurar_banco()
    arquivar_exemplos()
    painel = criar_painel(banco, colecao())
    print(f"painel pronto: {len(CARDS)} cards em /dashboard/{painel}")

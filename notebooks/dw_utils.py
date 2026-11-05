"""Funções compartilhadas pelos notebooks e pela DAG do DW Saúde Alagoas.

Nos notebooks (que ficam um nível abaixo desta pasta):
    import sys; sys.path.append("..")
    from dw_utils import recarregar, mesclar, consultar
"""
import os
import re
import time
import zipfile
from ftplib import FTP

import oracledb

FTP_DATASUS = "ftp.datasus.gov.br"
TAB_SIA = "/dissemin/publicos/SIASUS/200801_/Auxiliar/TAB_SIA.zip"
TAB_SIH = "/dissemin/publicos/SIHSUS/200801_/Auxiliar/TAB_SIH.zip"

# anos processados (variável ANOS_PIPELINE no docker-compose)
ANOS = [int(a) for a in os.getenv("ANOS_PIPELINE", "2023,2024").split(",")]

# erros oracle de "objeto já existe", ignorados ao aplicar o schema.sql
_JA_EXISTE = {955, 1408, 1430, 2260, 2261, 2264, 2275}


def _n(valor):
    """Número com separador de milhar brasileiro: 588573 -> 588.573."""
    return f"{valor:,}".replace(",", ".")


# ----------------------------------------------------------------------------
# banco de dados
# ----------------------------------------------------------------------------
def conectar():
    """Conexão com o Oracle. Fora do Docker o host padrão é localhost."""
    return oracledb.connect(
        user=os.getenv("ORACLE_USER", "DW_ALAGOAS"),
        password=os.getenv("ORACLE_PASSWORD", "dw_password_123"),
        dsn="{}:{}/{}".format(
            os.getenv("ORACLE_HOST", "localhost"),
            os.getenv("ORACLE_PORT", "1521"),
            os.getenv("ORACLE_SERVICE", "FREEPDB1"),
        ),
    )


def executar(sql, params=None):
    with conectar() as con, con.cursor() as cur:
        cur.execute(sql, params or {})
        con.commit()
        return cur.rowcount


def contar(tabela):
    with conectar() as con, con.cursor() as cur:
        return cur.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]


def consultar(sql, params=None):
    """Executa um SELECT e devolve um DataFrame."""
    import pandas as pd

    with conectar() as con, con.cursor() as cur:
        cur.execute(sql, params or {})
        colunas = [c[0] for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=colunas)


def log_carga(tabela, lidos, gravados, **extras):
    detalhes = "".join(f", {_n(v)} {k}" for k, v in extras.items())
    print(f"{tabela}: {_n(lidos)} lidos, {_n(gravados)} gravados{detalhes}")


def recarregar(tabela, sql_insert, origem):
    """Carga full idempotente: TRUNCATE + INSERT /*+ APPEND */ (direct-path).

    Com a tabela vazia, o Oracle coleta as estatísticas durante a carga.
    `origem` é a tabela lida, usada para contar os registros lidos.
    """
    lidos = contar(origem)
    with conectar() as con, con.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {tabela}")
        cur.execute(sql_insert)
        con.commit()
        gravados = cur.rowcount
    log_carga(tabela, lidos, gravados)
    return gravados


def mesclar(tabela, sql_merge, origem):
    """Carga de dimensão com MERGE (SCD tipo 1): insere os novos, atualiza só o que mudou."""
    lidos = contar(origem)
    antes = contar(tabela)
    with conectar() as con, con.cursor() as cur:
        cur.execute(sql_merge)
        afetados = cur.rowcount
        con.commit()
    depois = contar(tabela)
    inseridos = depois - antes
    log_carga(tabela, lidos, afetados, inseridos=inseridos,
              atualizados=afetados - inseridos, **{"na tabela": depois})
    return afetados


def coletar_estatisticas(tabela):
    """Estatísticas de tabela, partições e índices (cascade) para o otimizador."""
    executar("BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER, :t, cascade => TRUE); END;",
             {"t": tabela})
    print(f"{tabela}: estatísticas coletadas")


def substituir(tabela, colunas, linhas):
    """Carga full de uma lista Python (tabelas pequenas)."""
    sql = (f"INSERT INTO {tabela} ({', '.join(colunas)}) "
           f"VALUES ({', '.join(f':{i}' for i in range(1, len(colunas) + 1))})")
    with conectar() as con, con.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {tabela}")
        cur.executemany(sql, linhas)
        con.commit()
    log_carga(tabela, len(linhas), len(linhas))
    return len(linhas)


def limpar_particao(tabela, ano):
    """Trunca a partição do ano (idempotência da bronze); ignora se ainda não existir."""
    try:
        executar(f"ALTER TABLE {tabela} TRUNCATE PARTITION FOR ('{ano}')")
        print(f"{tabela}: partição {ano} limpa")
    except oracledb.DatabaseError as erro:
        if erro.args[0].code != 14702:  # partição ainda não existe
            raise


def aplicar_schema(caminho_sql):
    """Executa o schema.sql comando a comando, ignorando "objeto já existe"."""
    with open(caminho_sql, encoding="utf-8-sig") as arquivo:
        linhas = [l for l in arquivo if not l.strip().startswith("--")]
    comandos = [c.strip() for c in "".join(linhas).split(";") if c.strip()]

    criados = 0
    with conectar() as con, con.cursor() as cur:
        for comando in comandos:
            try:
                cur.execute(comando)
                criados += 1
            except oracledb.DatabaseError as erro:
                if erro.args[0].code not in _JA_EXISTE:
                    raise
    print(f"schema aplicado: {criados} de {len(comandos)} objetos criados")


def alternar_fks(habilitar):
    """Desabilita ou reabilita (com VALIDATE) as FKs das fatos.

    Com FK habilitada o Oracle não faz insert direct-path. A DAG desabilita as FKs
    antes das fatos e as reabilita com VALIDATE no fim, validando a carga inteira.
    """
    acao = "ENABLE VALIDATE" if habilitar else "DISABLE"
    with conectar() as con, con.cursor() as cur:
        cur.execute("SELECT table_name, constraint_name FROM user_constraints "
                    "WHERE constraint_type = 'R'")
        fks = cur.fetchall()
        for tabela, fk in fks:
            cur.execute(f"ALTER TABLE {tabela} MODIFY CONSTRAINT {fk} {acao}")
    print(f"{len(fks)} fks {'habilitadas e validadas' if habilitar else 'desabilitadas'}")


# ----------------------------------------------------------------------------
# arquivos do DATASUS
# ----------------------------------------------------------------------------
def baixar_ftp(caminho, destino, tentativas=5, inatividade=60, limite=300):
    """Baixa um arquivo do FTP do DATASUS.

    O FTP às vezes fica lento sem derrubar a conexão. Cada tentativa tem dois limites:
    `inatividade` (segundos sem receber nada) e `limite` (tempo total do download).
    Estourou, abre uma conexão nova, que normalmente volta a ser rápida.
    """
    arquivo_nome = os.path.basename(caminho)
    for tentativa in range(1, tentativas + 1):
        inicio = time.monotonic()
        try:
            with FTP(FTP_DATASUS, timeout=inatividade) as ftp:
                ftp.login()
                with open(destino, "wb") as arquivo:
                    def gravar(bloco):
                        if time.monotonic() - inicio > limite:
                            raise TimeoutError(f"passou de {limite}s")
                        arquivo.write(bloco)
                    ftp.retrbinary(f"RETR {caminho}", gravar, blocksize=64 * 1024)
            tamanho = os.path.getsize(destino) / 1024 / 1024
            print(f"{arquivo_nome} baixado: {tamanho:.1f} MB em {time.monotonic() - inicio:.0f}s")
            return destino
        except Exception as erro:
            if tentativa == tentativas:
                raise RuntimeError(f"falha ao baixar {caminho} após {tentativas} tentativas: {erro}") from erro
            espera = 10 * tentativa
            print(f"{arquivo_nome}: tentativa {tentativa} falhou ({erro}), tentando de novo em {espera}s")
            time.sleep(espera)


def baixar_zip(caminho_ftp, pasta):
    """Baixa e extrai um .zip do DATASUS. Devolve {nome do arquivo em maiúsculas: caminho}."""
    os.makedirs(pasta, exist_ok=True)
    zip_local = baixar_ftp(caminho_ftp, os.path.join(pasta, os.path.basename(caminho_ftp)))
    with zipfile.ZipFile(zip_local) as zf:
        zf.extractall(pasta)
    return {
        nome.upper(): os.path.join(raiz, nome)
        for raiz, _, nomes in os.walk(pasta)
        for nome in nomes
    }


def baixar_tab_sia(pasta):
    return baixar_zip(TAB_SIA, pasta)


def dbc_para_dbf(caminho_dbc):
    """Descompacta o .dbc (DBF comprimido do DATASUS) para .dbf."""
    import pyreaddbc

    caminho_dbf = caminho_dbc[:-4] + ".dbf"
    pyreaddbc.dbc2dbf(caminho_dbc, caminho_dbf)
    return caminho_dbf


def ler_cnv(caminho):
    """Lê uma tabela de conversão do TabWin (.cnv) e devolve [(codigo, descricao)].

    O cabeçalho ("42 2 L" ou "N 41 2 L") informa o tamanho do código. Os códigos
    ficam no fim de cada linha, separados por vírgula.
    """
    cabecalho = re.compile(r"^\s*(?:N\s+)?(\d+)\s+(\d+)")
    with open(caminho, encoding="latin-1") as arquivo:
        # alguns arquivos têm linhas de comentário antes do cabeçalho
        tamanho = next(int(m.group(2)) for m in map(cabecalho.match, arquivo) if m)
        cod = rf"[0-9A-Z]{{{tamanho}}}"
        padrao = re.compile(rf"^\s*\d+\s+(.*?)\s*({cod}(?:,{cod})*)$")
        pares = []
        for linha in arquivo:
            # remove vírgulas e espaços sobrando no fim (ex.: "00,  ,")
            achou = padrao.match(re.sub(r"[,\s]+$", "", linha))
            if achou:
                descricao, codigos = achou.groups()
                pares += [(c, descricao.strip()) for c in codigos.split(",")]
    return pares


def carregar_dbf(caminho_dbf, tabela, colunas, lote=50_000):
    """Insere as colunas de um DBF na tabela, em lotes direct-path (APPEND_VALUES).

    Lê o arquivo em streaming e devolve (lidos, gravados).
    """
    from dbfread import DBF

    dbf = DBF(caminho_dbf, encoding="iso-8859-1", load=False)
    faltando = set(colunas) - set(dbf.field_names)
    if faltando:
        raise ValueError(f"{os.path.basename(caminho_dbf)} sem as colunas {faltando}")

    sql = (f"INSERT /*+ APPEND_VALUES */ INTO {tabela} ({', '.join(colunas)}) "
           f"VALUES ({', '.join(f':{i}' for i in range(1, len(colunas) + 1))})")

    lidos = gravados = 0
    buffer = []
    with conectar() as con, con.cursor() as cur:
        for registro in dbf:
            lidos += 1
            buffer.append(tuple(registro[c] for c in colunas))
            if len(buffer) == lote:
                cur.executemany(sql, buffer)
                con.commit()  # obrigatório após cada lote direct-path
                gravados += len(buffer)
                buffer.clear()
        if buffer:
            cur.executemany(sql, buffer)
            con.commit()
            gravados += len(buffer)
    return lidos, gravados


def carregar_arquivos_mensais(tabela, pasta_ftp, prefixo, colunas):
    """Carga idempotente dos arquivos mensais .dbc (SIH, SIA e CNES leitos).

    Para cada ano: limpa a partição do ano e carrega os 12 meses.
    """
    import tempfile

    total_lidos = total_gravados = 0
    for ano in ANOS:
        limpar_particao(tabela, ano)
        for mes in range(1, 13):
            arquivo = f"{prefixo}{ano % 100:02d}{mes:02d}.dbc"
            with tempfile.TemporaryDirectory() as pasta:
                dbc = baixar_ftp(f"{pasta_ftp}/{arquivo}", os.path.join(pasta, arquivo))
                lidos, gravados = carregar_dbf(dbc_para_dbf(dbc), tabela, colunas)
            log_carga(f"{tabela} <- {arquivo}", lidos, gravados)
            total_lidos += lidos
            total_gravados += gravados
    log_carga(f"{tabela} (total)", total_lidos, total_gravados)
    coletar_estatisticas(tabela)

"""DAG do Data Warehouse Saúde Alagoas (SIH / SIA / CNES - DATASUS).

"Job" do ETL. Cada task executa a "transformation" de uma tabela, que é um
notebook (notebooks/<camada>/<nome>.ipynb) rodado pelo papermill. A saída
executada de cada notebook, com o log de registros lidos e gravados, fica em
logs/notebooks/.

Fluxo:
  aplicar_schema -> bronze (8, só com carregar_bronze=true) -> silver (8) -> dimensões (8, MERGE)
  -> desabilitar_fks -> FATO_INTERNACAO -> FATO_PRODUCAO_AMBULATORIAL -> FATO_LEITOS
  -> habilitar_fks (VALIDATE) -> marts (10, uma por pergunta de negócio)
"""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.baseoperator import cross_downstream
from airflow.models.param import Param
from airflow.utils.task_group import TaskGroup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTEBOOKS = os.path.join(BASE_DIR, "notebooks")

BRONZE = ["bronze_ibge", "bronze_cnes", "bronze_sigtap", "bronze_cid", "bronze_dominio",
          "bronze_sih", "bronze_sia", "bronze_leitos"]
SILVER = ["silver_dominio", "silver_municipio", "silver_estabelecimento", "silver_procedimento",
          "silver_cid", "silver_sih", "silver_sia", "silver_leitos"]
DIMENSOES = ["gold_dim_tempo", "gold_dim_municipio", "gold_dim_estabelecimento",
             "gold_dim_procedimento", "gold_dim_cid", "gold_dim_especialidade",
             "gold_dim_carater_atendimento", "gold_dim_perfil_paciente"]
FATOS = ["gold_fato_internacao", "gold_fato_producao_ambulatorial", "gold_fato_leitos"]
MARTS = ["mart_p01_custo_volume_municipio", "mart_p02_top_especialidades",
         "mart_p03_permanencia_especialidade", "mart_p04_ocupacao_hospitalar",
         "mart_p05_custo_procedimento", "mart_p06_perfil_urgencia",
         "mart_p07_respiratorias_mensal", "mart_p08_fluxo_polos",
         "mart_p09_hubs_hospitalares", "mart_p10_transbordo_regioes"]


def rodar_notebook(caminho):
    """Executa um notebook com o papermill. Qualquer erro no notebook falha a task."""
    import papermill as pm  # import aqui para não pesar o parse da DAG

    entrada = os.path.join(NOTEBOOKS, caminho)
    saida = os.path.join(BASE_DIR, "logs", "notebooks", os.path.basename(caminho))
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    pm.execute_notebook(entrada, saida, cwd=os.path.dirname(entrada), log_output=True)


def rodar_bronze(caminho, params=None):
    """Bronze só roda com carregar_bronze=true; senão usa o que já está no banco."""
    from airflow.exceptions import AirflowSkipException
    if not params["carregar_bronze"]:
        raise AirflowSkipException("carregar_bronze desligado, usando o bronze já carregado")
    rodar_notebook(caminho)


def notebook(camada, nome, **kwargs):
    funcao = rodar_bronze if camada == "bronze" else rodar_notebook
    return task(task_id=nome, **kwargs)(funcao)(f"{camada}/{nome}.ipynb")


def _dw_utils():
    import sys
    sys.path.append(NOTEBOOKS)
    import dw_utils
    return dw_utils


@task
def aplicar_schema():
    _dw_utils().aplicar_schema(os.path.join(BASE_DIR, "sql", "schema.sql"))


@task
def desabilitar_fks():
    _dw_utils().alternar_fks(habilitar=False)


@task
def habilitar_fks():
    _dw_utils().alternar_fks(habilitar=True)


@dag(
    dag_id="dag_etl_saude_alagoas",
    description="DW Saúde Alagoas: bronze -> silver -> gold (star schema) -> marts",
    schedule=None,  # execução manual: dispare a DAG pelo Airflow quando quiser recarregar
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,  # o Oracle Free usa no máximo 2 CPUs
    default_args={
        "owner": "DW_ALAGOAS",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["DW", "SAUDE", "ORACLE", "DATASUS"],
    params={
        # marque ao disparar (trigger dag w/ config) na primeira carga ou para baixar de novo
        "carregar_bronze": Param(False, type="boolean",
                                 description="baixar os arquivos do DATASUS e recarregar o bronze"),
    },
)
def dag_etl_saude_alagoas():
    schema = aplicar_schema()

    with TaskGroup("bronze"):
        bronze = [notebook("bronze", n) for n in BRONZE]

    with TaskGroup("silver"):
        # none_failed: a silver roda mesmo com o bronze pulado
        silver = [notebook("silver", SILVER[0], trigger_rule="none_failed")]
        silver += [notebook("silver", n) for n in SILVER[1:]]

    with TaskGroup("dimensoes"):
        dimensoes = [notebook("gold", n) for n in DIMENSOES]

    with TaskGroup("fatos"):
        fks_off = desabilitar_fks()
        fatos = [notebook("gold", n) for n in FATOS]
        fks_on = habilitar_fks()

    with TaskGroup("marts"):
        marts = [notebook("mart", n) for n in MARTS]

    schema >> bronze
    # silver_dominio primeiro: as demais silvers buscam descrições nele
    cross_downstream(bronze, silver[:1])
    silver[0] >> silver[1:]
    cross_downstream(silver, dimensoes)
    dimensoes >> fks_off >> fatos[0] >> fatos[1] >> fatos[2] >> fks_on >> marts


dag_etl_saude_alagoas()

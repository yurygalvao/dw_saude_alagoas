# Imagem do Airflow com as dependências do pipeline já instaladas.
# Fixar "apache-airflow==versão" no mesmo pip install impede que as dependências
# do projeto atualizem pacotes do próprio Airflow (recomendação oficial).
FROM apache/airflow:2.8.1-python3.10

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt

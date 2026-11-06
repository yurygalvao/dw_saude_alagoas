-- ============================================================================
-- Auditoria da carga do DW (execute conectado como DW_ALAGOAS)
-- No SQL Developer: posicione o cursor numa consulta e use Ctrl+Enter.
-- ============================================================================

-- 1. Quantidade de linhas de todas as tabelas
SELECT t.table_name AS tabela, x.linhas
FROM user_tables t,
     XMLTABLE('/ROWSET/ROW'
              PASSING DBMS_XMLGEN.GETXMLTYPE('SELECT COUNT(*) AS C FROM "' || t.table_name || '"')
              COLUMNS linhas NUMBER PATH 'C') x
ORDER BY CASE WHEN t.table_name LIKE 'BRONZE%' THEN 1 WHEN t.table_name LIKE 'SILVER%' THEN 2
              WHEN t.table_name LIKE 'DIM%' THEN 3 WHEN t.table_name LIKE 'FATO%' THEN 4 ELSE 5 END,
         t.table_name;

-- 2. Dimensões sem repetição: linhas = chaves naturais distintas
SELECT 'DIM_TEMPO' AS dimensao, COUNT(*) AS linhas, COUNT(DISTINCT SK_TEMPO) AS chaves FROM DIM_TEMPO
UNION ALL SELECT 'DIM_MUNICIPIO', COUNT(*), COUNT(DISTINCT COD_IBGE_6) FROM DIM_MUNICIPIO
UNION ALL SELECT 'DIM_ESTABELECIMENTO', COUNT(*), COUNT(DISTINCT COD_CNES) FROM DIM_ESTABELECIMENTO
UNION ALL SELECT 'DIM_PROCEDIMENTO', COUNT(*), COUNT(DISTINCT COD_PROCEDIMENTO) FROM DIM_PROCEDIMENTO
UNION ALL SELECT 'DIM_CID', COUNT(*), COUNT(DISTINCT COD_CID) FROM DIM_CID
UNION ALL SELECT 'DIM_ESPECIALIDADE', COUNT(*), COUNT(DISTINCT COD_ESPECIALIDADE) FROM DIM_ESPECIALIDADE
UNION ALL SELECT 'DIM_CARATER_ATENDIMENTO', COUNT(*), COUNT(DISTINCT COD_CARATER) FROM DIM_CARATER_ATENDIMENTO
UNION ALL SELECT 'DIM_PERFIL_PACIENTE', COUNT(*), COUNT(DISTINCT SEXO || FAIXA_ETARIA) FROM DIM_PERFIL_PACIENTE;

-- 3. Fatos sem repetição: linhas = combinações distintas do grão
SELECT 'FATO_INTERNACAO' AS fato, COUNT(*) AS linhas,
       COUNT(DISTINCT SK_ESTABELECIMENTO || '|' || NUM_AIH || '|' || TIPO_AIH || '|' || SEQ_AIH5
             || '|' || ANO_MES_CMPT || '|' || SK_TEMPO_SAIDA) AS graos_distintos
FROM FATO_INTERNACAO
UNION ALL
SELECT 'FATO_PRODUCAO_AMBULATORIAL', COUNT(*),
       COUNT(DISTINCT SK_TEMPO_COMPETENCIA || '|' || SK_MUNICIPIO_RESIDENCIA || '|'
             || SK_MUNICIPIO_ATENDIMENTO || '|' || SK_ESTABELECIMENTO || '|' || SK_PROCEDIMENTO)
FROM FATO_PRODUCAO_AMBULATORIAL
UNION ALL
SELECT 'FATO_LEITOS', COUNT(*), COUNT(DISTINCT SK_TEMPO_COMPETENCIA || '|' || SK_ESTABELECIMENTO)
FROM FATO_LEITOS;

-- 4. Bronze sem duplicação: cada AIH principal aparece uma vez por competência
SELECT ANO_CMPT, COUNT(*) AS aih_principais,
       COUNT(DISTINCT N_AIH || MES_CMPT) AS aih_distintas,
       COUNT(*) - COUNT(DISTINCT N_AIH || MES_CMPT) AS duplicadas
FROM BRONZE_SIH
WHERE IDENT = '1'
GROUP BY ANO_CMPT
ORDER BY ANO_CMPT;

-- 5. Reconciliação: o mesmo valor no bronze, na silver e na fato
SELECT 'SIH - VALOR TOTAL' AS medida,
       (SELECT SUM(VAL_TOT) FROM BRONZE_SIH) AS bronze,
       (SELECT SUM(VL_TOTAL) FROM SILVER_SIH) AS silver,
       (SELECT SUM(VL_TOTAL) FROM FATO_INTERNACAO) AS fato
FROM DUAL
UNION ALL
SELECT 'SIA - VALOR APROVADO',
       (SELECT SUM(PA_VALAPR) FROM BRONZE_SIA),
       (SELECT SUM(VL_APROVADO) FROM SILVER_SIA),
       (SELECT SUM(VL_APROVADO) FROM FATO_PRODUCAO_AMBULATORIAL)
FROM DUAL
UNION ALL
SELECT 'CNES - LEITOS SUS',
       (SELECT SUM(QT_SUS) FROM BRONZE_LEITOS),
       (SELECT SUM(QTD_LEITOS_SUS) FROM SILVER_LEITOS),
       (SELECT SUM(QTD_LEITOS_SUS) FROM FATO_LEITOS)
FROM DUAL;

-- 6. Integridade referencial: todas as FKs habilitadas e validadas
SELECT table_name, constraint_name, status, validated
FROM user_constraints
WHERE constraint_type = 'R'
ORDER BY table_name, constraint_name;

-- 7. Onde os dados ficam: tablespaces de dados e de índices
SELECT tablespace_name, segment_type, COUNT(*) AS objetos, ROUND(SUM(bytes) / 1024 / 1024) AS mb
FROM user_segments
GROUP BY tablespace_name, segment_type
ORDER BY tablespace_name, segment_type;

-- 8. Particionamento: bronze por ano e fato ambulatorial por mês
SELECT table_name, COUNT(*) AS particoes, MIN(partition_name) AS primeira, MAX(partition_name) AS ultima
FROM user_tab_partitions
GROUP BY table_name
ORDER BY table_name;

-- 9. Consulta no modelo estrela: internações e custo por região de saúde de residência
SELECT m.REGIAO_SAUDE, t.NR_ANO,
       SUM(f.QTD_INTERNACAO) AS internacoes,
       SUM(f.VL_TOTAL) AS valor_total,
       ROUND(SUM(f.VL_TOTAL) / NULLIF(SUM(f.QTD_INTERNACAO), 0), 2) AS custo_medio
FROM FATO_INTERNACAO f
JOIN DIM_MUNICIPIO m ON m.SK_MUNICIPIO = f.SK_MUNICIPIO_RESIDENCIA
JOIN DIM_TEMPO t     ON t.SK_TEMPO = f.SK_TEMPO_INTERNACAO
WHERE m.UF = 'AL' AND t.NR_ANO IN (2023, 2024)
GROUP BY m.REGIAO_SAUDE, t.NR_ANO
ORDER BY m.REGIAO_SAUDE, t.NR_ANO;

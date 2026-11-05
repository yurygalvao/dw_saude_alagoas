-- ============================================================================
-- DATA WAREHOUSE SAÚDE ALAGOAS - CRIAÇÃO DE TABLESPACES E DO OWNER
-- Executado UMA vez, como SYS, na primeira inicialização do container Oracle
-- (pasta /container-entrypoint-initdb.d da imagem gvenzl/oracle-free).
--
-- TS_DW_DADOS   : tabelas de todas as camadas (bronze, silver, gold, mart)
-- TS_DW_INDICES : todos os índices (PK, UK e bitmap), separados dos dados
-- DW_ALAGOAS    : owner/schema do DW, com apenas os privilégios necessários
-- ============================================================================

ALTER SESSION SET CONTAINER = FREEPDB1;

CREATE TABLESPACE TS_DW_DADOS
    DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/ts_dw_dados01.dbf'
    SIZE 512M AUTOEXTEND ON NEXT 256M MAXSIZE 10G;

CREATE TABLESPACE TS_DW_INDICES
    DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/ts_dw_indices01.dbf'
    SIZE 128M AUTOEXTEND ON NEXT 64M MAXSIZE 2G;

CREATE USER DW_ALAGOAS IDENTIFIED BY "dw_password_123"
    DEFAULT TABLESPACE TS_DW_DADOS
    TEMPORARY TABLESPACE TEMP
    QUOTA UNLIMITED ON TS_DW_DADOS
    QUOTA UNLIMITED ON TS_DW_INDICES;

GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE TO DW_ALAGOAS;

EXIT;

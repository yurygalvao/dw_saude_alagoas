// ============================================================================
// DW Saúde Alagoas - perguntas de negócio respondidas no grafo (Neo4j)
// Cada bloco começa com "// Pnn" (pergunta original) ou "// Pnn-ALT" (pergunta
// alternativa, mais adequada a grafo, para as perguntas que o painel responde melhor).
// ============================================================================

// P01 | Custo total e volume de atendimentos por município (2023-2024)
MATCH (m:Municipio {uf: 'AL'})-[p:PRODUZIU]->(:Mes)
RETURN m.nome AS municipio,
       sum(p.qtd_ambulatorial + p.internacoes) AS atendimentos,
       round(sum(p.vl_total), 2) AS custo_total
ORDER BY custo_total DESC
LIMIT 10;

// P01-ALT | Para onde vai o dinheiro gasto com as internações dos moradores de cada município?
MATCH (o:Municipio {uf: 'AL'})-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(d:Municipio)
WHERE o <> d
RETURN o.nome AS municipio_origem, d.nome AS municipio_destino,
       sum(i.internacoes) AS internacoes, round(sum(i.valor), 2) AS valor
ORDER BY valor DESC
LIMIT 10;

// P02 | Top 5 especialidades de leito mais demandadas na 1ª e na 2ª Macrorregião
MATCH (ma:Macrorregiao)<-[:PERTENCE_A]-(:Regiao)<-[:PERTENCE_A]-(:Municipio)-[d:DEMANDOU]->(s:Especialidade)
WHERE ma.nome <> 'FORA DE ALAGOAS'
WITH ma, s, sum(d.internacoes) AS internacoes
ORDER BY ma.nome, internacoes DESC
WITH ma, collect({especialidade: s.nome, internacoes: internacoes})[0..5] AS top5
UNWIND range(0, size(top5) - 1) AS i
RETURN ma.nome AS macrorregiao, i + 1 AS ranking,
       top5[i].especialidade AS especialidade, top5[i].internacoes AS internacoes;

// P02-ALT | Quais hospitais concentram as internações dos moradores de cada macrorregião?
MATCH (ma:Macrorregiao)<-[:PERTENCE_A]-(:Regiao)<-[:PERTENCE_A]-(:Municipio)-[i:INTERNOU_EM]->(h:Hospital)
WHERE ma.nome <> 'FORA DE ALAGOAS'
WITH ma, h, sum(i.internacoes) AS internacoes
ORDER BY ma.nome, internacoes DESC
WITH ma, collect({hospital: h.nome, internacoes: internacoes})[0..5] AS top5
UNWIND range(0, size(top5) - 1) AS i
RETURN ma.nome AS macrorregiao, i + 1 AS ranking,
       top5[i].hospital AS hospital, top5[i].internacoes AS internacoes;

// P03 | Tempo médio de permanência por especialidade do leito
MATCH (:Hospital)-[a:ATENDEU]->(s:Especialidade)
RETURN s.nome AS especialidade, sum(a.internacoes) AS internacoes,
       round(toFloat(sum(a.dias)) / sum(a.internacoes), 1) AS media_dias
ORDER BY media_dias DESC;

// P03-ALT | Quais hospitais formam a rede de psiquiatria e qual a permanência em cada um?
MATCH (h:Hospital)-[a:ATENDEU]->(s:Especialidade {nome: 'PSIQUIATRIA'})
MATCH (h)-[:LOCALIZADO_EM]->(m:Municipio)
RETURN h.nome AS hospital, m.nome AS municipio, a.internacoes AS internacoes,
       round(toFloat(a.dias) / a.internacoes, 1) AS media_dias
ORDER BY internacoes DESC;

// P04 | Hospitais com maior taxa de ocupação (10 ou mais leitos SUS)
MATCH (h:Hospital)
WHERE h.leitos_sus >= 10
RETURN h.nome AS hospital, h.leitos_sus AS leitos_sus, h.pct_ocupacao AS pct_ocupacao
ORDER BY pct_ocupacao DESC
LIMIT 10;

// P04-ALT | Os hospitais mais lotados (ocupação acima de 85%) recebem pacientes de quantos municípios?
MATCH (o:Municipio)-[i:INTERNOU_EM]->(h:Hospital)
WHERE h.leitos_sus >= 10 AND h.pct_ocupacao > 85
RETURN h.nome AS hospital, h.pct_ocupacao AS pct_ocupacao,
       count(o) AS municipios_origem, sum(i.internacoes) AS internacoes
ORDER BY pct_ocupacao DESC;

// P05 | Procedimentos com maior variação de custo médio entre hospitais
MATCH (h:Hospital)-[r:REALIZOU]->(p:Procedimento)
WHERE r.internacoes >= 10 AND r.custo_medio > 0
WITH p, count(h) AS hospitais, min(r.custo_medio) AS menor, max(r.custo_medio) AS maior
WHERE hospitais >= 3
RETURN p.nome AS procedimento, hospitais, menor, maior, round(maior / menor, 1) AS vezes
ORDER BY vezes DESC
LIMIT 10;

// P05-ALT | Quais pares de hospitais realizam mais procedimentos em comum, e quem cobra mais caro?
MATCH (h1:Hospital)-[r1:REALIZOU]->(p:Procedimento)<-[r2:REALIZOU]-(h2:Hospital)
WHERE h1.cnes < h2.cnes AND r1.internacoes >= 10 AND r2.internacoes >= 10
  AND r1.custo_medio > 0 AND r2.custo_medio > 0
RETURN h1.nome AS hospital_1, h2.nome AS hospital_2, count(p) AS procedimentos_em_comum,
       round(avg(r1.custo_medio / r2.custo_medio), 2) AS custo_1_sobre_2
ORDER BY procedimentos_em_comum DESC
LIMIT 10;

// P06 | Perfil (faixa etária e sexo) das internações de urgência
MATCH (p:Perfil)-[u:INTERNADO_EM_URGENCIA]->(:Hospital)
RETURN p.sexo AS sexo, p.faixa_etaria AS faixa_etaria, sum(u.internacoes) AS internacoes
ORDER BY internacoes DESC;

// P06-ALT | Em quais hospitais se concentram as urgências do perfil predominante (mulheres de 15 a 29 anos)?
MATCH (p:Perfil {chave: 'F|15-29'})-[u:INTERNADO_EM_URGENCIA]->(h:Hospital)-[:LOCALIZADO_EM]->(m:Municipio)
RETURN h.nome AS hospital, m.nome AS municipio, u.internacoes AS internacoes
ORDER BY internacoes DESC
LIMIT 10;

// P07 | Meses com picos de internação por doenças respiratórias (3 maiores de cada ano)
MATCH (:GrupoDoenca)-[x:INTERNACOES_NO_MES]->(t:Mes)
WHERE x.ranking_ano <= 3
RETURN t.ano AS ano, x.ranking_ano AS ranking, t.nome AS mes, x.internacoes AS internacoes
ORDER BY ano, ranking;

// P07-ALT | De quais municípios vêm e para quais hospitais vão os pacientes com doenças respiratórias?
MATCH (o:Municipio)-[i:INTERNOU_EM]->(h:Hospital)-[:LOCALIZADO_EM]->(d:Municipio)
WHERE i.respiratorias > 0 AND o <> d
RETURN o.nome AS municipio_origem, h.nome AS hospital, d.nome AS municipio_hospital,
       i.respiratorias AS internacoes_respiratorias
ORDER BY internacoes_respiratorias DESC
LIMIT 10;

// P08 | Fluxo de pacientes do interior para os polos Maceió e Arapiraca
MATCH (o:Municipio {tipo: 'INTERIOR'})-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(p:Municipio)
WHERE p.nome IN ['MACEIÓ', 'ARAPIRACA'] AND o <> p
RETURN o.nome AS municipio_origem, p.nome AS polo, sum(i.internacoes) AS internacoes
ORDER BY internacoes DESC
LIMIT 15;

// P08 | Percentual das internações de cada polo que vêm do interior
MATCH (o:Municipio)-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(p:Municipio)
WHERE p.nome IN ['MACEIÓ', 'ARAPIRACA']
WITH p, sum(i.internacoes) AS total,
     sum(CASE WHEN o.tipo = 'INTERIOR' AND o <> p THEN i.internacoes ELSE 0 END) AS do_interior
RETURN p.nome AS polo, total, do_interior, round(100.0 * do_interior / total, 1) AS pct_interior;

// P09 | Hospitais "hub": quais recebem pacientes de mais municípios
MATCH (o:Municipio)-[i:INTERNOU_EM]->(h:Hospital)-[:LOCALIZADO_EM]->(m:Municipio)
RETURN h.nome AS hospital, m.nome AS municipio, count(o) AS municipios_origem,
       sum(i.internacoes) AS internacoes
ORDER BY municipios_origem DESC
LIMIT 10;

// P10 | Transbordo de internações entre regiões de saúde
MATCH (ro:Regiao)<-[:PERTENCE_A]-(:Municipio)-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(:Municipio)-[:PERTENCE_A]->(rd:Regiao)
WHERE ro <> rd AND ro.nome <> 'FORA DE ALAGOAS'
RETURN ro.nome AS regiao_origem, rd.nome AS regiao_destino, sum(i.internacoes) AS internacoes
ORDER BY internacoes DESC
LIMIT 10;

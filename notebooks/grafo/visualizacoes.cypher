// ============================================================================
// Consultas de visualização para o Neo4j Browser (http://localhost:7474).
// Retornam caminhos (paths) para o Browser desenhar o grafo. Os filtros de
// quantidade deixam só as ligações mais fortes, para a imagem ficar legível.
// Antes, rode o estilo abaixo (cole no editor do Browser) para mostrar os nomes.
// ============================================================================

// ESTILO
:style
node { diameter: 50px; color: #A5ABB6; border-color: #9AA1AC; border-width: 2px; text-color-internal: #000000; font-size: 9px; caption: '{nome}'; }
relationship { color: #A5ABB6; shaft-width: 1px; font-size: 8px; padding: 3px; text-color-external: #000000; text-color-internal: #FFFFFF; caption: ''; }
node.Municipio { color: #C9E7FA; border-color: #68BDF6; diameter: 62px; caption: '{nome}'; }
node.Hospital { color: #FCD9C6; border-color: #F79767; diameter: 85px; caption: '{nome}'; }
node.Regiao { color: #D3F0E1; border-color: #6DCE9E; diameter: 75px; caption: '{nome}'; }
node.Macrorregiao { color: #E8D9F5; border-color: #A97FD6; diameter: 90px; caption: '{nome}'; }
node.Especialidade { color: #FFD6D4; border-color: #FF756E; diameter: 80px; caption: '{nome}'; }
node.Procedimento { color: #FFF3C4; border-color: #F2C94C; diameter: 60px; caption: '{nome}'; }
node.Perfil { color: #FFD6D4; border-color: #FF756E; diameter: 80px; caption: '{sexo} {faixa_etaria}'; }
relationship.INTERNOU_EM { caption: '{internacoes}'; }
relationship.TRANSBORDO { caption: '{internacoes}'; shaft-width: 2px; }
relationship.ATENDEU { caption: '{internacoes}'; }
relationship.INTERNADO_EM_URGENCIA { caption: '{internacoes}'; }

// G08 | Fluxo do interior para os hospitais de Maceió e Arapiraca (700 ou mais internações)
MATCH p = (o:Municipio {tipo: 'INTERIOR'})-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(m:Municipio)
WHERE m.nome IN ['MACEIÓ', 'ARAPIRACA'] AND o <> m AND i.internacoes >= 700
RETURN p;

// G09 | Os 3 maiores hospitais hub e os municípios de Alagoas que mandam pacientes para eles
MATCH (h:Hospital)<-[:INTERNOU_EM]-(o:Municipio)
WITH h, count(o) AS grau ORDER BY grau DESC LIMIT 3
MATCH p = (:Municipio {uf: 'AL'})-[:INTERNOU_EM]->(h)
RETURN p;

// G10 | Transbordo entre regiões de saúde (1.000 ou mais internações)
MATCH p = (:Regiao)-[t:TRANSBORDO]->(:Regiao)
WHERE t.internacoes >= 1000
RETURN p;

// G01-ALT | Para onde vão as internações dos moradores (ligações de R$ 2 milhões ou mais)
MATCH p = (o:Municipio {uf: 'AL'})-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(d:Municipio)
WHERE o <> d AND i.valor >= 2000000
RETURN p;

// G02-ALT | Hospitais que concentram a demanda de cada macrorregião (1.500 ou mais internações)
MATCH p = (ma:Macrorregiao)<-[:PERTENCE_A]-(:Regiao)<-[:PERTENCE_A]-(:Municipio)-[i:INTERNOU_EM]->(:Hospital)
WHERE ma.nome <> 'FORA DE ALAGOAS' AND i.internacoes >= 1500
RETURN p;

// G03-ALT | Rede de hospitais que atendem psiquiatria
MATCH p = (:Municipio)<-[:LOCALIZADO_EM]-(:Hospital)-[:ATENDEU]->(:Especialidade {nome: 'PSIQUIATRIA'})
RETURN p;

// G04-ALT | Municípios que mandam pacientes aos hospitais com ocupação acima de 85% (30 ou mais internações)
MATCH p = (:Municipio)-[i:INTERNOU_EM]->(h:Hospital)
WHERE h.leitos_sus >= 10 AND h.pct_ocupacao > 85 AND i.internacoes >= 30
RETURN p;

// G05-ALT | Hospitais regionais ligados pelos procedimentos que realizam em comum (50 ou mais internações)
MATCH p = (h1:Hospital)-[r1:REALIZOU]->(:Procedimento)<-[r2:REALIZOU]-(h2:Hospital)
WHERE h1.nome STARTS WITH 'HOSPITAL REGIONAL' AND h2.nome STARTS WITH 'HOSPITAL REGIONAL'
  AND h1.cnes < h2.cnes AND r1.internacoes >= 50 AND r2.internacoes >= 50
RETURN p;

// G06-ALT | Hospitais que recebem as urgências de mulheres de 15 a 29 anos (2.000 ou mais)
MATCH p = (:Perfil {chave: 'F|15-29'})-[u:INTERNADO_EM_URGENCIA]->(:Hospital)
WHERE u.internacoes >= 2000
RETURN p;

// G07-ALT | Fluxo das internações por doenças respiratórias (100 ou mais, fora do município)
MATCH p = (o:Municipio)-[i:INTERNOU_EM]->(:Hospital)-[:LOCALIZADO_EM]->(d:Municipio)
WHERE o <> d AND i.respiratorias >= 100
RETURN p;

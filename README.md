# Como Votar

Perfil de cada deputado federal e senador (legislatura 2023–2026): propostas, votos nominais, gastos da cota parlamentar
comparados à média (nacional e do estado) e presença. Usa só dados abertos da Câmara.

## Rodar

```bash
./fetch_data.sh                # baixa ~1,8 GB de CSVs para data_raw/ (uma vez; REFRESH=1 para atualizar)
python3 build_data.py          # gera web/data/*.json (~15 s, só biblioteca padrão)
python3 -m http.server 8765 --directory web   # abre http://localhost:8765
```

O front (`web/`) é estático: HTML + JS puro, sem build. Pode ser publicado em qualquer hospedagem estática
(GitHub Pages, Netlify…). `web/data/` (~26 MB) é gerado e precisa ir junto.

## Decisões e limitações

- **Cota (CEAP):** vem do CSV anual da Câmara. O ID do deputado é `ideCadastro` (o `nuDeputadoId` é interno).
  Os últimos meses saem incompletos (notas chegam com atraso), então `build_data.py` corta a janela no último
  mês cuja média nacional é ≥ 80% da mediana dos 12 anteriores.
- **Verba de gabinete** (salários de assessores) não está nos dados abertos em formato comparável: fora do escopo.
- **Votos:** só votações nominais do Plenário. "Maioria do partido" é calculada dos votos, não é a orientação oficial.
- **Presença:** sessões deliberativas do Plenário. Justificativas de ausência não existem nos dados abertos.
- **Período do deputado:** do 1º ao último registro em presença/votação; licenças no meio do mandato não são descontadas.
- Médias só incluem deputados com ≥ 6 meses de mandato.

## Orientação da liderança e ideologia

- `votacoesOrientacoes-AAAA.csv` traz a orientação de cada bancada (partido, federação, bloco, Governo, Oposição…).
  `build_data.py` mapeia o partido do deputado à bancada mais específica (`BANCADAS`); blocos de nome truncado
  que não estão na lista oficial têm a composição deduzida (partidos sem outra linha na votação).
- `ideologia.json` é a tabela editável de ideologia por partido: nota 0–10 e faixas de Bolognesi, Ribeiro & Codato
  (2023, *Dados*, survey UFPR/ABCP). Renomeados usam a nota do nome anterior; União e PRD são médias marcadas como
  estimadas; Missão fica sem classificação. Para trocar de fonte, edite esse arquivo e rode `build_data.py`.

## Orientação ideológica pelo voto

`build_data.py` também posiciona cada deputado num eixo único a partir dos votos (`escalar()`, posto 1 por mínimos
quadrados alternados, Python puro). Usa só votações Plenário contestadas (minoria ≥ 10%) em que o Governo **não**
orientou Sim/Não; com todas as votações o eixo vira governo × oposição (o build imprime a correlação de cada escala
com o alinhamento ao Governo e com a pesquisa acadêmica). Sinal fixado com PSOL à esquerda de PL; escala 0–10 relativa
(percentis 2 e 98) com os mesmos cortes de faixa do artigo. Saída: `web/data/ideologia_voto.json` + campos
`voto_nota`/`voto_faixa` em `deputados.json`.

## Senado

O site tem duas casas (`#/` = Câmara, `#/senado` = Senado); os dados do Senado ficam em `web/data/senado/`.

```bash
python3 fetch_senado.py     # baixa votações, orientações, autorias, processos e CEAPS para data_raw/senado/ (REFRESH=1 força)
python3 build_senado.py     # gera web/data/senado/ no mesmo formato da Câmara (usa funções de build_data.py)
```

- Fontes: [dados abertos do Senado](https://legis.senado.leg.br/dadosabertos) (`/votacao`, `/plenario/votacao/orientacaoBancada`,
  `/senador/...`, `/processo`) e a CEAPS (`adm.senado.gov.br`). Candidaturas: mesmo arquivo do TSE usado para a Câmara.
- **Voto individual só existe nas votações nominais abertas** (183 de 423 na legislatura); as secretas só registram presença.
- **Presença** é medida nas votações nominais (abertas e secretas) e separa ausência justificada (atividade parlamentar,
  missão, licença) de não comparecimento.
- **Não há "posição ideológica pelo voto" no Senado**: com as poucas votações abertas em que o Governo não orientou, a escala
  reproduz o alinhamento ao Governo (correlação 0,94) mais que a pesquisa acadêmica (0,62). Ver `meta.json -> diagnostico`.
- Tema das votações = nível mais alto da classificação do processo legislativo.
- `fetch_senado.py` usa endpoints que o Senado marcou como descontinuados (`/senador/{id}/autorias`); se pararem de
  responder, o substituto é `/processo?codigoParlamentarAutor=`.

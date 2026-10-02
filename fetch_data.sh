#!/usr/bin/env bash
# Baixa os arquivos em lote da Câmara dos Deputados (legislatura 57: 2023-2026) para data_raw/
set -euo pipefail
cd "$(dirname "$0")/data_raw"
A=https://dadosabertos.camara.leg.br/arquivos
get() { [ -s "$2" ] && [ -z "${REFRESH:-}" ] && return 0; echo "baixando $2"; curl -sSf --retry 5 --retry-delay 5 -o "$2.tmp" "$1" && mv "$2.tmp" "$2"; }
for y in 2023 2024 2025 2026; do
  get $A/eventos/csv/eventos-$y.csv                              eventos-$y.csv &
  get $A/eventosPresencaDeputados/csv/eventosPresencaDeputados-$y.csv presenca-$y.csv &
  get $A/votacoes/csv/votacoes-$y.csv                            votacoes-$y.csv &
  get $A/votacoesVotos/csv/votacoesVotos-$y.csv                  votos-$y.csv &
  get $A/votacoesOrientacoes/csv/votacoesOrientacoes-$y.csv       orient-$y.csv &
  get $A/votacoesProposicoes/csv/votacoesProposicoes-$y.csv      votprop-$y.csv &
  get $A/proposicoesAutores/csv/proposicoesAutores-$y.csv        autores-$y.csv &
  get $A/proposicoes/csv/proposicoes-$y.csv                      proposicoes-$y.csv &
  wait
  if [ ! -s ceap-$y.csv ]; then echo "baixando ceap-$y"; curl -sSf -o ceap-$y.zip https://www.camara.leg.br/cotas/Ano-$y.csv.zip && unzip -p ceap-$y.zip "Ano-$y.csv" > ceap-$y.csv && rm ceap-$y.zip; fi
done
# temas oficiais das proposições, por ano de apresentação (votações citam proposições antigas)
for y in $(seq 2003 2026); do get $A/proposicoesTemas/csv/proposicoesTemas-$y.csv temas-$y.csv & done; wait
get "https://dadosabertos.camara.leg.br/api/v2/deputados?idLegislatura=57&itens=1000&ordem=ASC&ordenarPor=nome" deputados.json
get "https://dadosabertos.camara.leg.br/api/v2/deputados?itens=1000" deputados-atuais.json
# candidaturas 2026 (TSE) e dados civis dos deputados (nome civil + nascimento) para cruzar as duas bases
if [ ! -s consulta_cand_2026_BRASIL.csv ] || [ -n "${REFRESH:-}" ]; then
  echo "baixando candidaturas 2026 (TSE)"
  curl -sSf --retry 5 --retry-delay 5 -o cand2026.zip https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip
  unzip -o -q -j cand2026.zip consulta_cand_2026_BRASIL.csv && rm cand2026.zip
fi
get $A/deputados/csv/deputados.csv deputados-csv.csv
# histórico de situação de cada deputado (períodos de exercício, licenças, suplências)
mkdir -p historico
python3 -c "import json;print('\n'.join(str(d['id']) for d in json.load(open('deputados.json'))['dados']))" | sort -u \
  | xargs -P 6 -I{} sh -c 'if [ ! -s historico/{}.json ] || [ -n "${REFRESH:-}" ]; then curl -sSf --retry 5 --retry-delay 3 -o historico/{}.json.tmp "https://dadosabertos.camara.leg.br/api/v2/deputados/{}/historico" && mv historico/{}.json.tmp historico/{}.json; fi'
echo ok

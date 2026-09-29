#!/usr/bin/env python3
"""Baixa os dados do Senado Federal (legislatura 57: 2023-2026) para data_raw/senado/.

Fontes (dados abertos do Senado):
  - votações nominais com o voto de cada senador       /dadosabertos/votacao
  - orientações de liderança e do Governo               /dadosabertos/plenario/votacao/orientacaoBancada
  - lista de senadores, detalhe e autorias              /dadosabertos/senador/...
  - status das proposições e temas                      /dadosabertos/processo
  - cota parlamentar (CEAPS)                            adm.senado.gov.br/adm-dadosabertos

Só usa a biblioteca padrão. Arquivos já baixados são reaproveitados (REFRESH=1 força novo download).
"""
import http.client
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "data_raw", "senado")
BASE = "https://legis.senado.leg.br/dadosabertos"
YEARS = [2023, 2024, 2025, 2026]
SIGLAS = ["PL", "PLP", "PEC", "PDL", "PRS"]  # tipos de proposição listados no perfil
REFRESH = bool(os.environ.get("REFRESH"))


def get(url, dest):
    """GET com cache em disco, novas tentativas e pausa curta entre chamadas."""
    path = os.path.join(RAW, dest)
    if os.path.exists(path) and os.path.getsize(path) > 2 and not REFRESH:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "como-votar/1.0"})
    for tentativa in range(5):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                dados = r.read()
            json.loads(dados)  # garante JSON válido antes de gravar
            with open(path, "wb") as f:
                f.write(dados)
            time.sleep(0.1)
            return json.loads(dados)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:  # rede, HTTP 5xx, corpo truncado
            espera = 3 * (tentativa + 1)
            print(f"  falha em {url} ({e}); nova tentativa em {espera}s", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"não foi possível baixar {url}")


def main():
    os.makedirs(RAW, exist_ok=True)
    # votações nominais (todas, inclusive secretas: servem para presença) e orientações
    votacoes = []
    for y in YEARS:
        print(f"votações {y}")
        votacoes += get(f"{BASE}/votacao?dataInicio={y}-01-01&dataFim={y}-12-31", f"votacao-{y}.json")
        get(f"{BASE}/plenario/votacao/orientacaoBancada/{y}0101/{y}1231", f"orient-{y}.json")
    atual = get(f"{BASE}/senador/lista/atual", "atual.json")
    get(f"{BASE}/senador/lista/legislatura/57", "lista57.json")

    # senadores que aparecem nas votações + em exercício hoje
    codigos = {str(v["codigoParlamentar"]) for votacao in votacoes for v in votacao["votos"]}
    codigos |= {p["IdentificacaoParlamentar"]["CodigoParlamentar"]
                for p in atual["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]}
    print(f"{len(codigos)} senadores: detalhe e autorias")
    for i, c in enumerate(sorted(codigos, key=int), 1):
        get(f"{BASE}/senador/{c}", f"det/{c}.json")
        get(f"{BASE}/senador/{c}/autorias", f"aut/{c}.json")
        if i % 25 == 0:
            print(f"  {i}/{len(codigos)}")

    # situação das proposições (uma lista por tipo e ano)
    for sigla in SIGLAS:
        for y in YEARS:
            get(f"{BASE}/processo?sigla={sigla}&ano={y}", f"proc-{sigla}-{y}.json")

    # tema (classificação) dos processos votados abertamente
    ids = sorted({v["idProcesso"] for v in votacoes if v.get("votacaoSecreta") == "N" and v.get("idProcesso")})
    print(f"{len(ids)} processos votados: classificação temática")
    for i in ids:
        get(f"{BASE}/processo/{i}", f"procdet/{i}.json")

    # cota parlamentar (CEAPS)
    for y in YEARS:
        print(f"CEAPS {y}")
        get(f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{y}", f"ceaps-{y}.json")
    print("ok")


if __name__ == "__main__":
    main()

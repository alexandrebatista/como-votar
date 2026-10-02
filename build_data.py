#!/usr/bin/env python3
"""Processa os CSVs em lote da Câmara (data_raw/) e gera JSONs compactos em web/data/.

Saídas:
  web/data/meta.json         data de geração, período, médias nacionais/por UF
  web/data/deputados.json    lista resumida (busca + métricas principais)
  web/data/votacoes.json     votações nominais do Plenário (metadados)
  web/data/d/<id>.json       detalhe de cada deputado (propostas, votos, gastos, presença)

Só usa a biblioteca padrão (Python 3.9+).
"""
import csv
import difflib
import json
import os
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

csv.field_size_limit(sys.maxsize)
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "data_raw")
OUT = os.path.join(ROOT, "web", "data")
YEARS = [2023, 2024, 2025, 2026]  # legislatura 57

# Tipos de proposição considerados "propostas legislativas" (o resto é requerimento, indicação etc.)
TIPOS_PRINCIPAIS = {"PL", "PLP", "PEC", "PDL", "PRC", "PLV", "PFC", "PLN", "PLC", "PLS", "PRS"}
MIN_MESES_MEDIA = 6  # só entra nas médias quem exerceu o mandato por pelo menos isso
VOTO_COD = {"Sim": "S", "Não": "N", "Abstenção": "A", "Obstrução": "O"}


ORIENT_COD = {"Sim": "S", "Não": "N", "Obstrução": "O", "Liberado": "L", "Abstenção": "A", "": ""}
FED_PT = {"PT", "PCdoB", "PV"}
FED_PSDB = {"PSDB", "CIDADANIA"}
# Membros de cada "bancada" que aparece em votacoesOrientacoes (rótulo do arquivo -> siglas de partido).
# Blocos vêm com nome truncado; a composição abaixo segue os nomes/ordem publicados pela Câmara
# (/blocos, legislatura 57). Rótulos que não conseguimos resolver com segurança ficam de fora.
BANCADAS = {
    "PL": {"PL"}, "Novo": {"NOVO"}, "PSB": {"PSB"}, "PP": {"PP"}, "Patriota": {"PATRIOTA"},
    "Solidaried": {"SOLIDARIEDADE"}, "PDT": {"PDT"}, "União": {"UNIÃO"}, "Avante": {"AVANTE"},
    "Podemos": {"PODE"}, "Republican": {"REPUBLICANOS"}, "MDB": {"MDB"}, "PSD": {"PSD"}, "PRD": {"PRD"},
    "Missão": {"MISSÃO"}, "DC": {"DC"}, "PSOL": {"PSOL"}, "PT": {"PT"},
    "Fdr PT-PCdoB-PV": FED_PT, "Fdr PSOL-REDE": {"PSOL", "REDE"}, "Fdr PSDB-CIDADANIA": FED_PSDB,
    "Bl MdbPsdRepPode": {"MDB", "PSD", "REPUBLICANOS", "PODE"},
    "Bl MdbPsdRepPodePsc": {"MDB", "PSD", "REPUBLICANOS", "PODE", "PSC"},
    "Bl UniPpFdrPsdbCid...": {"UNIÃO", "PP"} | FED_PSDB,
    "Bl UniPpPsd...": {"UNIÃO", "PP", "PSD", "REPUBLICANOS", "MDB", "PODE"} | FED_PSDB,
    "Bl AvanSolidPrd...": {"AVANTE", "SOLIDARIEDADE", "PRD"},
}
GRUPO_NOME = {"esquerda": "Esquerda", "centro": "Centro", "direita": "Direita"}


def load_ideologia():
    with open(os.path.join(ROOT, "ideologia.json"), encoding="utf-8") as f:
        ide = json.load(f)
    out = {}
    for sigla, d in ide["partidos"].items():
        faixa = next(x for x in ide["faixas"] if x["min"] <= d["nota"] <= x["max"] + 0.0049)
        out[sigla] = {"nota": d["nota"], "faixa": faixa["id"], "campo": faixa["campo"],
                      "estimado": bool(d.get("estimado")), "obs": d.get("obs", "")}
    return ide, out


def rd(name):
    with open(os.path.join(RAW, name), encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter=";")


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def ym_range(a, b):
    """Lista de 'AAAA-MM' de a até b (inclusive)."""
    y, m = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    out = []
    while (y, m) <= (yb, mb):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def periodos_exercicio(historico, fim_geral, inicio_leg="2023-02-01"):
    """Intervalos [ini, fim] (datas AAAA-MM-DD) em que o deputado ocupou a cadeira na legislatura, a partir do
    histórico de situação da Câmara. Só 'Exercício' conta: licença, suspensão, suplência, vacância e fim de mandato
    encerram o intervalo; 'CONVOCADO' (aguardando posse) e entradas sem situação não mudam o estado."""
    ev = sorted((x["dataHora"][:10], x["situacao"]) for x in historico if x.get("situacao") not in (None, "CONVOCADO"))
    out, ini = [], None
    for dt, sit in ev:
        if sit == "Exercício":
            if ini is None:
                ini = dt
        elif ini is not None:
            out.append([ini, dt])
            ini = None
    if ini is not None:
        out.append([ini, fim_geral])
    res = []
    for a, b in out:
        a, b = max(a, inicio_leg), min(b, fim_geral)
        if a <= b:
            res.append([a, b])
    return res


def em_periodos(periodos, d):
    return any(a <= d <= b for a, b in periodos)


def escalar(votos_por_dep, colunas, min_votos_dep=30, iteracoes=40):
    """Posição unidimensional de cada deputado a partir dos votos (Sim=+1, Não=-1), modelo de posto 1 com
    média por votação: x_ij ~ m_j + a_i * b_j, por mínimos quadrados alternados. Devolve {deputado: a_i}
    (média 0, desvio 1, sinal arbitrário)."""
    obs = {}
    for dep, v in votos_por_dep.items():
        r = {j: (1.0 if v[c] == "S" else -1.0) for j, c in enumerate(colunas) if v.get(c) in ("S", "N")}
        if len(r) >= min_votos_dep:
            obs[dep] = r
    soma, cnt = defaultdict(float), Counter()
    for r in obs.values():
        for j, x in r.items():
            soma[j] += x
            cnt[j] += 1
    media = {j: soma[j] / cnt[j] for j in cnt}
    R = {dep: {j: x - media[j] for j, x in r.items()} for dep, r in obs.items()}
    a = {dep: sum(r.values()) or 1e-3 for dep, r in R.items()}  # ponto de partida determinístico
    for _ in range(iteracoes):
        num, den = defaultdict(float), defaultdict(float)
        for dep, r in R.items():
            for j, x in r.items():
                num[j] += x * a[dep]
                den[j] += a[dep] ** 2
        b = {j: num[j] / den[j] for j in num if den[j]}
        for dep, r in R.items():
            n_ = sum(x * b[j] for j, x in r.items() if j in b)
            d_ = sum(b[j] ** 2 for j in r if j in b)
            a[dep] = n_ / d_ if d_ else 0.0
        mu = statistics.mean(a.values())
        sd = statistics.pstdev(a.values()) or 1.0
        a = {dep: (x - mu) / sd for dep, x in a.items()}
    return a


def correlacao(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def percentil(vals, p):
    v = sorted(vals)
    k = (len(v) - 1) * p
    lo = int(k)
    return v[lo] + (v[min(lo + 1, len(v) - 1)] - v[lo]) * (k - lo)


def _norm(s):
    return " ".join(unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().upper().split())


def _iso(d):  # "dd/mm/aaaa" -> "aaaa-mm-dd"
    p = d.strip().split("/")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else ""


def candidaturas(deps, civil=None, cargo_proprio="DEPUTADO FEDERAL"):
    """Cruza os parlamentares (deps) com o registro de candidaturas de 2026 do TSE.

    civil: {id: (nome civil normalizado, data de nascimento AAAA-MM-DD)}; se omitido, usa o arquivo de deputados.
    cargo_proprio: cargo do próprio mandato (candidatura a ele = reeleição).


    O arquivo do TSE é um retrato que mantém registros já substituídos (a coluna de situação vem em branco),
    então:
    1) reúne TODOS os registros da mesma pessoa: nome civil + data de nascimento (exato) e, na mesma data de
       nascimento e UF, registros com nome parecido (similaridade >= 0.75), igual ao nome parlamentar ou com o
       mesmo nome de urna (cobre grafias diferentes do nome civil);
    2) descarta o registro cujo número de urna (mesma UF e cargo) foi assumido depois (SQ_CANDIDATO maior) por
       outra pessoa: é uma substituição;
    3) se sobrar mais de um registro para cargos/números diferentes, usa o mais recente e sinaliza os demais.
    Devolve ({id: candidatura}, {id: registros substituídos}, data de geração do arquivo)."""
    with open(os.path.join(RAW, "consulta_cand_2026_BRASIL.csv"), encoding="latin-1", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    gerado = linhas[0]["DT_GERACAO"] if linhas else ""
    por_chave, por_data, por_numero = defaultdict(list), defaultdict(list), defaultdict(list)
    for x in linhas:
        x["_nome"] = _norm(x["NM_CANDIDATO"])
        x["_urna"] = _norm(x["NM_URNA_CANDIDATO"])
        x["_sq"] = int(x["SQ_CANDIDATO"])
        por_chave[(x["_nome"], _iso(x["DT_NASCIMENTO"]))].append(x)
        por_data[_iso(x["DT_NASCIMENTO"])].append(x)
        por_numero[(x["SG_UF"], x["DS_CARGO"], x["NR_CANDIDATO"])].append(x)

    def cedido_a(x):  # outras pessoas que registraram depois o mesmo número (UF + cargo)
        return [y for y in por_numero[(x["SG_UF"], x["DS_CARGO"], x["NR_CANDIDATO"])]
                if y["DT_NASCIMENTO"] != x["DT_NASCIMENTO"] and y["_sq"] > x["_sq"]]

    if civil is None:
        civil = {}
        for r in rd("deputados-csv.csv"):
            civil[int(r["uri"].rsplit("/", 1)[1])] = (_norm(r["nomeCivil"]), r["dataNascimento"])
    out, substituidos = {}, {}
    for dep, info in deps.items():
        nome, nasc = civil.get(dep, ("", ""))
        recs, modo = list(por_chave.get((nome, nasc), [])), "exato"
        if nasc:
            urnas = {x["_urna"] for x in recs} | {_norm(info["nome"])}
            vistos = {x["_sq"] for x in recs}
            extra = [x for x in por_data.get(nasc, []) if x["_sq"] not in vistos and x["SG_UF"] == info["uf"] and (
                difflib.SequenceMatcher(None, nome, x["_nome"]).ratio() >= 0.75
                or x["_urna"] in urnas or _norm(info["nome"]) == x["_nome"])]
            if extra and not recs:
                modo = "aproximado"
            recs += extra
        if not recs:
            continue
        vivos = [x for x in recs if not cedido_a(x)]
        if not vivos:  # todos os registros tiveram o número assumido por outra pessoa
            substituidos[dep] = [{"cargo": x["DS_CARGO"].title(), "numero": x["NR_CANDIDATO"], "uf": x["SG_UF"],
                                  "cedido_a": sorted({y["NM_URNA_CANDIDATO"].title() for y in cedido_a(x)})} for x in recs]
            continue
        vivos.sort(key=lambda x: x["_sq"])
        x = vivos[-1]
        chave = lambda r: (r["DS_CARGO"], r["NR_CANDIDATO"], r["SG_UF"])
        outros = [{"cargo": r["DS_CARGO"].title(), "numero": r["NR_CANDIDATO"], "uf": r["SG_UF"]}
                  for r in vivos[:-1] if chave(r) != chave(x)]
        out[dep] = {"cargo": x["DS_CARGO"].title(), "uf": x["SG_UF"], "partido": x["SG_PARTIDO"],
                    "numero": x["NR_CANDIDATO"], "nome_urna": x["NM_URNA_CANDIDATO"].title(),
                    "reeleicao": x["DS_CARGO"] == cargo_proprio, "cruzamento": modo,
                    "outros_registros": outros,
                    "substituidos": [{"cargo": r["DS_CARGO"].title(), "numero": r["NR_CANDIDATO"]} for r in recs if cedido_a(r)]}
    return out, substituidos, gerado


def main():
    os.makedirs(os.path.join(OUT, "d"), exist_ok=True)

    # ---------- deputados ----------
    with open(os.path.join(RAW, "deputados.json"), encoding="utf-8") as f:
        raw = json.load(f)["dados"]
    deps = {}
    for d in raw:
        deps[d["id"]] = {
            "id": d["id"], "nome": d["nome"], "partido": d["siglaPartido"], "uf": d["siglaUf"],
            "foto": d["urlFoto"],
        }
    print(f"{len(deps)} deputados na legislatura 57")
    with open(os.path.join(RAW, "deputados-atuais.json"), encoding="utf-8") as f:
        em_exercicio = {d["id"] for d in json.load(f)["dados"]}  # quem ocupa cadeira hoje (513)
    for i, d in deps.items():
        d["em_exercicio"] = i in em_exercicio
    cands, cand_subst, cand_gerado = candidaturas(deps)
    print(f"{len(cands)} deputados com candidatura em 2026 ({sum(c['reeleicao'] for c in cands.values())} à reeleição); "
          f"{len(cand_subst)} só com registro substituído; {sum(1 for c in cands.values() if c['outros_registros'])} com mais de um registro")

    # ---------- sessões deliberativas do Plenário ----------
    sessoes = {}  # idEvento -> data
    for y in YEARS:
        for r in rd(f"eventos-{y}.csv"):
            if r["descricaoTipo"] == "Sessão Deliberativa" and r["localCamara.nome"].startswith("Plenário da Câmara"):
                sessoes[r["id"]] = r["dataHoraInicio"][:10]
    print(f"{len(sessoes)} sessões deliberativas do Plenário")

    # ---------- presença ----------
    pres_sess = defaultdict(set)  # dep -> idEventos deliberativos com presença
    first_seen, last_seen = {}, {}  # período de exercício (proxy): 1º e último registro de presença
    for y in YEARS:
        for r in rd(f"presenca-{y}.csv"):
            dep = int(r["idDeputado"])
            dt = r["dataHoraInicio"][:10]
            if dep not in first_seen or dt < first_seen[dep]:
                first_seen[dep] = dt
            if dep not in last_seen or dt > last_seen[dep]:
                last_seen[dep] = dt
            if r["idEvento"] in sessoes:
                pres_sess[dep].add(r["idEvento"])

    # ---------- votações ----------
    votacoes = {}  # id -> dict
    for y in YEARS:
        for r in rd(f"votacoes-{y}.csv"):
            if r["siglaOrgao"] == "PLEN":
                votacoes[r["id"]] = {
                    "id": r["id"], "data": r["data"], "desc": r["descricao"].strip()[:400],
                    "sim": int(num(r["votosSim"])), "nao": int(num(r["votosNao"])),
                    "outros": int(num(r["votosOutros"])), "aprov": r["aprovacao"],
                    "prop_alt": r["ultimaApresentacaoProposicao_idProposicao"],
                }
    props = {}  # idProposicao -> {t, e}
    vot_prop = defaultdict(list)
    for y in YEARS:
        for r in rd(f"votprop-{y}.csv"):
            if r["idVotacao"] not in votacoes:
                continue
            pid = r["proposicao_id"]
            props[pid] = {"t": r["proposicao_titulo"], "e": r["proposicao_ementa"].strip()[:500],
                          "tp": r["proposicao_siglaTipo"]}
            vot_prop[r["idVotacao"]].append(pid)

    # ---------- votos individuais ----------
    votos_dep = defaultdict(dict)  # dep -> {idVotacao: código}
    party_cnt = defaultdict(lambda: defaultdict(Counter))  # votacao -> partido -> Counter(S/N)
    dep_party_vot = defaultdict(dict)  # dep -> {idVotacao: partido à época}
    for y in YEARS:
        for r in rd(f"votos-{y}.csv"):
            vid = r["idVotacao"]
            cod = VOTO_COD.get(r["voto"])
            if vid not in votacoes or cod is None:
                continue  # ignora votações de comissão, "Artigo 17" (presidente) e vazios
            dep = int(r["deputado_id"])
            votos_dep[dep][vid] = cod
            dep_party_vot[dep][vid] = r["deputado_siglaPartido"]
            party_cnt[vid][r["deputado_siglaPartido"]][cod] += 1
            # amplia o período de exercício também pelos votos
            dt = r["dataHoraVoto"][:10]
            if dep not in first_seen or dt < first_seen[dep]:
                first_seen[dep] = dt
            if dep not in last_seen or dt > last_seen[dep]:
                last_seen[dep] = dt
    # mantém só votações que tiveram voto nominal
    votacoes = {k: v for k, v in votacoes.items() if k in party_cnt}
    print(f"{len(votacoes)} votações nominais no Plenário")

    # ---------- orientações oficiais das lideranças ----------
    ide_raw, ideologia = load_ideologia()
    orient = defaultdict(dict)  # votação -> rótulo da bancada -> código
    for y in YEARS:
        for r in rd(f"orient-{y}.csv"):
            if r["idVotacao"] in votacoes and r["siglaOrgao"] == "PLEN":
                orient[r["idVotacao"]][r["siglaBancada"]] = ORIENT_COD.get(r["orientacao"], "")

    # Blocos cujo nome vem truncado e não estão em BANCADAS: deduz a composição. Em votações com um único
    # rótulo de bloco desconhecido, os partidos sem nenhuma outra linha (própria, federação ou bloco
    # conhecido) só podem estar nele. Vale como membro quem falta em >= 80% dessas votações.
    faltando = defaultdict(Counter)
    total_rot = Counter()
    for vid, labels in orient.items():
        desconhecidos = [l for l in labels if l.startswith("Bl") and l not in BANCADAS]
        if len(desconhecidos) != 1:
            continue
        cobertos = set().union(*[BANCADAS[l] for l in labels if l in BANCADAS]) if labels else set()
        total_rot[desconhecidos[0]] += 1
        for partido in set(party_cnt[vid]) - cobertos:
            faltando[desconhecidos[0]][partido] += 1
    inferidas = {rot: {pt for pt, n in c.items() if n >= 0.8 * total_rot[rot]} for rot, c in faltando.items()}
    for rot, membros in inferidas.items():
        print(f"bloco inferido {rot!r}: {sorted(membros)}")
    bancadas = {**BANCADAS, **inferidas}

    def orient_partido(vid, partido):
        """Orientação da bancada mais específica (partido < federação < bloco) a que o partido pertence."""
        cands = [(len(bancadas[l]), l) for l in orient[vid] if l in bancadas and partido in bancadas[l]]
        return orient[vid][min(cands)[1]] if cands else ""

    # maioria de cada campo ideológico em cada votação (só votos Sim/Não)
    campo_cnt = defaultdict(lambda: defaultdict(Counter))
    for vid, partidos in party_cnt.items():
        for partido, c in partidos.items():
            campo = ideologia.get(partido, {}).get("campo")
            if campo:
                for cod in ("S", "N"):
                    campo_cnt[vid][campo][cod] += c[cod]

    def campo_major(vid, campo):
        c = campo_cnt[vid][campo]
        tot = c["S"] + c["N"]
        if tot < 5 or c["S"] == c["N"]:
            return ""
        return "S" if c["S"] > c["N"] else "N"

    def party_major(vid, partido):
        c = party_cnt[vid][partido]
        if not c:
            return ""
        top = c.most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            return ""  # empate: sem maioria
        return top[0][0]

    # Proposição "principal" de cada votação (prefere tipos legislativos)
    vot_out = []
    vid_index = {}
    for vid in sorted(votacoes, key=lambda k: (votacoes[k]["data"], k)):
        v = votacoes[vid]
        pids = vot_prop.get(vid) or ([v["prop_alt"]] if v["prop_alt"] not in ("", "0") else [])
        pid = None
        for p in pids:
            if p in props and props[p]["tp"] in TIPOS_PRINCIPAIS:
                pid = p
                break
        if pid is None and pids:
            pid = pids[0]
        vid_index[vid] = len(vot_out)
        vot_out.append([vid, v["data"], pid, v["desc"], v["sim"], v["nao"], v["outros"], v["aprov"],
                        orient[vid].get("Governo", ""), campo_major(vid, "esquerda"),
                        campo_major(vid, "centro"), campo_major(vid, "direita")])
    # temas oficiais da Câmara (arquivos por ano de apresentação da proposição)
    temas_nome, temas_prop = {}, defaultdict(list)
    for y in range(2003, YEARS[-1] + 1):
        path = os.path.join(RAW, f"temas-{y}.csv")
        if not os.path.exists(path):
            continue
        for r in rd(f"temas-{y}.csv"):
            pid = r["uriProposicao"].rsplit("/", 1)[1]
            cod = int(r["codTema"])
            temas_nome[cod] = r["tema"]
            if cod not in temas_prop[pid]:
                temas_prop[pid].append(cod)
    prop_out = {}
    for row in vot_out:
        pid = row[2]
        if pid and pid in props:
            prop_out[pid] = {"t": props[pid]["t"], "e": props[pid]["e"], "tp": props[pid]["tp"],
                             "tm": temas_prop.get(pid, [])}
    sem_tema = sum(1 for p in prop_out.values() if not p["tm"])
    print(f"{len(prop_out)} proposições votadas, {sem_tema} sem tema oficial")
    with open(os.path.join(OUT, "votacoes.json"), "w", encoding="utf-8") as f:
        json.dump({"votacoes": vot_out, "proposicoes": prop_out,
                   "temas": {str(k): v for k, v in sorted(temas_nome.items(), key=lambda kv: kv[1])}},
                  f, ensure_ascii=False, separators=(",", ":"))

    # ---------- posição ideológica pelo voto ----------
    # Duas escalas: (A) todas as votações contestadas -> na prática mede governo x oposição (só diagnóstico);
    # (B) só votações em que o Governo NÃO orientou Sim/Não -> usada como "posição pelo voto".
    sim_nao = defaultdict(Counter)
    for d, v in votos_dep.items():
        for vid, c in v.items():
            if c in ("S", "N"):
                sim_nao[vid][c] += 1
    def contestada(row):
        c = sim_nao[row[0]]
        tot = c["S"] + c["N"]
        return tot >= 100 and min(c["S"], c["N"]) / tot >= 0.10
    colsA = [row[0] for row in vot_out if contestada(row)]
    colsB = [row[0] for row in vot_out if contestada(row) and row[8] not in ("S", "N")]

    def orientar(esc):  # sinal: PSOL à esquerda (menor) do PL — única âncora externa
        def med(p):
            v = [x for d, x in esc.items() if deps[d]["partido"] == p]
            return statistics.median(v) if v else 0
        return esc if med("PSOL") <= med("PL") else {d: -x for d, x in esc.items()}
    escA = orientar(escalar(votos_dep, colsA))
    escB = orientar(escalar(votos_dep, colsB))
    lo, hi = percentil(list(escB.values()), 0.02), percentil(list(escB.values()), 0.98)
    faixas_ide = ide_raw["faixas"]
    def faixa_de(nota):
        return next(f for f in faixas_ide if f["min"] <= nota <= f["max"] + 0.0049)
    voto_ide = {}
    for d, x in escB.items():
        nota = round(min(max(10 * (x - lo) / (hi - lo), 0), 10), 2)
        f = faixa_de(nota)
        voto_ide[d] = {"nota": nota, "faixa": f["id"], "campo": f["campo"],
                       "n": sum(1 for c in colsB if votos_dep[d].get(c) in ("S", "N"))}
    por_partido = defaultdict(list)
    for d, v in voto_ide.items():
        por_partido[deps[d]["partido"]].append(v["nota"])
    partidos_voto = {}
    for p, notas in por_partido.items():
        med = round(statistics.median(notas), 2)
        partidos_voto[p] = {"nota": med, "faixa": faixa_de(med)["id"], "n": len(notas),
                            "q1": round(percentil(notas, 0.25), 2), "q3": round(percentil(notas, 0.75), 2)}

    def corr_gov(esc):  # correlação com o % de votos iguais à orientação do Governo
        xs, ys = [], []
        for d, x in esc.items():
            ok = tot = 0
            for row in vot_out:
                c = votos_dep[d].get(row[0])
                if row[8] in ("S", "N") and c in ("S", "N"):
                    tot += 1
                    ok += c == row[8]
            if tot >= 30:
                xs.append(x); ys.append(ok / tot)
        return correlacao(xs, ys)
    def corr_pesquisa(esc):
        pares = [(x, ideologia[deps[d]["partido"]]["nota"]) for d, x in esc.items() if deps[d]["partido"] in ideologia]
        return correlacao(*zip(*pares))
    diag = {"votacoes_A": len(colsA), "votacoes_B": len(colsB), "n_deputados": len(escB),
            "A": {"corr_governo": round(abs(corr_gov(escA)), 2), "corr_pesquisa": round(abs(corr_pesquisa(escA)), 2)},
            "B": {"corr_governo": round(abs(corr_gov(escB)), 2), "corr_pesquisa": round(abs(corr_pesquisa(escB)), 2)}}
    print("escala pelo voto:", diag)
    with open(os.path.join(OUT, "ideologia_voto.json"), "w", encoding="utf-8") as f:
        json.dump({"partidos": partidos_voto, "diagnostico": diag, "min_votos": 30},
                  f, ensure_ascii=False, separators=(",", ":"))

    # ---------- proposições de autoria ----------
    autor = defaultdict(list)  # dep -> [(idProp, ordem)]
    for y in YEARS:
        for r in rd(f"autores-{y}.csv"):
            if r["codTipoAutor"] == "10000" and r["idDeputadoAutor"]:
                autor[int(r["idDeputadoAutor"])].append((r["idProposicao"], int(r["ordemAssinatura"] or 0)))
    need = {p for lst in autor.values() for p, _ in lst}
    pinfo = {}
    for y in YEARS:
        for r in rd(f"proposicoes-{y}.csv"):
            if r["id"] in need:
                sit = r["ultimoStatus_descricaoSituacao"] or r["ultimoStatus_descricaoTramitacao"]
                pinfo[r["id"]] = {
                    "id": r["id"], "tp": r["siglaTipo"], "n": r["numero"], "a": r["ano"],
                    "e": r["ementa"].strip()[:400], "d": r["dataApresentacao"][:10], "s": sit,
                }

    # ---------- gastos (CEAP) ----------
    gasto_mes = defaultdict(lambda: defaultdict(float))  # dep -> ym -> total
    gasto_cat = defaultdict(lambda: defaultdict(float))  # dep -> categoria -> total
    ultimo_ym = "0000-00"
    for y in YEARS:
        for r in rd(f"ceap-{y}.csv"):
            try:
                dep = int(r["ideCadastro"])  # ideCadastro = id da API (nuDeputadoId é interno do gabinete)
            except ValueError:
                continue
            if dep not in deps:
                continue  # lideranças e afins
            ym = f"{int(r['numAno'])}-{int(r['numMes']):02d}"
            v = num(r["vlrLiquido"])
            gasto_mes[dep][ym] += v
            gasto_cat[dep][r["txtDescricao"].strip().rstrip(".")] += v
            if ym > ultimo_ym:
                ultimo_ym = ym

    # ---------- período de exercício ----------
    sess_por_data = sorted((d, i) for i, d in sessoes.items())
    fim_geral = max(last_seen.values())
    # Período real de exercício: histórico de situação da Câmara (data_raw/historico/<id>.json), para não contar
    # como mandato os meses em que o titular/suplente estava fora da cadeira. Sem histórico, cai no 1º/último registro.
    periodos = {}
    for dep in deps:
        hp = os.path.join(RAW, "historico", f"{dep}.json")
        if os.path.exists(hp):
            with open(hp, encoding="utf-8") as f:
                periodos[dep] = periodos_exercicio(json.load(f)["dados"], fim_geral)
        elif dep in first_seen:
            periodos[dep] = [[first_seen[dep], last_seen[dep]]]
    ativos, meses_ex = {}, {}
    for dep, per in periodos.items():
        if per:
            ativos[dep] = (per[0][0], per[-1][1])  # primeiro dia e último dia de exercício (para exibição)
            meses_ex[dep] = sorted({m for a, b in per for m in ym_range(a[:7], b[:7])})
    sem_hist = sum(1 for d in deps if not os.path.exists(os.path.join(RAW, "historico", f"{d}.json")))
    print(f"{len(ativos)} deputados com período de exercício ({sem_hist} sem histórico);",
          f"{sum(1 for p in periodos.values() if len(p) > 1)} com mais de um intervalo")
    # mês em que os dados vão até (evita contar meses futuros/incompletos demais)
    print("dados até", fim_geral, "| CEAP até", ultimo_ym)

    # ---------- janela de gastos: só meses completos ----------
    # A CEAP é lançada com atraso; os últimos meses saem incompletos e derrubariam as médias.
    # Corte: último mês cuja média nacional é >= 80% da mediana dos 12 meses anteriores.
    serie_nac = {}
    for m in ym_range("2023-02", ultimo_ym):
        ativos_m = [d for d in ativos if m in meses_ex[d]]
        if ativos_m:
            serie_nac[m] = round(statistics.mean(gasto_mes[d].get(m, 0.0) for d in ativos_m), 2)
    ms = sorted(serie_nac)
    ceap_fim = ms[0]
    for i, m in enumerate(ms):
        hist = [serie_nac[x] for x in ms[max(0, i - 12):i]]
        if not hist or serie_nac[m] >= 0.8 * statistics.median(hist):
            ceap_fim = m
        else:
            break
    print("CEAP considerada até", ceap_fim, "(dados brutos até", ultimo_ym + ")")

    # ---------- métricas por deputado ----------
    resumo = {}
    for dep, info in deps.items():
        if dep not in ativos:
            continue
        ini, fim = ativos[dep]
        meses = [m for m in meses_ex[dep] if m <= ceap_fim]
        n_meses = max(len(meses), 1)
        total = sum(gasto_mes[dep].get(m, 0.0) for m in meses)
        # presença
        sess_periodo = [i for d, i in sess_por_data if em_periodos(periodos[dep], d)]
        pres = [i for i in sess_periodo if i in pres_sess[dep]]
        vots_periodo = [vid for vid, v in votacoes.items() if em_periodos(periodos[dep], v["data"])]
        votos_periodo = sum(1 for vid in vots_periodo if vid in votos_dep[dep])
        resumo[dep] = {
            **info,
            "faixa": ideologia.get(info["partido"], {}).get("faixa"),
            "voto_nota": voto_ide.get(dep, {}).get("nota"),
            "voto_faixa": voto_ide.get(dep, {}).get("faixa"),
            "cand": ("reeleicao" if cands[dep]["reeleicao"] else "outro") if dep in cands else "nao",
            "cand_numero": cands[dep]["numero"] if dep in cands else None,
            "cand_cargo": cands[dep]["cargo"] if dep in cands else None,
            # observação sobre o registro: 'substituido' (só há registro cujo número foi assumido por outra pessoa)
            # ou 'multiplos' (mais de um registro em vigor; usamos o mais recente)
            "cand_obs": "substituido" if dep in cand_subst else ("multiplos" if dep in cands and cands[dep]["outros_registros"] else None),
            "inicio": ini, "fim": fim, "meses": n_meses,
            "gasto_total": round(total, 2), "gasto_mensal": round(total / n_meses, 2),
            "sessoes": len(sess_periodo), "presencas": len(pres),
            "pct_presenca": round(100 * len(pres) / len(sess_periodo), 1) if sess_periodo else None,
            "votacoes_periodo": len(vots_periodo), "votos": votos_periodo,
            "pct_votos": round(100 * votos_periodo / len(vots_periodo), 1) if vots_periodo else None,
        }
        ps = autor.get(dep, [])
        resumo[dep]["n_prop"] = sum(1 for p, o in ps if o == 1 and p in pinfo and pinfo[p]["tp"] in TIPOS_PRINCIPAIS)
        resumo[dep]["n_leis"] = sum(1 for p, o in ps if o == 1 and p in pinfo and pinfo[p]["tp"] in TIPOS_PRINCIPAIS
                                    and pinfo[p]["s"] == "Transformado em Norma Jurídica")

    # ---------- médias de comparação ----------
    elegiveis = [d for d, r in resumo.items() if r["meses"] >= MIN_MESES_MEDIA]
    def media(ids, key):
        vals = [resumo[i][key] for i in ids if resumo[i][key] is not None]
        return round(statistics.mean(vals), 2) if vals else None
    def mediana(ids, key):
        vals = [resumo[i][key] for i in ids if resumo[i][key] is not None]
        return round(statistics.median(vals), 2) if vals else None
    por_uf = defaultdict(list)
    for d in elegiveis:
        por_uf[resumo[d]["uf"]].append(d)
    campos = ["gasto_mensal", "pct_presenca", "pct_votos"]
    nacional = {k: {"media": media(elegiveis, k), "mediana": mediana(elegiveis, k)} for k in campos}
    ufs = {uf: {k: {"media": media(ids, k), "mediana": mediana(ids, k)} for k in campos} | {"n": len(ids)}
           for uf, ids in por_uf.items()}
    nacional["n"] = len(elegiveis)

    # categorias: gasto mensal médio por categoria (mesma base de meses de cada deputado)
    cats = sorted({c for d in elegiveis for c in gasto_cat[d]})
    def cat_mensal(dep, c):
        return gasto_cat[dep].get(c, 0.0) / resumo[dep]["meses"]
    cat_nac = {c: round(statistics.mean(cat_mensal(d, c) for d in elegiveis), 2) for c in cats}
    cat_uf = {uf: {c: round(statistics.mean(cat_mensal(d, c) for d in ids), 2) for c in cats}
              for uf, ids in por_uf.items()}
    # ---------- arquivos por deputado ----------
    sess_datas = dict(sessoes)
    for dep, r in resumo.items():
        ini, fim = r["inicio"], r["fim"]
        # propostas
        lista, contagem = [], Counter()
        for p, ordem in autor.get(dep, []):
            pi = pinfo.get(p)
            if not pi:
                continue
            contagem[pi["tp"]] += 1
            if pi["tp"] in TIPOS_PRINCIPAIS:
                lista.append({**pi, "autor_principal": ordem == 1})
        lista.sort(key=lambda x: x["d"], reverse=True)
        # votos: [indice_votacao, meu_voto, voto_da_maioria_do_partido]
        vs = []
        for vid, cod in votos_dep[dep].items():
            partido = dep_party_vot[dep][vid]
            vs.append([vid_index[vid], cod, party_major(vid, partido), partido, orient_partido(vid, partido)])
        vs.sort()
        seguiu = sum(1 for v in vs if v[2] and v[1] == v[2])
        def alinh(ref):  # ref(v) -> código de referência; conta só quando há referência Sim/Não/Obstrução
            tot = ok = 0
            for v in vs:
                c = ref(v)
                if c in ("S", "N", "O"):
                    tot += 1
                    ok += v[1] == c
            return [ok, tot]
        alinhamento = {
            "orientacao": alinh(lambda v: v[4]),
            "governo": alinh(lambda v: vot_out[v[0]][8]),
            "esquerda": alinh(lambda v: vot_out[v[0]][9]),
            "centro": alinh(lambda v: vot_out[v[0]][10]),
            "direita": alinh(lambda v: vot_out[v[0]][11]),
        }
        com_maioria = sum(1 for v in vs if v[2])
        # gastos
        meses = [m for m in meses_ex[dep] if m <= ceap_fim]
        serie = [[m, round(gasto_mes[dep].get(m, 0.0), 2)] for m in meses]
        categorias = sorted(
            ([c, round(v, 2), round(v / r["meses"], 2), cat_nac.get(c, 0.0), cat_uf[r["uf"]].get(c, 0.0) if r["uf"] in cat_uf else None]
             for c, v in gasto_cat[dep].items() if abs(v) > 0.005),
            key=lambda x: -x[1])
        # presença por ano
        por_ano = {}
        for y in YEARS:
            sess_y = [i for d, i in sess_por_data if em_periodos(periodos[dep], d) and d.startswith(str(y))]
            if sess_y:
                por_ano[y] = [sum(1 for i in sess_y if i in pres_sess[dep]), len(sess_y)]
        out = {
            **{k: r[k] for k in ("id", "nome", "partido", "uf", "foto", "inicio", "fim", "meses", "em_exercicio")},
            "periodos": periodos[dep],
            "ideologia": ideologia.get(r["partido"]),
            "ideologia_voto": voto_ide.get(dep),
            "candidatura": cands.get(dep),
            "candidatura_substituida": cand_subst.get(dep),
            "partido_voto": partidos_voto.get(r["partido"]),
            "propostas": {"contagem": dict(contagem.most_common()), "lista": lista},
            "votos": {"lista": vs, "total": len(vs), "com_maioria": com_maioria, "seguiu_partido": seguiu, "alinhamento": alinhamento},
            "gastos": {"total": r["gasto_total"], "mensal": r["gasto_mensal"], "serie": serie, "categorias": categorias},
            "presenca": {"presencas": r["presencas"], "sessoes": r["sessoes"], "pct": r["pct_presenca"], "por_ano": por_ano,
                         "votos": r["votos"], "votacoes": r["votacoes_periodo"], "pct_votos": r["pct_votos"]},
        }
        with open(os.path.join(OUT, "d", f"{dep}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        pct_al = lambda k: round(100 * alinhamento[k][0] / alinhamento[k][1], 1) if alinhamento[k][1] else None
        r["pct_orientacao"] = pct_al("orientacao")  # votos iguais à orientação oficial do partido
        r["pct_governo"] = pct_al("governo")        # votos iguais à orientação do Governo
        r["nota_pesquisa"] = ideologia.get(r["partido"], {}).get("nota")

    with open(os.path.join(OUT, "deputados.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(resumo.values(), key=lambda x: x["nome"]), f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "ideologia.json"), "w", encoding="utf-8") as f:
        json.dump({**ide_raw, "partidos": ideologia}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dados_ate": fim_geral, "ceap_ate": ceap_fim, "ceap_bruto_ate": ultimo_ym, "candidaturas_tse_em": cand_gerado, "legislatura": 57,
            "min_meses_media": MIN_MESES_MEDIA,
            "nacional": nacional, "uf": ufs,
            "categorias": {"nacional": cat_nac, "uf": cat_uf},
            "serie_nacional": {m: v for m, v in serie_nac.items() if m <= ceap_fim},
        }, f, ensure_ascii=False, separators=(",", ":"))
    print("ok:", len(resumo), "deputados gerados")


if __name__ == "__main__":
    main()

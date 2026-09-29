#!/usr/bin/env python3
"""Processa os dados do Senado (data_raw/senado/, veja fetch_senado.py) e gera web/data/senado/.

Gera arquivos no MESMO formato dos da Câmara, para o site reaproveitar o código do perfil:
  web/data/senado/senadores.json   lista resumida (busca, tabela e filtros)
  web/data/senado/votacoes.json    votações nominais ABERTAS do Plenário (metadados e temas)
  web/data/senado/d/<codigo>.json  detalhe de cada senador
  web/data/senado/meta.json        médias nacionais/por UF e datas

Diferenças em relação à Câmara (por causa do que o Senado publica):
  - a maior parte das votações nominais é SECRETA (autoridades, vetos etc.): o voto individual só existe nas abertas;
  - a presença é medida nas votações nominais (abertas e secretas) e distingue ausência justificada
    (atividade parlamentar, missão, licença) de não comparecimento;
  - não publicamos posição ideológica "pelo voto": com as poucas votações abertas e contestadas sem orientação
    do Governo, a escala é estável mas acompanha o alinhamento ao Governo (correlação ~0,94) mais que a
    classificação acadêmica dos partidos (~0,62); os valores exatos saem em meta.json -> diagnostico;
  - o tema vem da classificação do processo legislativo (nível mais alto da hierarquia).
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import build_data as bd  # noqa: E402  (reaproveita candidaturas, ideologia, datas)

RAW = os.path.join(ROOT, "data_raw", "senado")
OUT = os.path.join(ROOT, "web", "data", "senado")
YEARS = bd.YEARS
INICIO_LEGISLATURA = "2023-02-01"
MIN_MESES_MEDIA = bd.MIN_MESES_MEDIA

PRESENTE = {"Sim", "Não", "Abstenção", "Obstrução", "Votou", "P-NRV", "Presidente (art. 51 RISF)"}
JUSTIFICADA = {"AP", "MIS", "LS", "LP", "LAP"}  # atividade parlamentar, missão, licença saúde/particular
SEM_JUSTIFICATIVA = {"NCom"}
VOTO_COD = {"Sim": "S", "Não": "N", "Abstenção": "A", "Obstrução": "O"}
ORIENT_COD = {"SIM": "S", "NÃO": "N", "LIVRE": "L", "OBSTRUÇÃO": "O"}
# rótulos de partido das orientações -> sigla usada nos votos
ROTULO_PARTIDO = {"REPUBLICA": "REPUBLICANOS", "REPUBLICANOS": "REPUBLICANOS", "PODEMOS": "PODE", "PROGRESSISTAS": "PP"}
CATEGORIAS = [  # nomes longos da CEAPS -> nomes curtos (por prefixo)
    ("Aluguel de imóveis", "Aluguel de imóveis para escritório político"),
    ("Passagens aéreas", "Passagens aéreas, aquáticas e terrestres"),
    ("Locomoção, hospedagem", "Locomoção, hospedagem, alimentação e combustíveis"),
    ("Contratação de consultorias", "Consultorias, assessorias e serviços de apoio ao mandato"),
    ("Divulgação da atividade", "Divulgação da atividade parlamentar"),
    ("Aquisição de material", "Material de consumo, software e equipamentos do escritório"),
    ("Serviços de Segurança", "Segurança privada"),
]


def load(name):
    with open(os.path.join(RAW, name), encoding="utf-8") as f:
        return json.load(f)


def chave_partido(sigla):
    n = bd._norm(sigla or "")
    return ROTULO_PARTIDO.get(n, n)


def categoria(tipo):
    if not tipo:
        return "Outros"
    for prefixo, nome in CATEGORIAS:
        if tipo.startswith(prefixo):
            return nome
    return tipo.strip()[:80]


def main():
    os.makedirs(os.path.join(OUT, "d"), exist_ok=True)
    ide_raw, ideologia = bd.load_ideologia()

    # ---------- votações nominais ----------
    votacoes = []
    for y in YEARS:
        votacoes += load(f"votacao-{y}.json")
    votacoes.sort(key=lambda v: (v["dataSessao"], v["codigoSessaoVotacao"], v["sequencialVotacao"]))
    abertas = [v for v in votacoes if v["votacaoSecreta"] == "N"]
    print(f"{len(votacoes)} votações nominais, {len(abertas)} abertas")

    # ---------- orientações (chave: data + sequencial da votação) ----------
    orient = {}
    for y in YEARS:
        for o in load(f"orient-{y}.json")["votacoes"]:
            data = (o.get("dataInicioVotacao") or "")[:10]
            orient[(data, o["sequencialVotacao"])] = {
                chave_partido(l["partido"]): ORIENT_COD.get((l.get("voto") or "").upper(), "")
                for l in (o.get("orientacoesLideranca") or [])}

    def orient_de(v):
        return orient.get((v["dataSessao"], v["sequencialVotacao"]), {})

    # ---------- senadores ----------
    atual = load("atual.json")["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    em_exercicio = {int(p["IdentificacaoParlamentar"]["CodigoParlamentar"]) for p in atual}
    info = {}
    ultimo_voto = {}
    for v in votacoes:
        for x in v["votos"]:
            c = x["codigoParlamentar"]
            if c not in ultimo_voto or v["dataSessao"] >= ultimo_voto[c]:
                ultimo_voto[c] = v["dataSessao"]
                info[c] = {"partido": x["siglaPartidoParlamentar"], "uf": x["siglaUFParlamentar"]}
    for c in list(info):
        d = load(f"det/{c}.json")["DetalheParlamentar"]["Parlamentar"]
        ident, basicos = d["IdentificacaoParlamentar"], d.get("DadosBasicosParlamentar", {})
        info[c].update({
            "id": c, "nome": ident["NomeParlamentar"], "nome_civil": ident.get("NomeCompletoParlamentar", ""),
            "foto": (ident.get("UrlFotoParlamentar") or "").replace("http://", "https://"),
            "url_perfil": (ident.get("UrlPaginaParlamentar") or "").replace("http://", "https://"),
            "nasc": basicos.get("DataNascimento", ""), "em_exercicio": c in em_exercicio})
    print(f"{len(info)} senadores na legislatura (com votações)")

    # ---------- presença (todas as votações nominais) ----------
    pres = defaultdict(Counter)       # senador -> contagem por código
    pres_ano = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # senador -> ano -> [presentes, total]
    first_seen, last_seen = {}, {}
    for v in votacoes:
        ano = v["dataSessao"][:4]
        for x in v["votos"]:
            c, cod = x["codigoParlamentar"], x["siglaVotoParlamentar"]
            first_seen[c] = min(first_seen.get(c, v["dataSessao"]), v["dataSessao"])
            last_seen[c] = max(last_seen.get(c, v["dataSessao"]), v["dataSessao"])
            pres[c][cod] += 1
            if cod in PRESENTE or cod in JUSTIFICADA or cod in SEM_JUSTIFICATIVA:
                pres_ano[c][ano][1] += 1
                if cod in PRESENTE:
                    pres_ano[c][ano][0] += 1

    # ---------- votações abertas: votos individuais, campos ideológicos, tema ----------
    votos_sen = defaultdict(dict)       # senador -> {índice: código S/N/A/O}
    partido_voto = defaultdict(dict)    # senador -> {índice: partido à época}
    listadas = defaultdict(int)         # senador -> nº de votações abertas em que consta
    party_cnt = defaultdict(lambda: defaultdict(Counter))  # índice -> chave do partido -> Counter(S/N)
    for idx, v in enumerate(abertas):
        for x in v["votos"]:
            c = x["codigoParlamentar"]
            listadas[c] += 1
            cod = VOTO_COD.get(x["siglaVotoParlamentar"])
            if cod:
                votos_sen[c][idx] = cod
                partido_voto[c][idx] = x["siglaPartidoParlamentar"]
                party_cnt[idx][x["siglaPartidoParlamentar"]][cod] += 1

    def campo_major(idx, campo):
        cnt = Counter()
        for partido, c in party_cnt[idx].items():
            if ideologia.get(partido, {}).get("campo") == campo:
                cnt["S"] += c["S"]
                cnt["N"] += c["N"]
        tot = cnt["S"] + cnt["N"]
        if tot < 5 or cnt["S"] == cnt["N"]:
            return ""
        return "S" if cnt["S"] > cnt["N"] else "N"

    # temas: nível mais alto da classificação do processo
    tema_de = {}
    nomes_tema = set()
    for v in abertas:
        pid = v.get("idProcesso")
        if pid and pid not in tema_de:
            try:
                det = load(f"procdet/{pid}.json")
            except FileNotFoundError:
                det = {}
            temas = []
            for cl in det.get("classificacoes") or []:
                topo = (cl.get("descricaoHierarquia") or cl.get("descricao") or "").split(" / ")[0].strip()
                if topo and topo not in temas:
                    temas.append(topo)
            tema_de[pid] = temas
            nomes_tema.update(temas)
    codigo_tema = {nome: i + 1 for i, nome in enumerate(sorted(nomes_tema))}

    vot_out, props = [], {}
    for idx, v in enumerate(abertas):
        o = orient_de(v)
        contagem = Counter(x["siglaVotoParlamentar"] for x in v["votos"])
        sim, nao = contagem["Sim"], contagem["Não"]
        pid = str(v["codigoMateria"]) if v.get("codigoMateria") else None
        vot_out.append([f"{v['dataSessao']}-{v['sequencialVotacao']}", v["dataSessao"], pid,
                        (v.get("descricaoVotacao") or "").strip()[:400], sim, nao,
                        contagem["Abstenção"] + contagem["Obstrução"],
                        "1" if v.get("resultadoVotacao") == "A" else "0" if v.get("resultadoVotacao") == "R" else "",
                        o.get("GOVERNO", ""), campo_major(idx, "esquerda"), campo_major(idx, "centro"),
                        campo_major(idx, "direita")])
        if pid:
            props[pid] = {"t": v.get("identificacao") or "", "e": (v.get("ementa") or "").strip()[:500],
                          "tp": v.get("sigla") or "",
                          "tm": [codigo_tema[t] for t in tema_de.get(v.get("idProcesso"), [])]}
    with open(os.path.join(OUT, "votacoes.json"), "w", encoding="utf-8") as f:
        json.dump({"votacoes": vot_out, "proposicoes": props,
                   "temas": {str(c): n for n, c in sorted(codigo_tema.items(), key=lambda kv: kv[1])}},
                  f, ensure_ascii=False, separators=(",", ":"))

    # diagnóstico: por que não há posição ideológica pelo voto
    def contestada(idx):
        c = Counter()
        for x in abertas[idx]["votos"]:
            c[x["siglaVotoParlamentar"]] += 1
        tot = c["Sim"] + c["Não"]
        return tot >= 30 and min(c["Sim"], c["Não"]) / tot >= 0.10
    contest = [i for i in range(len(abertas)) if contestada(i)]
    sem_gov = [i for i in contest if orient_de(abertas[i]).get("GOVERNO") not in ("S", "N")]
    diag = {"votacoes": len(votacoes), "abertas": len(abertas), "contestadas": len(contest),
            "contestadas_sem_orientacao_governo": len(sem_gov)}
    # a mesma escala usada na Câmara, aplicada às votações contestadas sem orientação do Governo
    # (mínimo de 15 votos por senador): mostra que ela não reproduz a pesquisa acadêmica
    esc = bd.escalar(votos_sen, sem_gov, min_votos_dep=15)
    pares = [(x, ideologia[info[c]["partido"]]["nota"]) for c, x in esc.items() if info[c]["partido"] in ideologia]
    if len(pares) >= 10:
        diag["senadores_sem_governo"] = len(esc)
        diag["corr_pesquisa_sem_governo"] = round(abs(bd.correlacao(*zip(*pares))), 2)
        # ... e com o alinhamento à orientação do Governo (nas votações em que ele orientou Sim/Não)
        alinh_gov = []
        for c, x in esc.items():
            ok = tot = 0
            for i in contest:
                g = orient_de(abertas[i]).get("GOVERNO")
                voto = votos_sen[c].get(i)
                if g in ("S", "N") and voto in ("S", "N"):
                    tot += 1
                    ok += voto == g
            if tot >= 15:
                alinh_gov.append((x, ok / tot))
        if len(alinh_gov) >= 10:
            diag["corr_governo_sem_governo"] = round(abs(bd.correlacao(*zip(*alinh_gov))), 2)
    print("diagnóstico:", diag)

    # ---------- proposições (autorias) ----------
    status = {}
    for sigla in ("PL", "PLP", "PEC", "PDL", "PRS"):
        for y in YEARS:
            for p in load(f"proc-{sigla}-{y}.json"):
                status[p["codigoMateria"]] = p.get("situacaoAtual", "")
    autor = {}
    for c in info:
        aut = load(f"aut/{c}.json")["MateriasAutoriaParlamentar"]["Parlamentar"].get("Autorias") or {}
        lst = aut.get("Autoria", []) if isinstance(aut, dict) else []
        lst = [lst] if isinstance(lst, dict) else lst
        autor[c] = [(a["Materia"], a.get("IndicadorAutorPrincipal") == "Sim") for a in lst
                    if a["Materia"].get("Data", "") >= INICIO_LEGISLATURA]

    # ---------- cota parlamentar (CEAPS) ----------
    gasto_mes = defaultdict(lambda: defaultdict(float))
    gasto_cat = defaultdict(lambda: defaultdict(float))
    ultimo_ym = "0000-00"
    for y in YEARS:
        for r in load(f"ceaps-{y}.json"):
            c = r["codSenador"]
            if c not in info:
                continue
            ym = f"{r['ano']}-{int(r['mes']):02d}"
            gasto_mes[c][ym] += r["valorReembolsado"] or 0.0
            gasto_cat[c][categoria(r["tipoDespesa"])] += r["valorReembolsado"] or 0.0
            ultimo_ym = max(ultimo_ym, ym)

    # janela de gastos: só meses completos (mesmo critério da Câmara)
    serie_nac = {}
    for m in bd.ym_range("2023-02", ultimo_ym):
        ativos_m = [c for c in info if first_seen[c][:7] <= m <= last_seen[c][:7]]
        if ativos_m:
            serie_nac[m] = round(statistics.mean(gasto_mes[c].get(m, 0.0) for c in ativos_m), 2)
    ms = sorted(serie_nac)
    ceap_fim = ms[0]
    for i, m in enumerate(ms):
        hist = [serie_nac[x] for x in ms[max(0, i - 12):i]]
        # limiar de 75% (na Câmara, 80%): a CEAPS tem forte sazonalidade (pico em dezembro, queda em janeiro)
        if not hist or serie_nac[m] >= 0.75 * statistics.median(hist):
            ceap_fim = m
        else:
            break
    print("CEAPS considerada até", ceap_fim, "(dados brutos até", ultimo_ym + ")")

    # ---------- candidaturas 2026 ----------
    civil = {c: (bd._norm(i["nome_civil"]), i["nasc"]) for c, i in info.items()}
    cands, cand_subst, cand_gerado = bd.candidaturas(info, civil=civil, cargo_proprio="SENADOR")
    print(f"{len(cands)} senadores com candidatura em 2026 ({sum(c['reeleicao'] for c in cands.values())} à reeleição)")

    # ---------- métricas por senador ----------
    resumo = {}
    for c, i in info.items():
        ini, fim = first_seen[c], last_seen[c]
        meses = bd.ym_range(ini[:7], min(fim[:7], ceap_fim))
        n_meses = max(len(meses), 1)
        total = sum(gasto_mes[c].get(m, 0.0) for m in meses)
        cnt = pres[c]
        presentes = sum(n for k, n in cnt.items() if k in PRESENTE)
        justificadas = sum(n for k, n in cnt.items() if k in JUSTIFICADA)
        sem_just = sum(n for k, n in cnt.items() if k in SEM_JUSTIFICATIVA)
        base = presentes + justificadas + sem_just
        emitidos = len(votos_sen[c])
        ps = autor[c]
        prin = [(m, p) for m, p in ps if p and m["Sigla"] in bd.TIPOS_PRINCIPAIS]
        resumo[c] = {
            "id": c, "nome": i["nome"], "partido": i["partido"], "uf": i["uf"], "foto": i["foto"],
            "em_exercicio": i["em_exercicio"],
            "faixa": ideologia.get(i["partido"], {}).get("faixa"),
            "nota_pesquisa": ideologia.get(i["partido"], {}).get("nota"),
            "voto_nota": None, "voto_faixa": None,
            "cand": ("reeleicao" if cands[c]["reeleicao"] else "outro") if c in cands else "nao",
            "cand_numero": cands[c]["numero"] if c in cands else None,
            "cand_cargo": cands[c]["cargo"] if c in cands else None,
            "cand_obs": "substituido" if c in cand_subst else ("multiplos" if c in cands and cands[c]["outros_registros"] else None),
            "inicio": ini, "fim": fim, "meses": n_meses,
            "gasto_total": round(total, 2), "gasto_mensal": round(total / n_meses, 2),
            "sessoes": base, "presencas": presentes,
            "pct_presenca": round(100 * presentes / base, 1) if base else None,
            "votacoes_periodo": listadas[c], "votos": emitidos,
            "pct_votos": round(100 * emitidos / listadas[c], 1) if listadas[c] else None,
            "n_prop": len(prin),
            "n_leis": sum(1 for m, _ in prin if "NORMA JURÍDICA" in status.get(int(m["Codigo"]), "").upper()),
        }

    # ---------- médias de comparação ----------
    elegiveis = [c for c, r in resumo.items() if r["meses"] >= MIN_MESES_MEDIA]

    def agrega(ids, chave, fn):
        vals = [resumo[i][chave] for i in ids if resumo[i][chave] is not None]
        return round(fn(vals), 2) if vals else None
    por_uf = defaultdict(list)
    for c in elegiveis:
        por_uf[resumo[c]["uf"]].append(c)
    campos = ["gasto_mensal", "pct_presenca", "pct_votos"]
    nacional = {k: {"media": agrega(elegiveis, k, statistics.mean), "mediana": agrega(elegiveis, k, statistics.median)}
                for k in campos}
    nacional["n"] = len(elegiveis)
    ufs = {uf: {k: {"media": agrega(ids, k, statistics.mean), "mediana": agrega(ids, k, statistics.median)} for k in campos}
           | {"n": len(ids)} for uf, ids in por_uf.items()}
    cats = sorted({k for c in elegiveis for k in gasto_cat[c]})
    cat_mensal = lambda c, k: gasto_cat[c].get(k, 0.0) / resumo[c]["meses"]
    cat_nac = {k: round(statistics.mean(cat_mensal(c, k) for c in elegiveis), 2) for k in cats}
    cat_uf = {uf: {k: round(statistics.mean(cat_mensal(c, k) for c in ids), 2) for k in cats} for uf, ids in por_uf.items()}

    # ---------- arquivos por senador ----------
    for c, r in resumo.items():
        ini, fim = r["inicio"], r["fim"]
        lista, contagem = [], Counter()
        for m, principal in autor[c]:
            contagem[m["Sigla"]] += 1
            if m["Sigla"] in bd.TIPOS_PRINCIPAIS:
                sit = status.get(int(m["Codigo"]), "")
                lista.append({"id": m["Codigo"], "tp": m["Sigla"], "n": m["Numero"], "a": m["Ano"],
                              "e": (m.get("Ementa") or "").strip()[:400], "d": m["Data"][:10],
                              "s": sit.capitalize(), "autor_principal": principal})
        lista.sort(key=lambda x: x["d"], reverse=True)
        vs = []
        for idx, cod in sorted(votos_sen[c].items()):
            partido = partido_voto[c][idx]
            o = orient_de(abertas[idx]).get(chave_partido(partido), "")
            vs.append([idx, cod, "", partido, o])

        def alinh(ref):
            tot = ok = 0
            for v in vs:
                x = ref(v)
                if x in ("S", "N", "O"):
                    tot += 1
                    ok += v[1] == x
            return [ok, tot]
        alinhamento = {"orientacao": alinh(lambda v: v[4]), "governo": alinh(lambda v: vot_out[v[0]][8]),
                       "esquerda": alinh(lambda v: vot_out[v[0]][9]), "centro": alinh(lambda v: vot_out[v[0]][10]),
                       "direita": alinh(lambda v: vot_out[v[0]][11])}
        pct_al = lambda k: round(100 * alinhamento[k][0] / alinhamento[k][1], 1) if alinhamento[k][1] else None
        r["pct_orientacao"], r["pct_governo"] = pct_al("orientacao"), pct_al("governo")

        meses = bd.ym_range(ini[:7], min(fim[:7], ceap_fim))
        serie = [[m, round(gasto_mes[c].get(m, 0.0), 2)] for m in meses]
        categorias = sorted(
            ([k, round(v, 2), round(v / r["meses"], 2), cat_nac.get(k, 0.0),
              cat_uf[r["uf"]].get(k, 0.0) if r["uf"] in cat_uf else None]
             for k, v in gasto_cat[c].items() if abs(v) > 0.005), key=lambda x: -x[1])
        cnt = pres[c]
        out = {
            **{k: r[k] for k in ("id", "nome", "partido", "uf", "foto", "inicio", "fim", "meses", "em_exercicio")},
            "casa": "senado", "url_perfil": info[c]["url_perfil"],
            "ideologia": ideologia.get(r["partido"]), "ideologia_voto": None, "partido_voto": None,
            "candidatura": cands.get(c), "candidatura_substituida": cand_subst.get(c),
            "propostas": {"contagem": dict(contagem.most_common()), "lista": lista},
            "votos": {"lista": vs, "total": len(vs), "com_maioria": 0, "seguiu_partido": 0, "alinhamento": alinhamento},
            "gastos": {"total": r["gasto_total"], "mensal": r["gasto_mensal"], "serie": serie, "categorias": categorias},
            "presenca": {
                "presencas": r["presencas"], "sessoes": r["sessoes"], "pct": r["pct_presenca"],
                "por_ano": {int(a): v for a, v in sorted(pres_ano[c].items())},
                "votos": r["votos"], "votacoes": r["votacoes_periodo"], "pct_votos": r["pct_votos"],
                "detalhe": {"justificadas": {k: cnt[k] for k in ("AP", "MIS", "LS", "LP", "LAP") if cnt[k]},
                            "sem_justificativa": sum(cnt[k] for k in SEM_JUSTIFICATIVA),
                            "presente_sem_voto": cnt["P-NRV"], "voto_secreto": cnt["Votou"]}},
        }
        with open(os.path.join(OUT, "d", f"{c}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(OUT, "senadores.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(resumo.values(), key=lambda x: x["nome"]), f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dados_ate": max(last_seen.values()), "ceap_ate": ceap_fim, "ceap_bruto_ate": ultimo_ym,
            "candidaturas_tse_em": cand_gerado, "legislatura": 57, "min_meses_media": MIN_MESES_MEDIA,
            "nacional": nacional, "uf": ufs, "categorias": {"nacional": cat_nac, "uf": cat_uf},
            "serie_nacional": {m: v for m, v in serie_nac.items() if m <= ceap_fim},
            "diagnostico": diag,
        }, f, ensure_ascii=False, separators=(",", ":"))
    print("ok:", len(resumo), "senadores gerados")


if __name__ == "__main__":
    main()

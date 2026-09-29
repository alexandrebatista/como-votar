(() => {
'use strict';

const app = document.getElementById('app');
const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
const int = new Intl.NumberFormat('pt-BR');
const pct1 = v => (v == null ? '—' : v.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fdate = iso => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '');
const fmes = ym => { const [y, m] = ym.split('-'); return ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][+m - 1] + '/' + y.slice(2); };
const LABEL = { S: 'Sim', N: 'Não', A: 'Abstenção', O: 'Obstrução' };
const camaraDep = id => `https://www.camara.leg.br/deputados/${id}`;
const camaraProp = id => `https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=${id}`;

// todas as palavras da busca precisam aparecer (em qualquer ordem)
const matchAll = (nq, hay) => !nq || nq.split(/\s+/).every(w => hay.includes(w));

const cache = {};
async function load(path) {
  if (!cache[path]) {
    cache[path] = fetch(path).then(r => { if (!r.ok) throw new Error(path + ' → ' + r.status); return r.json(); });
  }
  return cache[path];
}

/* ---------- comparações ---------- */
function compare(value, ref, refLabel, { unit = 'pct' } = {}) {
  if (value == null || ref == null || !ref) return '';
  const diff = (value - ref) / ref * 100;
  if (Math.abs(diff) < 3) return `<span class="badge eq">≈ ${esc(refLabel)}</span>`;
  const cls = diff > 0 ? 'up' : 'down';
  return `<span class="badge ${cls}">${Math.abs(diff).toFixed(0)}% ${diff > 0 ? 'acima' : 'abaixo'} ${esc(refLabel)}</span>`;
}
const stat = (n, l, extra = '') => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div>${extra}</div>`;

/* ---------- lista ---------- */
async function viewList() {
  document.title = 'Como Votar — atuação de deputados federais';
  const ide = await load('data/ideologia.json');
  const faixaNome = Object.fromEntries(ide.faixas.map(f => [f.id, f.nome]));
  const deps = [...await load('data/deputados.json')].sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', { sensitivity: 'base' }));
  const ufs = [...new Set(deps.map(d => d.uf))].sort();
  const idv = await load('data/ideologia_voto.json');
  const meta = await load('data/meta.json');
  const SEM = '-'; // "sem classificação"

  // ----- visualização em tabela -----
  let visao = 'cartoes'; // 'cartoes' | 'tabela'
  try { visao = localStorage.getItem('visao') === 'tabela' ? 'tabela' : 'cartoes'; } catch { /* sem armazenamento */ }
  const ord = { k: 'nome', dir: 1 };
  const nfl = v => v.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
  const pctF = v => (v == null ? '—' : nfl(v) + '%');
  const mediaNac = meta.nacional.gasto_mensal.media;
  const CAND_TXT = d => (d.cand === 'reeleicao' ? `Reeleição · nº ${d.cand_numero}` : d.cand === 'outro' ? `Candidato a ${d.cand_cargo}` : 'Sem candidatura');
  const CAND_ORD = { reeleicao: 0, outro: 1, nao: 2 };
  // v = valor para ordenar; h = HTML da célula; c = texto para o CSV; num = alinhar à direita
  const COLS = [
    { k: 'nome', t: 'Deputado', v: d => d.nome, h: d => `<a href="#/d/${d.id}">${esc(d.nome)}</a>${d.em_exercicio ? '' : ' <span class="muted small">(fora de exercício)</span>'}`, c: d => d.nome },
    { k: 'partido', t: 'Partido', v: d => d.partido, h: d => esc(d.partido), c: d => d.partido },
    { k: 'uf', t: 'UF', v: d => d.uf, h: d => esc(d.uf), c: d => d.uf },
    { k: 'cand', t: 'Candidatura em 2026', v: d => CAND_ORD[d.cand], h: d => esc(CAND_TXT(d)), c: d => CAND_TXT(d) },
    { k: 'pesq', t: 'Ideologia (pesquisa)', num: 1, v: d => d.nota_pesquisa, h: d => (d.nota_pesquisa == null ? '—' : `${esc(faixaNome[d.faixa])} · ${nfl(d.nota_pesquisa)}`), c: d => (d.nota_pesquisa == null ? '' : `${faixaNome[d.faixa]} (${nfl(d.nota_pesquisa)})`) },
    { k: 'voto', t: 'Ideologia (pelo voto)', num: 1, v: d => d.voto_nota, h: d => (d.voto_nota == null ? '—' : `${esc(faixaNome[d.voto_faixa])} · ${nfl(d.voto_nota)}`), c: d => (d.voto_nota == null ? '' : `${faixaNome[d.voto_faixa]} (${nfl(d.voto_nota)})`) },
    { k: 'pres', t: 'Presença em sessões', num: 1, v: d => d.pct_presenca, h: d => pctF(d.pct_presenca), c: d => d.pct_presenca ?? '' },
    { k: 'pvot', t: 'Participação em votações', num: 1, v: d => d.pct_votos, h: d => pctF(d.pct_votos), c: d => d.pct_votos ?? '' },
    { k: 'ori', t: 'Voto igual à orientação do partido', num: 1, v: d => d.pct_orientacao, h: d => pctF(d.pct_orientacao), c: d => d.pct_orientacao ?? '' },
    { k: 'gov', t: 'Voto igual à orientação do Governo', num: 1, v: d => d.pct_governo, h: d => pctF(d.pct_governo), c: d => d.pct_governo ?? '' },
    { k: 'gasto', t: 'Gasto médio por mês (CEAP)', num: 1, v: d => d.gasto_mensal, h: d => brl.format(d.gasto_mensal), c: d => d.gasto_mensal },
    // só compara com a média quem exerceu pelo menos min_meses_media meses (mesmo critério das médias)
    { k: 'gvs', t: 'Gasto vs. média nacional', num: 1, v: d => (d.meses >= meta.min_meses_media ? (d.gasto_mensal / mediaNac - 1) * 100 : null),
      h: d => { if (d.meses < meta.min_meses_media) return `<span class="muted" title="Menos de ${meta.min_meses_media} meses de mandato: sem comparação">—</span>`;
        const x = (d.gasto_mensal / mediaNac - 1) * 100; return `<span class="${x > 3 ? 'up' : x < -3 ? 'down' : ''}">${x > 0 ? '+' : ''}${nfl(x)}%</span>`; },
      c: d => (d.meses >= meta.min_meses_media ? Math.round((d.gasto_mensal / mediaNac - 1) * 1000) / 10 : '') },
    { k: 'prop', t: 'Propostas (autor principal)', num: 1, v: d => d.n_prop, h: d => int.format(d.n_prop), c: d => d.n_prop },
    { k: 'leis', t: 'Viraram lei', num: 1, v: d => d.n_leis, h: d => int.format(d.n_leis), c: d => d.n_leis },
  ];
  const ordenar = list => {
    const col = COLS.find(c => c.k === ord.k);
    return [...list].sort((a, b) => {
      const x = col.v(a), y = col.v(b);
      if (x == null || Number.isNaN(x)) return y == null || Number.isNaN(y) ? 0 : 1; // vazios sempre no fim
      if (y == null || Number.isNaN(y)) return -1;
      const r = typeof x === 'string' ? x.localeCompare(y, 'pt-BR', { sensitivity: 'base' }) : x - y;
      return r * ord.dir || a.nome.localeCompare(b.nome, 'pt-BR', { sensitivity: 'base' });
    });
  };
  const tabelaHtml = list => `<div class="tablewrap"><table class="tbl"><thead><tr>${COLS.map(c =>
    `<th class="${c.num ? 'r' : ''}" aria-sort="${ord.k === c.k ? (ord.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button type="button" class="sortb" data-sort="${c.k}">${c.t}<span class="arr">${ord.k === c.k ? (ord.dir > 0 ? ' ▲' : ' ▼') : ''}</span></button></th>`).join('')}</tr></thead><tbody>${
    ordenar(list).map(d => `<tr>${COLS.map(c => `<td class="${c.num ? 'r' : ''}">${c.h(d)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const baixarCsv = list => {
    const cel = v => { const s = String(v ?? '').replace('.', ','); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const nomeCel = v => { const s = String(v ?? ''); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const linhas = [COLS.map(c => nomeCel(c.t)).join(';'), ...ordenar(list).map(d => COLS.map(c => (typeof c.c(d) === 'number' ? cel(c.c(d)) : nomeCel(c.c(d)))).join(';'))];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + linhas.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    a.download = 'deputados.csv'; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  let listaAtual = [];

  let fonte = 'pesquisa'; // 'pesquisa' (nota do partido) | 'voto' (como o deputado vota)
  const faixaOf = d => (fonte === 'voto' ? d.voto_faixa : d.faixa) || SEM;
  const notaPartido = p => (fonte === 'voto' ? idv.partidos[p]?.nota : ide.partidos[p]?.nota) ?? 99;
  let partyCount = {}, faixaCount = {}, partyFaixas = {};
  const recount = base => {
    partyCount = {}; faixaCount = {}; partyFaixas = {};
    base.forEach(d => {
      partyCount[d.partido] = (partyCount[d.partido] || 0) + 1;
      faixaCount[faixaOf(d)] = (faixaCount[faixaOf(d)] || 0) + 1;
      (partyFaixas[d.partido] ||= new Set()).add(faixaOf(d));
    });
  };
  const allParties = [...new Set(deps.map(d => d.partido))];
  // partidos do mais à esquerda ao mais à direita; sem classificação por último
  const sortedParties = () => [...allParties].sort((x, y) => notaPartido(x) - notaPartido(y) || x.localeCompare(y, 'pt-BR'));
  const faixas = [...ide.faixas.map(f => ({ id: f.id, nome: f.nome })), { id: SEM, nome: 'Sem classificação' }];
  const CAND_PADRAO = ['reeleicao']; // a lista abre só com candidatos à reeleição
  const selIde = new Set(), selPt = new Set(), selCand = new Set(CAND_PADRAO);
  const candPadrao = () => selCand.size === CAND_PADRAO.length && CAND_PADRAO.every(c => selCand.has(c));
  const CAND = [
    ['reeleicao', 'Candidato a deputado federal (reeleição)'],
    ['outro', 'Candidato a outro cargo'],
    ['nao', 'Sem candidatura em 2026'],
  ];
  let candCount = {};

  app.innerHTML = `
    <h1>Como o seu deputado atuou?</h1>
    <p class="muted">Escolha um deputado federal para ver propostas, votos, gastos e presença na legislatura 2023–2026.</p>
    <div class="filters">
      <input type="search" id="q" placeholder="Buscar por nome…" aria-label="Buscar por nome" autofocus>
      <select id="uf" aria-label="Estado"><option value="">Todos os estados</option>${ufs.map(u => `<option>${u}</option>`).join('')}</select>
      <label class="check"><input type="checkbox" id="ativos" checked> só deputados em exercício</label>
      <button type="button" id="clear" hidden>Restaurar filtros padrão</button>
    </div>
    <div class="chipgroup" role="group" aria-labelledby="lbl-cand">
      <div class="glabel" id="lbl-cand">Candidatura em 2026 <span class="muted small">(registro do TSE; escolha uma ou mais)</span></div>
      <div class="chipbar" id="cand-chips"></div>
    </div>
    <div class="chipgroup" role="radiogroup" aria-labelledby="lbl-fonte">
      <div class="glabel" id="lbl-fonte">Como classificar a orientação ideológica</div>
      <div class="seg">
        <button type="button" class="segb on" data-fonte="pesquisa" role="radio" aria-checked="true">Pelo partido <span class="muted small">(pesquisa acadêmica)</span></button>
        <button type="button" class="segb" data-fonte="voto" role="radio" aria-checked="false">Pelo voto <span class="muted small">(como o deputado vota)</span></button>
      </div>
      <p class="muted small" id="fonte-nota"></p>
    </div>
    <div class="chipgroup" role="group" aria-labelledby="lbl-ide">
      <div class="glabel" id="lbl-ide">Orientação ideológica <span class="muted small">(escolha uma ou mais)</span></div>
      <div class="chipbar" id="ide-chips"></div>
    </div>
    <div class="chipgroup" role="group" aria-labelledby="lbl-pt">
      <div class="glabel" id="lbl-pt">Partido <span class="muted small">(escolha um ou mais)</span></div>
      <div class="chipbar" id="pt-chips"></div>
      <p class="muted small" id="pt-note" hidden>Partidos fora das orientações escolhidas ficam indisponíveis.</p>
    </div>
    <div class="listbar">
      <p class="muted small" id="count"></p>
      <div class="listtools">
        <button type="button" id="csv" class="tool" title="Baixa os deputados que estão na lista, com as colunas da tabela">Baixar CSV</button>
        <div class="seg" role="radiogroup" aria-label="Forma de exibição">
          <button type="button" class="segb viewb" data-visao="cartoes" role="radio">Cartões</button>
          <button type="button" class="segb viewb" data-visao="tabela" role="radio">Tabela</button>
        </div>
      </div>
    </div>
    <div class="grid" id="grid"></div>`;
  const norm = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const q = document.getElementById('q'), uf = document.getElementById('uf'), clear = document.getElementById('clear'), ativos = document.getElementById('ativos');

  // um partido está disponível se nenhuma orientação foi escolhida ou se algum deputado dele está em uma das escolhidas
  // (pela pesquisa todo o partido tem uma só faixa; pelo voto um partido pode ter deputados em várias)
  const disponivel = p => !selIde.size || [...(partyFaixas[p] || [])].some(f => selIde.has(f));
  const NOTA_FONTE = {
    pesquisa: 'Faixa do partido segundo a pesquisa com cientistas políticos (ABCP). É a mesma para todos os deputados do partido.',
    voto: 'Faixa do próprio deputado, estimada pelos votos em votações nominais em que o Governo não orientou Sim/Não. É uma escala relativa a esta Câmara, e deputados do mesmo partido podem cair em faixas diferentes.',
  };
  const chip = (kind, id, label, count, { on, off }) => !count && !on ? '' :
    `<button type="button" class="fchip${on ? ' on' : ''}" data-kind="${kind}" data-id="${esc(id)}" aria-pressed="${on}"${off ? ' disabled title="Fora das orientações ideológicas escolhidas"' : ''}>${esc(label)} <span class="n">${count}</span></button>`;
  const drawChips = () => {
    // escolher orientação invalida partidos que não pertencem a ela
    [...selPt].forEach(p => { if (!disponivel(p)) selPt.delete(p); });
    document.getElementById('ide-chips').innerHTML = faixas.map(f => chip('ide', f.id, f.nome, faixaCount[f.id], { on: selIde.has(f.id) })).join('');
    document.getElementById('cand-chips').innerHTML = CAND.map(([id, nome]) => chip('cand', id, nome, candCount[id] || 0, { on: selCand.has(id) })).join('');
    document.getElementById('fonte-nota').textContent = NOTA_FONTE[fonte];
    document.querySelectorAll('.segb').forEach(b => { const on = b.dataset.fonte === fonte; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    document.getElementById('pt-chips').innerHTML = sortedParties().map(p => chip('pt', p, p, partyCount[p], { on: selPt.has(p), off: !disponivel(p) })).join('');
    document.getElementById('pt-note').hidden = !selIde.size;
    clear.hidden = !(selIde.size || selPt.size || !candPadrao() || q.value || uf.value || !ativos.checked);
  };
  const render = () => {
    // contagens e partidos disponíveis refletem também o filtro de candidatura
    const base = deps.filter(d => !ativos.checked || d.em_exercicio);
    candCount = {}; base.forEach(d => { candCount[d.cand] = (candCount[d.cand] || 0) + 1; });
    recount(selCand.size ? base.filter(d => selCand.has(d.cand)) : base);
    drawChips();
    const nq = norm(q.value.trim());
    // buscar por nome ignora todos os filtros (inclusive "em exercício" e candidatura): quem digita um nome quer aquela pessoa
    const buscando = nq.length > 0;
    app.classList.toggle('buscando', buscando);
    const list = buscando
      ? deps.filter(d => norm(d.nome).includes(nq))
      : deps.filter(d => (!ativos.checked || d.em_exercicio) && (!selCand.size || selCand.has(d.cand)) && (!uf.value || d.uf === uf.value)
        && (!selPt.size || selPt.has(d.partido)) && (!selIde.size || selIde.has(faixaOf(d))));
    listaAtual = list;
    const tabela = visao === 'tabela';
    app.classList.toggle('wide', tabela);
    document.querySelectorAll('.viewb').forEach(b => { const on = b.dataset.visao === visao; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    document.getElementById('count').textContent = `${list.length} deputado(s)`
      + (buscando ? ' encontrado(s) pelo nome — os filtros abaixo ficam ignorados enquanto houver busca (inclui deputados fora de exercício).' : '')
      + (!tabela && list.length > 120 ? ' Mostrando os 120 primeiros; refine a busca.' : '');
    const grid = document.getElementById('grid');
    grid.classList.toggle('grid', !tabela);
    if (tabela) { grid.innerHTML = tabelaHtml(list); return; }
    grid.innerHTML = list.slice(0, 120).map(d => `
      <a class="dep" href="#/d/${d.id}"><img loading="lazy" src="${esc(d.foto)}" alt=""><div><b>${esc(d.nome)}</b><span>${esc(d.partido)} · ${esc(d.uf)}${faixaOf(d) !== SEM ? ' · ' + esc(faixaNome[faixaOf(d)]) : ''}${d.em_exercicio ? '' : ' · fora de exercício'}</span>${
        d.cand === 'reeleicao' ? `<span class="candtag">Candidato · nº ${esc(d.cand_numero)}</span>`
        : d.cand === 'outro' ? `<span class="candtag other">Candidato a ${esc(d.cand_cargo)}</span>` : ''}</div></a>`).join('');
  };
  app.querySelector('.filters').parentElement.addEventListener('click', e => {
    const vb = e.target.closest('.viewb');
    if (vb) { visao = vb.dataset.visao; try { localStorage.setItem('visao', visao); } catch { /* ok */ } render(); return; }
    const so = e.target.closest('.sortb');
    if (so) { const k = so.dataset.sort; ord.dir = ord.k === k ? -ord.dir : (COLS.find(c => c.k === k).num ? -1 : 1); ord.k = k; render(); document.querySelector(`.sortb[data-sort="${k}"]`)?.focus(); return; }
    if (e.target.closest('#csv')) { baixarCsv(listaAtual); return; }
    const sb = e.target.closest('.segb');
    if (sb) { fonte = sb.dataset.fonte; render(); return; }
    const b = e.target.closest('.fchip'); if (!b || b.disabled) return;
    const set = b.dataset.kind === 'ide' ? selIde : b.dataset.kind === 'cand' ? selCand : selPt;
    set.has(b.dataset.id) ? set.delete(b.dataset.id) : set.add(b.dataset.id);
    render();
    document.querySelector(`.fchip[data-kind="${b.dataset.kind}"][data-id="${CSS.escape(b.dataset.id)}"]`)?.focus();
  });
  clear.addEventListener('click', () => { selIde.clear(); selPt.clear(); selCand.clear(); CAND_PADRAO.forEach(c => selCand.add(c)); q.value = ''; uf.value = ''; ativos.checked = true; render(); });
  [q, uf, ativos].forEach(el => el.addEventListener('input', render));
  render();
}

/* ---------- perfil ---------- */
async function viewDep(id) {
  app.classList.remove('wide', 'buscando'); // estados da lista não valem no perfil
  app.innerHTML = '<p class="muted">Carregando…</p>';
  const [meta, dep, vdata] = await Promise.all([load('data/meta.json'), load(`data/d/${id}.json`), load('data/votacoes.json')]);
  const summary = (await load('data/deputados.json')).find(d => d.id === +id);
  document.title = `${dep.nome} — Como Votar`;
  const nac = meta.nacional, ufm = meta.uf[dep.uf];
  const short = dep.meses < meta.min_meses_media;
  const [ide, idv] = await Promise.all([load('data/ideologia.json'), load('data/ideologia_voto.json')]);
  const faixaNome = Object.fromEntries(ide.faixas.map(f => [f.id, f.nome]));
  const nf = v => v.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
  const ideo = (dep.ideologia
    ? `<span class="pill ideo" title="${esc(`Partido, pela pesquisa acadêmica: nota ${dep.ideologia.nota.toLocaleString('pt-BR')} de 10 (0 = esquerda, 10 = direita)${dep.ideologia.estimado ? ' — estimada: ' + dep.ideologia.obs : dep.ideologia.obs ? ' — ' + dep.ideologia.obs : ''}`)}">Partido (pesquisa): ${esc(faixaNome[dep.ideologia.faixa])}</span>`
    : `<span class="pill ideo">partido sem classificação na pesquisa</span>`)
    + (dep.ideologia_voto
      ? ` <span class="pill ideo" title="Posição do deputado estimada pelos votos, escala relativa de 0 a 10">Pelo voto: ${esc(faixaNome[dep.ideologia_voto.faixa])}</span>`
      : ` <span class="pill ideo" title="Menos de ${idv.min_votos} votos nas votações usadas">Pelo voto: sem dados suficientes</span>`);

  const cd = dep.candidatura;
  const candPill = cd
    ? (cd.reeleicao
      ? `<span class="pill cand" title="Registro de candidaturas do TSE, 2026">Candidato a deputado federal · nº ${esc(cd.numero)} (${esc(cd.partido)}-${esc(cd.uf)}) · urna: ${esc(cd.nome_urna)}</span>`
      : `<span class="pill cand other" title="Registro de candidaturas do TSE, 2026">Candidato a ${esc(cd.cargo)} (${esc(cd.partido)}-${esc(cd.uf)}) · nº ${esc(cd.numero)}</span>`)
    : `<span class="pill" title="Não encontramos este deputado entre as candidaturas registradas no TSE em 2026">sem candidatura registrada em 2026</span>`;

  app.innerHTML = `
    <a class="back" href="#/">← Todos os deputados</a>
    <div class="hero">
      <img src="${esc(dep.foto)}" alt="Foto de ${esc(dep.nome)}">
      <div>
        <h1>${esc(dep.nome)}</h1>
        <div style="margin:4px 0">${candPill}</div>
        <div class="muted">${esc(dep.partido)} · ${esc(dep.uf)} ${ideo} ${dep.em_exercicio ? '' : '<span class="pill">fora de exercício hoje</span>'} · dados de ${fdate(dep.inicio)} a ${fdate(dep.fim)} · <a href="${camaraDep(dep.id)}" target="_blank" rel="noopener">perfil na Câmara ↗</a></div>
      </div>
    </div>
    ${short ? `<div class="notice">Este deputado exerceu o mandato por poucos meses (${dep.meses}). As comparações com a média podem não ser representativas.</div>` : ''}
    <nav class="tabs" aria-label="Seções">
      <a href="#s-prop" data-s="prop">Propostas</a><a href="#s-votos" data-s="votos">Votos</a>
      <a href="#s-gastos" data-s="gastos">Gastos</a><a href="#s-pres" data-s="pres">Presença</a>
    </nav>
    <div id="sec"></div>`;

  // âncoras internas sem quebrar o roteador por hash
  app.querySelectorAll('.tabs a').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    document.getElementById(a.getAttribute('href').slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));

  const sec = document.getElementById('sec');
  sec.append(...[sectionProp(dep), sectionIde(dep, ide, idv, faixaNome), sectionVotos(dep, vdata), sectionGastos(dep, meta, ufm), sectionPres(dep, nac, ufm)].map(html => {
    const t = document.createElement('div'); t.innerHTML = html.html; if (html.after) html.after(t.firstElementChild); return t.firstElementChild;
  }));
}

/* ---------- propostas ---------- */
function sectionProp(dep) {
  const p = dep.propostas;
  const principais = p.lista.filter(x => x.autor_principal);
  const co = p.lista.length - principais.length;
  const leis = principais.filter(x => x.s === 'Transformado em Norma Jurídica').length;
  const outros = Object.entries(p.contagem).filter(([t]) => !['PL','PLP','PEC','PDL','PRC','PLV','PFC','PLN','PLC','PLS'].includes(t));
  const req = (p.contagem.REQ || 0) + (p.contagem.RIC || 0) + (p.contagem.INC || 0);
  const tipos = {};
  principais.forEach(x => { tipos[x.tp] = (tipos[x.tp] || 0) + 1; });
  const html = `
  <section class="card" id="s-prop">
    <h2>Propostas apresentadas</h2>
    <p class="lead">Projetos e propostas de emenda à Constituição nesta legislatura. Requerimentos e indicações ficam de fora da lista.</p>
    <div class="stats">
      ${stat(int.format(principais.length), 'propostas como autor principal', Object.keys(tipos).length ? `<div class="l">${Object.entries(tipos).map(([t, n]) => `${n} ${t}`).join(' · ')}</div>` : '')}
      ${stat(int.format(co), 'em coautoria (não é o primeiro signatário)')}
      ${stat(int.format(leis), 'viraram lei', '<div class="l">"Transformado em Norma Jurídica"</div>')}
      ${stat(int.format(req), 'requerimentos, pedidos de informação e indicações')}
    </div>
    <div class="controls">
      <input type="search" id="pq" placeholder="Filtrar propostas por palavra…" aria-label="Filtrar propostas">
      <label><input type="checkbox" id="pmain" checked> só como autor principal</label>
    </div>
    <div id="plist"></div>
    <button class="more" id="pmore" hidden>Mostrar mais</button>
  </section>`;
  return { html, after: root => wireProp(root, dep) };
}
function wireProp(root, dep) {
  const q = root.querySelector('#pq'), main = root.querySelector('#pmain'), list = root.querySelector('#plist'), more = root.querySelector('#pmore');
  let shown = 20, cur = [];
  const norm = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const draw = () => {
    list.innerHTML = cur.slice(0, shown).map(x => `
      <div class="prop"><div class="t"><a href="${camaraProp(x.id)}" target="_blank" rel="noopener">${esc(x.tp)} ${esc(x.n)}/${esc(x.a)}</a>
        ${x.s === 'Transformado em Norma Jurídica' ? '<span class="pill lei">virou lei</span>' : ''}${x.autor_principal ? '' : '<span class="pill">coautor</span>'}</div>
        <div>${esc(x.e)}</div><div class="muted small">Apresentada em ${fdate(x.d)}${x.s ? ' · ' + esc(x.s) : ''}</div></div>`).join('') || '<p class="muted">Nenhuma proposta encontrada.</p>';
    more.hidden = cur.length <= shown;
    more.textContent = `Mostrar mais (${cur.length - shown} restantes)`;
  };
  const filter = () => {
    const nq = norm(q.value.trim());
    cur = dep.propostas.lista.filter(x => (!main.checked || x.autor_principal) && matchAll(nq, norm(x.e + ' ' + x.tp + ' ' + x.n)));
    shown = 20; draw();
  };
  q.addEventListener('input', filter); main.addEventListener('change', filter);
  more.addEventListener('click', () => { shown += 40; draw(); });
  filter();
}

/* ---------- posição ideológica ---------- */
function sectionIde(dep, ide, idv, faixaNome) {
  const nf = v => v.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
  const pesq = dep.ideologia, pv = dep.partido_voto, dv = dep.ideologia_voto, diag = idv.diagnostico;
  // larguras (em décimos da escala) entre os cortes 0 | 1,5 | 3 | 4,5 | 5,5 | 7 | 8,5 | 10
  const cortes = [0, 1.5, 3, 4.5, 5.5, 7, 8.5, 10];
  const bands = ide.faixas.map((f, i) =>
    `<i class="band b-${f.id}" style="flex:${(cortes[i + 1] - cortes[i]).toFixed(1)}" title="${esc(f.nome)}"></i>`).join('');
  const mark = (nota, cls, label) => nota == null ? '' : `<b class="mk ${cls}" style="left:${(Math.min(Math.max(nota, 0), 10) * 10).toFixed(1)}%" title="${esc(label)}"></b>`;
  const range = pv && pv.n >= 3 ? `<span class="rng" style="left:${(pv.q1 * 10).toFixed(1)}%;width:${Math.max((pv.q3 - pv.q1) * 10, 0.6).toFixed(1)}%" title="Metade central dos deputados do partido (pelo voto)"></span>` : '';
  const linha = (cls, titulo, texto) => `<li><i class="dot ${cls}"></i><span><b>${titulo}</b> — ${texto}</span></li>`;
  const html = `
  <section class="card" id="s-ide">
    <h2>Posição ideológica</h2>
    <p class="lead">Duas formas de medir: o que <b>especialistas</b> dizem sobre o partido, e como o deputado <b>vota</b>. Em ambas, 0 é esquerda e 10 é direita.</p>
    <div class="axis"><div class="bands">${bands}</div>${range}${mark(pesq?.nota, 'pesq', 'Partido (pesquisa)')}${mark(pv?.nota, 'party', 'Partido (mediana pelo voto)')}${mark(dv?.nota, 'me', 'Deputado (pelo voto)')}</div>
    <div class="axis-scale"><span>esquerda</span><span>centro</span><span>direita</span></div>
    <ul class="ax-legend">
      ${linha('pesq', 'Partido, pela pesquisa', pesq ? `${esc(faixaNome[pesq.faixa])}, nota ${nf(pesq.nota)}${pesq.estimado ? ' (estimada)' : ''}` : 'sem classificação')}
      ${linha('party', `Partido, pelo voto`, pv ? `${esc(faixaNome[pv.faixa])}, mediana ${nf(pv.nota)} (metade dos ${pv.n} deputados entre ${nf(pv.q1)} e ${nf(pv.q3)})` : 'sem dados')}
      ${linha('me', 'Deputado, pelo voto', dv ? `${esc(faixaNome[dv.faixa])}, ${nf(dv.nota)} (${int.format(dv.n)} votações usadas)` : `menos de ${idv.min_votos} votos nas votações usadas`)}
    </ul>
    <p class="muted small">"Pelo voto" usa só votações nominais em que o Governo <b>não</b> orientou Sim/Não (${int.format(diag.votacoes_B)} votações) — se incluísse todas (${int.format(diag.votacoes_A)}), o eixo passaria a medir governo × oposição (correlação de ${diag.A.corr_governo.toLocaleString('pt-BR')} com o alinhamento ao Governo, contra ${diag.A.corr_pesquisa.toLocaleString('pt-BR')} com a pesquisa). A escala é <b>relativa a esta Câmara</b>, não absoluta: <a href="#" data-metodo>como é calculada</a>.</p>
  </section>`;
  return { html, after: root => root.querySelector('[data-metodo]')?.addEventListener('click', e => { e.preventDefault(); const d = document.getElementById('metodo'); d.open = true; d.scrollIntoView({ behavior: 'smooth' }); }) };
}

/* ---------- votos ---------- */
const CAMPOS = [['esquerda', 'Esquerda'], ['centro', 'Centro'], ['direita', 'Direita']];
const ORI_TXT = { S: 'Sim', N: 'Não', O: 'Obstrução', L: 'Liberou', A: 'Abstenção', '': 'sem orientação' };
const pctOf = ([ok, tot]) => (tot ? Math.round(100 * ok / tot) + '%' : '—');
const nOf = ([ok, tot]) => `${int.format(ok)} de ${int.format(tot)}`;

function sectionVotos(dep, vdata) {
  const v = dep.votos, al = v.alinhamento;
  const html = `
  <section class="card" id="s-votos">
    <h2>Como votou</h2>
    <p class="lead">Só entram votações <b>nominais</b> do Plenário — nas votações simbólicas não há registro de voto individual. A <b>orientação da liderança</b> é a que o líder do partido (ou do bloco/federação) anuncia ao plenário; pode ser "liberado". Governo e campos ideológicos servem de referência.</p>
    <div class="stats">
      ${stat(int.format(v.total), 'votos registrados', `<div class="l">de ${int.format(dep.presenca.votacoes)} votações nominais no período</div>`)}
      ${stat(pctOf(al.orientacao), 'votos iguais à orientação do partido', `<div class="l">${nOf(al.orientacao)} votações com orientação Sim/Não</div>`)}
      ${stat(pctOf(al.governo), 'votos iguais à orientação do Governo', `<div class="l">${nOf(al.governo)}</div>`)}
    </div>
    <h3>Com quem votou junto</h3>
    <p class="muted small" style="margin-top:-4px">Em quantas votações o deputado votou como a <b>maioria</b> de cada campo (partidos agrupados pela <a href="#" data-metodo>classificação ideológica</a>).</p>
    <div class="stats camp">
      ${CAMPOS.map(([k, nome]) => stat(pctOf(al[k]), `como a maioria ${nome === 'Centro' ? 'do centro' : 'da ' + nome.toLowerCase()}`, `<div class="l">${nOf(al[k])}</div>`)).join('')}
    </div>
    <h3>Filtros</h3>
    <div class="controls">
      <input type="search" id="vq" placeholder="Tema, número ou assunto (ex.: PEC 45, tributário, armas, saúde)…" aria-label="Filtrar votos">
      <select id="vv" aria-label="Tipo de voto"><option value="">Todos os votos</option><option value="S">Votou Sim</option><option value="N">Votou Não</option><option value="A">Abstenção</option><option value="O">Obstrução</option></select>
      <select id="vt" aria-label="Tipo de proposição"><option value="leg">Projetos e PECs</option><option value="">Tudo (inclui requerimentos)</option></select>
      <select id="vth" aria-label="Tema"><option value="">Todos os temas</option></select>
    </div>
    <div class="controls">
      <select id="vor" aria-label="Orientação do partido"><option value="">Orientação do partido: qualquer</option><option value="seguiu">Seguiu a orientação</option><option value="divergiu">Divergiu da orientação</option><option value="livre">Partido liberou</option><option value="sem">Sem orientação registrada</option></select>
      <select id="vgov" aria-label="Governo"><option value="">Governo: qualquer</option><option value="com">Votou com o Governo</option><option value="contra">Votou contra o Governo</option></select>
      <select id="vcamp" aria-label="Campo ideológico"><option value="">Campo ideológico: qualquer</option><option value="com-esquerda">Votou com a maioria da esquerda</option><option value="com-direita">Votou com a maioria da direita</option><option value="contra-esquerda">Votou contra a maioria da esquerda</option><option value="contra-direita">Votou contra a maioria da direita</option></select>
      <label><input type="checkbox" id="vpol"> só votações polarizadas (esquerda × direita em lados opostos)</label>
    </div>
    <h3>Votos por tema <span class="muted small">(clique em um tema para filtrar a lista)</span></h3>
    <div id="vtemas"></div>
    <h3>Votações</h3>
    <p class="muted small" id="vcount"></p>
    <div id="vlist"></div>
    <button class="more" id="vmore" hidden>Mostrar mais</button>
  </section>`;
  return { html, after: root => wireVotos(root, dep, vdata) };
}

function wireVotos(root, dep, vdata) {
  const LEG = new Set(['PL','PLP','PEC','PDL','PRC','PLV','PFC','PLN','PLC','PLS','MPV']);
  const $ = s => root.querySelector(s);
  const norm = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const rows = dep.votos.lista.map(([idx, voto, , partido, ori]) => {
    const [vid, data, pid, desc, sim, nao, outros, aprov, gov, esq, cen, dir] = vdata.votacoes[idx];
    const pr = pid ? vdata.proposicoes[pid] : null;
    return { vid, data, pid, desc, sim, nao, outros, aprov, voto, partido, ori, gov, camp: { esquerda: esq, centro: cen, direita: dir },
             t: pr ? pr.t : '', e: pr ? pr.e : '', tp: pr ? pr.tp : '', tm: pr ? pr.tm : [],
             hay: norm([pr ? pr.t + ' ' + pr.e + ' ' + pr.tm.map(c => vdata.temas[c]).join(' ') : '', desc].join(' ')) };
  }).sort((a, b) => (b.data + b.vid).localeCompare(a.data + a.vid));
  const isRef = c => c === 'S' || c === 'N' || c === 'O';
  const chip = (label, code, mine) => {
    if (!code) return `<span class="chip none">${label}: —</span>`;
    const cls = isRef(code) ? (code === mine ? 'ok' : 'no') : 'none';
    return `<span class="chip ${cls}" title="${isRef(code) ? (code === mine ? 'igual ao voto do deputado' : 'diferente do voto do deputado') : ''}">${label}: ${ORI_TXT[code] || code}</span>`;
  };

  let shown = 30, cur = [];
  const draw = () => {
    $('#vcount').textContent = `${int.format(cur.length)} votação(ões)`;
    $('#vlist').innerHTML = cur.slice(0, shown).map(r => {
      const res = r.aprov === '1' ? 'Aprovada' : r.aprov === '0' ? 'Rejeitada' : '';
      return `<div class="vote-row">
        <div><span class="v ${r.voto}">${LABEL[r.voto]}</span></div>
        <div><div class="t">${r.t ? `<a href="${camaraProp(r.pid)}" target="_blank" rel="noopener">${esc(r.t)}</a>` : 'Votação sem proposição vinculada'}</div>
          ${r.e ? `<div class="e">${esc(r.e)}</div>` : ''}
          ${r.tm.length ? `<div>${r.tm.map(c => `<span class="pill" data-tema="${c}">${esc(vdata.temas[c])}</span>`).join('')}</div>` : ''}
          <div class="m">${fdate(r.data)} · ${esc(r.desc)}</div>
          <div class="m">Resultado: ${res ? res + ' — ' : ''}${int.format(r.sim)} sim · ${int.format(r.nao)} não${r.outros ? ' · ' + int.format(r.outros) + ' outros' : ''}</div>
          <div class="chips">${CAMPOS.map(([k, n]) => chip('Maioria ' + n.toLowerCase(), r.camp[k], r.voto)).join('')}</div></div>
        <div class="party">${chip('Liderança ' + esc(r.partido), r.ori, r.voto)}<br>${chip('Governo', r.gov, r.voto)}</div>
      </div>`;
    }).join('') || '<p class="muted">Nenhuma votação encontrada com esses filtros.</p>';
    $('#vmore').hidden = cur.length <= shown;
    $('#vmore').textContent = `Mostrar mais (${cur.length - shown} restantes)`;
  };

  const contaTema = {};
  rows.forEach(r => r.tm.forEach(c => { contaTema[c] = (contaTema[c] || 0) + 1; }));
  const sel = $('#vth');
  Object.keys(contaTema).sort((a, b) => vdata.temas[a].localeCompare(vdata.temas[b], 'pt-BR')).forEach(c => {
    sel.insertAdjacentHTML('beforeend', `<option value="${c}">${esc(vdata.temas[c])} (${contaTema[c]})</option>`);
  });
  const drawTemas = base => {
    const agg = {};
    base.forEach(r => (r.tm.length ? r.tm : ['0']).forEach(c => {
      const a = agg[c] || (agg[c] = { n: 0, S: 0, N: 0, A: 0, O: 0, seg: 0, ref: 0 });
      a.n++; a[r.voto]++;
      if (isRef(r.ori)) { a.ref++; if (r.voto === r.ori) a.seg++; }
    }));
    const linhas = Object.entries(agg).sort((x, y) => y[1].n - x[1].n);
    $('#vtemas').innerHTML = linhas.length ? `<table><thead><tr><th>Tema</th><th class="r">Votos</th><th class="r">Sim</th><th class="r">Não</th><th class="r">Abst./Obstr.</th><th class="r" title="Votos iguais à orientação da liderança do partido, entre as votações com orientação">Com a lideran&ccedil;a</th></tr></thead><tbody>${
      linhas.map(([c, a]) => `<tr class="tema-row${sel.value === c ? ' on' : ''}" data-tema="${c}" tabindex="0" role="button"><td>${esc(c === '0' ? 'Sem tema classificado' : vdata.temas[c])}</td><td class="r">${a.n}</td><td class="r">${a.S}</td><td class="r">${a.N}</td><td class="r">${a.A + a.O}</td><td class="r">${a.ref ? Math.round(100 * a.seg / a.ref) + '%' : '—'}</td></tr>`).join('')
    }</tbody></table>` : '<p class="muted">Sem votos com esses filtros.</p>';
  };

  const filter = () => {
    const nq = norm($('#vq').value.trim()), tv = $('#vv').value, leg = $('#vt').value === 'leg', th = sel.value;
    const or = $('#vor').value, gv = $('#vgov').value, cp = $('#vcamp').value, pol = $('#vpol').checked;
    const base = rows.filter(r => {
      if (!matchAll(nq, r.hay) || (tv && r.voto !== tv) || (leg && !LEG.has(r.tp))) return false;
      if (or === 'seguiu' && !(isRef(r.ori) && r.voto === r.ori)) return false;
      if (or === 'divergiu' && !(isRef(r.ori) && r.voto !== r.ori)) return false;
      if (or === 'livre' && r.ori !== 'L') return false;
      if (or === 'sem' && r.ori !== '') return false;
      if (gv === 'com' && !(isRef(r.gov) && r.voto === r.gov)) return false;
      if (gv === 'contra' && !(isRef(r.gov) && r.voto !== r.gov)) return false;
      if (cp) {
        const [modo, campo] = cp.split('-'); const ref = r.camp[campo];
        if (!ref || (modo === 'com') !== (r.voto === ref)) return false;
      }
      if (pol && !(r.camp.esquerda && r.camp.direita && r.camp.esquerda !== r.camp.direita)) return false;
      return true;
    });
    drawTemas(base);
    cur = th ? base.filter(r => r.tm.includes(+th)) : base;
    shown = 30; draw();
  };
  const pick = c => { sel.value = sel.value === c ? '' : (c === '0' ? '' : c); filter(); };
  $('#vtemas').addEventListener('click', e => { const tr = e.target.closest('[data-tema]'); if (tr) pick(tr.dataset.tema); });
  $('#vtemas').addEventListener('keydown', e => { if (e.key === 'Enter') { const tr = e.target.closest('[data-tema]'); if (tr) pick(tr.dataset.tema); } });
  $('#vlist').addEventListener('click', e => { const p = e.target.closest('.pill[data-tema]'); if (p) { sel.value = p.dataset.tema; filter(); $('#vtemas').scrollIntoView({ block: 'nearest' }); } });
  ['#vq', '#vv', '#vt', '#vth', '#vor', '#vgov', '#vcamp', '#vpol'].forEach(s => $(s).addEventListener('input', filter));
  $('#vmore').addEventListener('click', () => { shown += 50; draw(); });
  root.querySelector('[data-metodo]')?.addEventListener('click', e => { e.preventDefault(); const d = document.getElementById('metodo'); d.open = true; d.scrollIntoView({ behavior: 'smooth' }); });
  filter();
}

/* ---------- gastos ---------- */
function barChart(serie, refSerie) {
  const W = 720, H = 200, pl = 46, pb = 22, pt = 8, pr = 6;
  const n = serie.length; if (!n) return '';
  const max = Math.max(...serie.map(s => s[1]), ...serie.map(s => refSerie[s[0]] || 0), 1) * 1.08;
  const bw = (W - pl - pr) / n;
  const y = v => pt + (H - pt - pb) * (1 - Math.max(v, 0) / max);
  const bars = serie.map(([m, v], i) => `<rect class="b" x="${(pl + i * bw + bw * 0.12).toFixed(1)}" y="${y(v).toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" height="${(H - pb - y(v)).toFixed(1)}"><title>${fmes(m)}: ${brl.format(v)}</title></rect>`).join('');
  const pts = serie.filter(s => refSerie[s[0]] != null).map(([m], i) => `${(pl + serie.findIndex(s => s[0] === m) * bw + bw / 2).toFixed(1)},${y(refSerie[m]).toFixed(1)}`).join(' ');
  const ticks = [0, .5, 1].map(f => { const v = max * f / 1.08; return `<text x="${pl - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${v >= 1000 ? Math.round(v / 1000) + ' mil' : Math.round(v)}</text><line x1="${pl}" x2="${W - pr}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--line)"/>`; }).join('');
  const step = Math.ceil(n / 10);
  const labels = serie.map(([m], i) => i % step === 0 ? `<text x="${(pl + i * bw + bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${fmes(m)}</text>` : '').join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Gastos mensais do deputado comparados à média nacional">${ticks}${bars}<polyline class="ref" points="${pts}"/>${labels}</svg>`;
}
function sectionGastos(dep, meta, ufm) {
  const g = dep.gastos, nac = meta.nacional.gasto_mensal;
  const cats = g.categorias;
  const maxCat = Math.max(...cats.map(c => Math.max(c[2], c[3], c[4] || 0)), 1);
  const bar = c => `<div class="bar" title="Deputado: ${brl.format(c[2])}/mês · média nacional: ${brl.format(c[3])} · média ${esc(dep.uf)}: ${brl.format(c[4] || 0)}"><i style="width:${Math.max(c[2], 0) / maxCat * 100}%"></i><u style="left:${c[3] / maxCat * 100}%"></u></div>`;
  const html = `
  <section class="card" id="s-gastos">
    <h2>Gastos com a cota parlamentar (CEAP)</h2>
    <p class="lead">A cota cobre passagens, combustível, divulgação, escritório etc. Valores líquidos, de ${fmes(dep.inicio.slice(0, 7))} a ${fmes(meta.ceap_ate)} (meses seguintes ainda estão sendo lançados pela Câmara).</p>
    <div class="stats">
      ${stat(brl.format(g.total), 'gasto total no período')}
      ${stat(brl.format(g.mensal), 'média por mês', compare(g.mensal, nac.media, 'da média nacional') + ' ' + (ufm ? compare(g.mensal, ufm.gasto_mensal.media, `da média de ${dep.uf}`) : ''))}
      ${stat(brl.format(nac.media), 'média nacional por mês', `<div class="l">${int.format(meta.nacional.n)} deputados · mediana ${brl.format(nac.mediana)}</div>`)}
      ${ufm ? stat(brl.format(ufm.gasto_mensal.media), `média da bancada de ${esc(dep.uf)}`, `<div class="l">${ufm.n} deputados</div>`) : ''}
    </div>
    <h3>Gasto mês a mês <span class="muted small">(linha = média nacional)</span></h3>
    ${barChart(g.serie, meta.serie_nacional)}
    <div class="legend"><span><i class="sw"></i>gasto do deputado</span><span><i class="sw ref"></i>média nacional no mês</span></div>
    <h3>Por categoria (média mensal)</h3>
    <table><thead><tr><th>Categoria</th><th class="r">Total</th><th class="r">Por mês</th><th class="r">Média nac.</th><th class="r">Média ${esc(dep.uf)}</th><th style="width:20%">vs. média nacional</th></tr></thead>
    <tbody>${cats.map(c => `<tr><td>${esc(c[0])}</td><td class="r">${brl.format(c[1])}</td><td class="r">${brl.format(c[2])}</td><td class="r">${brl.format(c[3])}</td><td class="r">${c[4] == null ? '—' : brl.format(c[4])}</td><td>${bar(c)}</td></tr>`).join('')}</tbody></table>
    <p class="muted small">A barra é o gasto mensal do deputado; o traço preto marca a média nacional daquela categoria. Passagens aéreas e divulgação tendem a variar muito com a distância de Brasília e o estilo de mandato — média não é limite nem meta.</p>
  </section>`;
  return { html };
}

/* ---------- presença ---------- */
function sectionPres(dep, nac, ufm) {
  const p = dep.presenca;
  const anos = Object.entries(p.por_ano);
  const html = `
  <section class="card" id="s-pres">
    <h2>Presença</h2>
    <p class="lead">Presença registrada nas sessões <b>deliberativas</b> do Plenário (as que têm votação) durante o período de mandato. A Câmara não publica em dados abertos se a ausência foi justificada.</p>
    <div class="stats">
      ${stat(pct1(p.pct), 'presença em sessões deliberativas', `<div class="l">${int.format(p.presencas)} de ${int.format(p.sessoes)} sessões</div>` + compare(p.pct, nac.pct_presenca.media, 'da média nacional'))}
      ${stat(pct1(nac.pct_presenca.media), 'média nacional', `<div class="l">mediana ${pct1(nac.pct_presenca.mediana)}${ufm ? ` · média ${esc(dep.uf)}: ${pct1(ufm.pct_presenca.media)}` : ''}</div>`)}
      ${stat(pct1(p.pct_votos), 'participação nas votações nominais', `<div class="l">${int.format(p.votos)} de ${int.format(p.votacoes)}</div>` + compare(p.pct_votos, nac.pct_votos.media, 'da média nacional'))}
    </div>
    <h3>Por ano</h3>
    <table><thead><tr><th>Ano</th><th class="r">Presenças</th><th class="r">Sessões</th><th style="width:40%"></th></tr></thead>
    <tbody>${anos.map(([a, [x, t]]) => `<tr><td>${a}</td><td class="r">${x}</td><td class="r">${t}</td><td><div class="bar"><i style="width:${t ? 100 * x / t : 0}%"></i></div></td></tr>`).join('')}</tbody></table>
  </section>`;
  return { html };
}

/* ---------- metodologia ---------- */
async function methodology() {
  const [meta, ide, idv] = await Promise.all([load('data/meta.json'), load('data/ideologia.json'), load('data/ideologia_voto.json')]);
  const idvMin = idv.min_votos, idvDiag = idv.diagnostico;
  document.getElementById('metodo-corpo').innerHTML = `
  <ul>
    <li><b>Fonte:</b> arquivos abertos da Câmara (proposições, autores, votações, votos, eventos, presenças e cota parlamentar), legislatura 57 (fev/2023 em diante). Dados gerados em ${fdate(meta.gerado_em)}; presença e votos até ${fdate(meta.dados_ate)}; gastos até ${fmes(meta.ceap_ate)}.</li>
    <li><b>Período do deputado:</b> do primeiro ao último registro dele em presença ou votação. Vale para suplentes e para quem se licenciou: as médias usam só o tempo em que a pessoa aparece nos registros, mas licenças no meio do mandato não são descontadas.</li>
    <li><b>Propostas:</b> mostramos PL, PLP, PEC, PDL, PRC e afins. "Autor principal" = primeiro signatário. Quantidade não é qualidade: um deputado pode apresentar muitos projetos sem que avancem.</li>
    <li><b>Votos:</b> apenas votações nominais no Plenário. Votação simbólica não registra voto individual; ausências nessas votações não aparecem.</li>
    <li><b>Orientação da liderança:</b> vem dos dados oficiais da Câmara (orientação de cada bancada em cada votação). Partidos em federação ou bloco seguem a orientação da federação/bloco. Os blocos vêm com nome truncado nos dados: associamos cada um aos partidos pela composição divulgada pela Câmara e, para quatro blocos de 2023 e 2025 que não constam na lista oficial, deduzimos os membros pelos partidos que ficam sem nenhuma outra linha de orientação na votação. "Sem orientação" significa que o registro oficial está em branco: isso é comum em 2025 (cerca de 60% dos votos daquele ano), quando os partidos estavam agrupados em blocos que quase nunca registraram orientação. "Liberou" significa que o partido deixou os deputados livres. A orientação do Governo vem do mesmo arquivo.</li>
    <li><b>Orientação ideológica:</b> nota de 0 (esquerda) a 10 (direita) dada por mais de 500 cientistas políticos da ABCP, em <a href="${esc(ide.fonte.url)}" target="_blank" rel="noopener">${esc(ide.fonte.titulo)}</a> (${esc(ide.fonte.autores)}, ${esc(ide.fonte.publicacao)}). Faixas do próprio artigo: extrema-esquerda até 1,5; esquerda até 3; centro-esquerda até 4,49; centro de 4,5 a 5,5; centro-direita até 7; direita até 8,5; extrema-direita acima disso. Partidos renomeados usam a nota do nome anterior (Republicanos = PRB, PL = PR, Cidadania = PPS, Solidariedade = SDD); União e PRD (fusões recentes) usam a média dos partidos que os formaram, marcada como "estimada"; Missão não tem classificação. É uma <b>medida acadêmica da percepção sobre o partido</b>, não sobre cada deputado, e o partido pode ter mudado de posição desde a pesquisa. Para os "campos" ("esquerda", "centro", "direita") agrupamos as faixas: esquerda = extrema-esquerda + esquerda + centro-esquerda; direita = centro-direita + direita + extrema-direita. Por isso partidos do chamado centrão (MDB, PSD, PP, União…) caem em "direita". A maioria de cada campo em cada votação é calculada por nós a partir dos votos Sim/Não dos deputados do campo (só quando há ao menos 5 votos).</li>
    <li><b>Gastos:</b> cota parlamentar (CEAP), valor líquido. Os limites da cota variam por estado (distância a Brasília). A verba de gabinete (salários de assessores) não está nos dados abertos da Câmara em formato comparável e <b>não</b> é considerada. Meses recentes são cortados porque as notas chegam com atraso.</li>
    <li><b>Médias:</b> só entram deputados com pelo menos ${meta.min_meses_media} meses de mandato (${meta.nacional.n} deputados), tanto na média nacional quanto na do estado.</li>
    <li><b>Presença:</b> registros de presença nas sessões deliberativas do Plenário. A Câmara considera justificativas e missões oficiais, que não estão nos dados abertos; por isso o número pode ser menor que o "oficial".</li>
    <li><b>Orientação ideológica pelo voto:</b> em vez da imagem do partido, mede-se o comportamento. Cada deputado com pelo menos ${idvMin} votos Sim/Não é posicionado num eixo único pelas votações nominais do Plenário (modelo de posto 1 sobre a matriz deputados × votações, ajustado por mínimos quadrados alternados; deputados que votam igual ficam próximos). Só entram votações <b>contestadas</b> (a minoria tem ao menos 10% dos votos) e em que o <b>Governo não orientou Sim/Não</b> (${int.format(idvDiag.votacoes_B)} votações). Motivo: com todas as votações (${int.format(idvDiag.votacoes_A)}) o eixo encontrado é governo × oposição, com correlação de ${idvDiag.A.corr_governo.toLocaleString('pt-BR')} com o alinhamento ao Governo e só ${idvDiag.A.corr_pesquisa.toLocaleString('pt-BR')} com a pesquisa acadêmica; excluindo as votações em que o Governo orientou, a correlação com a pesquisa sobe para ${idvDiag.B.corr_pesquisa.toLocaleString('pt-BR')}. O sinal do eixo é fixado colocando o PSOL à esquerda do PL (única âncora externa). A escala é reescalada de 0 a 10 (2º e 98º percentis dos deputados = 0 e 10) e as faixas usam os mesmos cortes do artigo, mas a escala é <b>relativa a esta Câmara e a esta legislatura</b>: "direita" pelo voto significa "vota mais como a direita desta Câmara", não uma medida absoluta. O eixo capta comportamento em votações, que também reflete alianças, emendas e negociação, e não só convicção. A nota do partido pelo voto é a mediana de seus deputados; a faixa mostra a dispersão (metade central). Deputados com poucos votos nessas votações ficam sem posição.</li>
    <li><b>Candidatura em 2026:</b> vem do registro de candidaturas do TSE (dados de ${fdate(meta.candidaturas_tse_em.split('/').reverse().join('-'))}). Cruzamos com os deputados pelo nome civil e data de nascimento; quando a grafia difere, aceitamos a mesma data de nascimento no mesmo estado com nome parecido ou igual ao nome parlamentar. "Reeleição" aqui significa: exerceu o mandato de deputado federal nesta legislatura (inclusive suplentes) e registrou candidatura a deputado federal. O arquivo do TSE não informa se o registro já foi deferido ou impugnado. "Sem candidatura" quer dizer que não encontramos o nome no registro, o que pode ser mesmo ausência de candidatura ou uma divergência de cadastro.</li>
    <li>Nada aqui é nota ou recomendação de voto.</li>
  </ul>`;
}

/* ---------- roteador ---------- */
async function route() {
  const m = location.hash.match(/^#\/d\/(\d+)/);
  try {
    if (m) await viewDep(m[1]); else await viewList();
    window.scrollTo(0, 0);
  } catch (e) {
    console.error(e);
    app.innerHTML = `<div class="notice">Não foi possível carregar os dados (${esc(e.message)}). Se abriu o arquivo direto do disco, sirva a pasta <code>web/</code> com um servidor local (<code>python3 -m http.server</code>).</div>`;
  }
}
window.addEventListener('hashchange', route);
methodology().catch(e => console.error('metodologia:', e));
route();
})();

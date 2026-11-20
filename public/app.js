/* Brabo Estoque — tela única, pensada para o celular.
   Três coisas que importam aqui:
   1) cadastrar em sequência (um item, próximo item) sem perder setor/pessoa;
   2) funcionar com sinal ruim: o que você registra entra numa fila local e sobe depois;
   3) consultar offline: a última leitura fica guardada no aparelho. */

const SITUACAO = {
  em_estoque: { rotulo: 'Em estoque', classe: 't-estoque' },
  com_colaborador: { rotulo: 'Com colaborador', classe: 't-pessoa' },
  manutencao: { rotulo: 'Manutenção', classe: 't-manutencao' },
  emprestado: { rotulo: 'Emprestado', classe: 't-emprestado' },
  baixado: { rotulo: 'Baixado', classe: 't-baixado' },
};
const CONDICOES = { novo: 'Novo', bom: 'Bom', regular: 'Regular', ruim: 'Ruim', defeito: 'Com defeito' };
const ACOES_ROTULO = {
  cadastro: 'Cadastrado', edicao: 'Editado', entrega: 'Entregue', devolucao: 'Devolvido',
  transferencia: 'Transferido', manutencao: 'Para manutenção', retorno: 'Voltou da manutenção',
  baixa: 'Baixado', exclusao: 'Excluído',
};
const SETORES_SEMENTE = ['Comercial', 'Marketing', 'Operacional', 'Atendimento', 'Financeiro',
  'RH', 'Redação', 'Diretoria', 'TI', 'Logística', 'Expedição', 'Audiovisual'];

const S = {
  dados: null,
  aba: 'estoque',
  filtro: { status: null, setor: null, busca: '' },
  buscaPessoas: '',
  fila: [],
  ultimo: { setor: '', pessoa: '', status: 'em_estoque' },
  enviando: false,
};

/* ───────────────────────── utilidades ───────────────────────── */
const $ = (sel) => document.querySelector(sel);
const esc = (v) => (v == null ? '' : String(v).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));

function aviso(texto, erro) {
  const el = $('#aviso');
  el.textContent = texto;
  el.classList.toggle('erro', !!erro);
  el.hidden = false;
  clearTimeout(aviso._t);
  aviso._t = setTimeout(() => { el.hidden = true; }, erro ? 5000 : 2600);
}

function quando(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  return d.toLocaleString('pt-BR', {
    timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function bilhete() {
  // identificador do registro feito no celular: o servidor usa para não gravar duas vezes
  return (crypto.randomUUID ? crypto.randomUUID() : 'b' + Date.now() + Math.random().toString(36).slice(2));
}

function guardar(chave, valor) {
  try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (e) { /* aparelho sem espaço */ }
}
function lido(chave, padrao) {
  try { const v = localStorage.getItem(chave); return v ? JSON.parse(v) : padrao; } catch (e) { return padrao; }
}

/* ───────────────────────── rede e fila ───────────────────────── */
async function api(metodo, rota, corpo) {
  const r = await fetch(rota, {
    method: metodo,
    headers: corpo ? { 'Content-Type': 'application/json' } : undefined,
    body: corpo ? JSON.stringify(corpo) : undefined,
    credentials: 'same-origin',
  });
  if (r.status === 401) { mostrarLogin(); throw new Error('Entre de novo.'); }
  if (r.status === 304) return null;
  const txt = await r.text();
  const dados = txt ? JSON.parse(txt) : {};
  if (!r.ok) throw Object.assign(new Error(dados.detail || 'Não deu certo.'), { status: r.status });
  return dados;
}

/** Escrita que pode acontecer sem sinal: se a rede falhar, fica na fila e sobe depois. */
async function escrever(metodo, rota, corpo, descricao) {
  const pedido = { metodo, rota, corpo: { ...corpo, origem_id: corpo.origem_id || bilhete() }, descricao };
  try {
    return await api(pedido.metodo, pedido.rota, pedido.corpo);
  } catch (e) {
    const semRede = e instanceof TypeError || e.message === 'Failed to fetch';
    if (!semRede) throw e;
    S.fila.push(pedido);
    guardar('estoque_fila', S.fila);
    pintarPendentes();
    aviso('Sem sinal: guardei no celular e envio sozinho depois.');
    return { enfileirado: true };
  }
}

function pintarPendentes() {
  const b = $('#btn-pendentes');
  b.hidden = S.fila.length === 0;
  b.textContent = S.fila.length + ' na fila';
}

async function enviarFila(silencioso) {
  if (S.enviando || !S.fila.length) return;
  S.enviando = true;
  let enviados = 0;
  while (S.fila.length) {
    const p = S.fila[0];
    try {
      await api(p.metodo, p.rota, p.corpo);
      S.fila.shift();
      enviados++;
    } catch (e) {
      if (e.status && e.status >= 400 && e.status < 500) {
        // o servidor recusou de vez (ex.: patrimônio repetido): não insistir para sempre
        S.fila.shift();
        aviso((p.descricao || 'Um registro') + ' não entrou: ' + e.message, true);
        continue;
      }
      break; // ainda sem rede: tenta mais tarde
    }
  }
  guardar('estoque_fila', S.fila);
  pintarPendentes();
  S.enviando = false;
  if (enviados) {
    if (!silencioso) aviso(enviados + (enviados > 1 ? ' registros enviados' : ' registro enviado'));
    await carregar(true);
  }
}

/* ───────────────────────── carregar dados ───────────────────────── */
async function carregar(silencioso) {
  try {
    const d = await api('GET', '/api/dados');
    if (d) {
      S.dados = d;
      guardar('estoque_cache', d);
    }
    render();
  } catch (e) {
    const cache = lido('estoque_cache', null);
    if (cache && !S.dados) { S.dados = cache; render(); aviso('Sem sinal: mostrando a última leitura.'); }
    else if (!silencioso) aviso(e.message, true);
  }
}

/* ───────────────────────── abas ───────────────────────── */
function trocarAba(aba) {
  S.aba = aba;
  for (const b of document.querySelectorAll('.rodape button')) {
    b.setAttribute('aria-current', String(b.dataset.aba === aba));
  }
  for (const nome of ['estoque', 'pessoas', 'registrar', 'historico']) {
    $('#aba-' + nome).hidden = nome !== aba;
  }
  window.scrollTo({ top: 0 });
  render();
}

function render() {
  if (!S.dados) return;
  $('#selo-usuario').textContent = (S.dados.eu?.nome || '').split(' ')[0];
  if (S.aba === 'estoque') renderEstoque();
  if (S.aba === 'pessoas') renderPessoas();
  if (S.aba === 'registrar') renderRegistrar();
  if (S.aba === 'historico') renderHistorico();
}

/* ───────────────────────── aba: estoque ───────────────────────── */
function filtrados() {
  const b = S.filtro.busca.trim().toLowerCase();
  return (S.dados.equipamentos || []).filter((e) => {
    if (S.filtro.status && e.status !== S.filtro.status) return false;
    if (S.filtro.setor && (e.setor || '') !== S.filtro.setor) return false;
    if (!b) return true;
    return [e.patrimonio, e.tipo, e.descricao, e.marca, e.modelo, e.serie, e.setor,
      e.localizacao, e.colaborador_nome].some((v) => (v || '').toLowerCase().includes(b));
  });
}

function cartaoItem(e) {
  const s = SITUACAO[e.status] || { rotulo: e.status, classe: 't-baixado' };
  const detalhe = [e.descricao || [e.marca, e.modelo].filter(Boolean).join(' '),
    e.status === 'com_colaborador' ? e.colaborador_nome : e.setor].filter(Boolean).join(' · ');
  return `<button class="item" data-id="${e.id}">
    <div class="item-corpo">
      <div class="item-topo">
        <strong>${esc(e.tipo)}</strong>
        ${e.patrimonio ? `<span class="pat">${esc(e.patrimonio)}</span>` : ''}
      </div>
      <div class="linha2">${esc(detalhe) || '—'}</div>
    </div>
    <span class="tag ${s.classe}">${s.rotulo}</span>
  </button>`;
}

function renderEstoque() {
  const r = S.dados.resumo || {};
  const setores = (S.dados.sugestoes?.setores || []);
  const itens = filtrados();
  const cards = [
    ['', 'Total', r.total || 0],
    ['em_estoque', 'Em estoque', r.em_estoque || 0],
    ['com_colaborador', 'Com pessoas', r.com_colaborador || 0],
    ['manutencao', 'Manutenção', r.manutencao || 0],
  ];
  if (r.baixado) cards.push(['baixado', 'Baixados', r.baixado]);

  $('#aba-estoque').innerHTML = `
    <div class="numeros">
      ${cards.map(([st, rot, n]) => `<button class="numero" data-status="${st}"
          aria-pressed="${(S.filtro.status || '') === st}"><b>${n}</b><span>${rot}</span></button>`).join('')}
    </div>
    <div class="busca">
      <input id="busca" type="search" inputmode="search" placeholder="Buscar patrimônio, item, pessoa…"
             value="${esc(S.filtro.busca)}">
    </div>
    ${setores.length ? `<div class="chips">
      <button class="chip" data-setor="" aria-pressed="${!S.filtro.setor}">Todos os setores</button>
      ${setores.map((s) => `<button class="chip" data-setor="${esc(s)}"
          aria-pressed="${S.filtro.setor === s}">${esc(s)}</button>`).join('')}
    </div>` : ''}
    <div class="lista" id="lista-estoque">
      ${itens.length ? itens.map(cartaoItem).join('')
        : `<p class="vazio">${r.total ? 'Nada com esse filtro.' : 'Nenhum equipamento cadastrado ainda.<br>Toque em <b>Registrar</b> para começar.'}</p>`}
    </div>
    ${itens.length ? `<p class="muted" style="text-align:center;font-size:.84rem">${itens.length} de ${r.total || 0} itens</p>` : ''}
  `;

  const busca = $('#busca');
  busca.oninput = () => {
    S.filtro.busca = busca.value;
    const lista = $('#lista-estoque');
    const achados = filtrados();
    lista.innerHTML = achados.length ? achados.map(cartaoItem).join('')
      : '<p class="vazio">Nada com esse filtro.</p>';
  };
  for (const b of document.querySelectorAll('#aba-estoque .numero')) {
    b.onclick = () => { S.filtro.status = b.dataset.status || null; renderEstoque(); };
  }
  for (const b of document.querySelectorAll('#aba-estoque .chip')) {
    b.onclick = () => { S.filtro.setor = b.dataset.setor || null; renderEstoque(); };
  }
}

/* ───────────────────────── aba: pessoas ───────────────────────── */
function renderPessoas() {
  const b = S.buscaPessoas.trim().toLowerCase();
  const pessoas = (S.dados.colaboradores || []).filter((p) =>
    !b || (p.nome || '').toLowerCase().includes(b) || (p.setor || '').toLowerCase().includes(b));
  const porPessoa = {};
  for (const e of S.dados.equipamentos || []) {
    if (e.status === 'com_colaborador' && e.colaborador_id) {
      (porPessoa[e.colaborador_id] = porPessoa[e.colaborador_id] || []).push(e);
    }
  }
  const comItens = pessoas.filter((p) => (porPessoa[p.id] || []).length);
  const semItens = pessoas.filter((p) => !(porPessoa[p.id] || []).length);

  const bloco = (p) => {
    const itens = porPessoa[p.id] || [];
    return `<details class="grupo" ${itens.length && pessoas.length <= 3 ? 'open' : ''}>
      <summary>
        <span>
          <strong>${esc(p.nome)}</strong>
          <span class="muted" style="font-size:.84rem"> ${esc(p.setor || 'setor não informado')}</span>
        </span>
        <span style="display:flex;gap:6px;align-items:center">
          <span class="conta-itens">${itens.length} ${itens.length === 1 ? 'item' : 'itens'}</span>
          <button class="icone-btn" style="background:var(--neutral-soft);color:var(--fg);border:0"
                  data-editar-pessoa="${p.id}" title="Editar pessoa">✎</button>
        </span>
      </summary>
      <div class="itens">
        ${itens.length ? itens.map(cartaoItem).join('')
          : '<p class="muted" style="padding:6px 6px 10px;font-size:.88rem">Sem equipamento no nome dela.</p>'}
      </div>
    </details>`;
  };

  $('#aba-pessoas').innerHTML = `
    <div class="busca">
      <input id="busca-pessoas" type="search" placeholder="Buscar pessoa ou setor…" value="${esc(S.buscaPessoas)}">
      <button class="btn secundario" id="btn-nova-pessoa" style="width:auto;white-space:nowrap">+ Pessoa</button>
    </div>
    ${comItens.length ? `<p class="rotulo">Com equipamento (${comItens.length})</p>
      <div class="lista">${comItens.map(bloco).join('')}</div>` : ''}
    ${semItens.length ? `<p class="rotulo" style="margin-top:8px">Sem equipamento (${semItens.length})</p>
      <div class="lista">${semItens.map(bloco).join('')}</div>` : ''}
    ${!pessoas.length ? `<p class="vazio">${S.buscaPessoas ? 'Ninguém com esse nome.' : 'Nenhum colaborador cadastrado.<br>Eles aparecem aqui quando você entrega um equipamento.'}</p>` : ''}
  `;

  const campo = $('#busca-pessoas');
  campo.oninput = () => { S.buscaPessoas = campo.value; renderPessoas(); campo.focus(); };
  $('#btn-nova-pessoa').onclick = () => painelPessoa(null);
  for (const b of document.querySelectorAll('[data-editar-pessoa]')) {
    b.onclick = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      painelPessoa((S.dados.colaboradores || []).find((p) => p.id === +b.dataset.editarPessoa));
    };
  }
}

/* ───────────────────────── aba: registrar ───────────────────────── */
function listaSetores() {
  const vistos = new Set([...(S.dados.sugestoes?.setores || []), ...SETORES_SEMENTE]);
  return [...vistos].sort((a, b) => a.localeCompare(b, 'pt-BR'));
}

function camposEquipamento(e, idPrefixo) {
  const p = idPrefixo;
  const tipos = [...new Set([...(S.dados.sugestoes?.tipos || []), ...(S.dados.tipos_sugeridos || [])])];
  const pessoas = S.dados.colaboradores || [];
  const status = e.status || S.ultimo.status || 'em_estoque';
  return `
    <div class="campo">
      <label for="${p}-pat">Código de patrimônio</label>
      <input id="${p}-pat" name="patrimonio" value="${esc(e.patrimonio)}"
             autocapitalize="characters" autocomplete="off" placeholder="ex.: BRB-0142">
    </div>
    <div class="campo">
      <label for="${p}-tipo">Equipamento *</label>
      <input id="${p}-tipo" name="tipo" list="lista-tipos" required value="${esc(e.tipo)}"
             autocomplete="off" placeholder="Notebook, Monitor, Headset…">
      <datalist id="lista-tipos">${tipos.map((t) => `<option value="${esc(t)}">`).join('')}</datalist>
    </div>
    <div class="campo">
      <label for="${p}-desc">Descrição</label>
      <input id="${p}-desc" name="descricao" value="${esc(e.descricao)}" placeholder="ex.: Dell Latitude 3420 i5 8GB">
    </div>
    <div class="campo">
      <label for="${p}-setor">Setor</label>
      <input id="${p}-setor" name="setor" list="lista-setores" autocomplete="off"
             value="${esc(e.setor || (idPrefixo === 'novo' ? S.ultimo.setor : ''))}">
      <datalist id="lista-setores">${listaSetores().map((s) => `<option value="${esc(s)}">`).join('')}</datalist>
    </div>
    <div class="campo">
      <label for="${p}-status">Situação *</label>
      <select id="${p}-status" name="status">
        ${Object.entries(SITUACAO).filter(([k]) => k !== 'emprestado' || status === 'emprestado')
          .map(([k, v]) => `<option value="${k}" ${status === k ? 'selected' : ''}>${v.rotulo}</option>`).join('')}
      </select>
    </div>
    <div class="campo" id="${p}-caixa-pessoa" ${status === 'com_colaborador' ? '' : 'hidden'}>
      <label for="${p}-pessoa">Com qual colaborador? *</label>
      <input id="${p}-pessoa" name="colaborador_nome" list="lista-pessoas" autocomplete="off"
             value="${esc(e.colaborador_nome || (idPrefixo === 'novo' ? S.ultimo.pessoa : ''))}"
             placeholder="Nome de quem está com o item">
      <datalist id="lista-pessoas">${pessoas.map((c) => `<option value="${esc(c.nome)}">`).join('')}</datalist>
      <p class="muted" style="font-size:.8rem">Nome novo é cadastrado na hora.</p>
    </div>
    <div class="campo">
      <label for="${p}-condicao">Condição</label>
      <select id="${p}-condicao" name="condicao">
        ${Object.entries(CONDICOES).map(([k, v]) =>
          `<option value="${k}" ${(e.condicao || 'bom') === k ? 'selected' : ''}>${v}</option>`).join('')}
      </select>
    </div>
    <details ${e.marca || e.modelo || e.serie || e.valor || e.localizacao || e.observacao ? 'open' : ''}>
      <summary class="rotulo" style="cursor:pointer;margin-bottom:10px">Mais detalhes (opcional)</summary>
      <div class="duplo">
        <div class="campo"><label for="${p}-marca">Marca</label>
          <input id="${p}-marca" name="marca" value="${esc(e.marca)}"></div>
        <div class="campo"><label for="${p}-modelo">Modelo</label>
          <input id="${p}-modelo" name="modelo" value="${esc(e.modelo)}"></div>
      </div>
      <div class="duplo">
        <div class="campo"><label for="${p}-serie">Nº de série</label>
          <input id="${p}-serie" name="serie" value="${esc(e.serie)}" autocapitalize="characters"></div>
        <div class="campo"><label for="${p}-valor">Valor (R$)</label>
          <input id="${p}-valor" name="valor" inputmode="decimal" value="${e.valor == null ? '' : e.valor}"></div>
      </div>
      <div class="campo"><label for="${p}-local">Local (sala, mesa, armário)</label>
        <input id="${p}-local" name="localizacao" value="${esc(e.localizacao)}"></div>
      <div class="campo"><label for="${p}-obs">Observação</label>
        <textarea id="${p}-obs" name="observacao">${esc(e.observacao)}</textarea></div>
    </details>`;
}

function ligarTrocaStatus(form, p) {
  const sel = form.querySelector(`#${p}-status`);
  const caixa = form.querySelector(`#${p}-caixa-pessoa`);
  sel.onchange = () => {
    caixa.hidden = sel.value !== 'com_colaborador';
    if (!caixa.hidden) form.querySelector(`#${p}-pessoa`).focus();
  };
}

function valoresDoForm(form) {
  const d = {};
  for (const campo of form.querySelectorAll('[name]')) d[campo.name] = campo.value;
  return d;
}

function renderRegistrar() {
  $('#aba-registrar').innerHTML = `
    <form class="cartao" id="form-novo" autocomplete="off">
      <h2 style="margin-bottom:4px">Novo equipamento</h2>
      <p class="muted" style="font-size:.88rem;margin-bottom:14px">
        Só <b>Equipamento</b> é obrigatório. Dá para cadastrar sem patrimônio e completar depois.</p>
      ${camposEquipamento({}, 'novo')}
      <button class="btn" type="submit">Salvar e cadastrar o próximo</button>
      <button class="btn secundario" type="button" id="btn-salvar-fechar" style="margin-top:8px">
        Salvar e ver no estoque</button>
    </form>`;

  const form = $('#form-novo');
  ligarTrocaStatus(form, 'novo');
  const salvar = async (continuar) => {
    const d = valoresDoForm(form);
    if (!d.tipo?.trim()) { aviso('Diga qual é o equipamento.', true); return; }
    if (d.status === 'com_colaborador' && !d.colaborador_nome?.trim()) {
      aviso('Diga com qual colaborador o item está.', true); return;
    }
    const botoes = form.querySelectorAll('button');
    botoes.forEach((b) => { b.disabled = true; });
    try {
      const r = await escrever('POST', '/api/equipamentos', d, 'O item ' + (d.patrimonio || d.tipo));
      S.ultimo = { setor: d.setor || '', pessoa: d.colaborador_nome || '', status: d.status };
      guardar('estoque_ultimo', S.ultimo);
      if (r?.repetido) aviso('Esse já estava gravado.');
      else aviso(d.patrimonio ? d.patrimonio + ' salvo' : (d.tipo + ' salvo'));
      await carregar(true);
      if (continuar) {
        renderRegistrar();
        $('#novo-pat').focus();
      } else {
        trocarAba('estoque');
      }
    } catch (e) {
      aviso(e.message, true);
      botoes.forEach((b) => { b.disabled = false; });
    }
  };
  form.onsubmit = (ev) => { ev.preventDefault(); salvar(true); };
  $('#btn-salvar-fechar').onclick = () => salvar(false);
}

/* ───────────────────────── aba: histórico ───────────────────────── */
function renderHistorico() {
  const movs = S.dados.movimentos || [];
  $('#aba-historico').innerHTML = `
    <h2>Últimos movimentos</h2>
    <div class="lista">
      ${movs.length ? movs.map((m) => `
        <button class="item" data-id="${m.equipamento_id}">
          <div class="item-corpo">
            <div class="item-topo">
              <strong>${esc(ACOES_ROTULO[m.acao] || m.acao)}</strong>
              ${m.patrimonio ? `<span class="pat">${esc(m.patrimonio)}</span>` : ''}
            </div>
            <div class="linha2">${esc([m.tipo, m.para_nome ? '→ ' + m.para_nome : (m.de_nome ? 'de ' + m.de_nome : ''),
              m.observacao].filter(Boolean).join(' · '))}</div>
            <div class="linha2 mono" style="font-size:.78rem">${quando(m.criado_em)} · ${esc((m.usuario || '').split('@')[0])}</div>
          </div>
        </button>`).join('')
        : '<p class="vazio">Nada registrado ainda.</p>'}
    </div>`;
}

/* ───────────────────────── painel do item ───────────────────────── */
function abrirPainel(html, aoFechar) {
  const area = $('#area-painel');
  area.innerHTML = `<div class="fundo"><div class="painel" role="dialog" aria-modal="true">${html}</div></div>`;
  const fundo = area.querySelector('.fundo');
  const fechar = () => { area.innerHTML = ''; document.body.style.overflow = ''; if (aoFechar) aoFechar(); };
  fundo.onclick = (ev) => { if (ev.target === fundo) fechar(); };
  for (const b of area.querySelectorAll('[data-fechar]')) b.onclick = fechar;
  document.body.style.overflow = 'hidden';
  return { area, fechar };
}

function painelItem(id) {
  const e = (S.dados.equipamentos || []).find((x) => x.id === +id);
  if (!e) return;
  const s = SITUACAO[e.status] || { rotulo: e.status, classe: 't-baixado' };
  const linha = (rot, valor) => (valor ? `<dt>${rot}</dt><dd>${esc(valor)}</dd>` : '');
  const acoes = [];
  if (e.status === 'em_estoque') acoes.push(['entrega', 'Entregar a alguém'], ['manutencao', 'Mandar p/ manutenção']);
  if (e.status === 'com_colaborador') acoes.push(['devolucao', 'Devolver ao estoque'], ['transferencia', 'Passar p/ outra pessoa'], ['manutencao', 'Mandar p/ manutenção']);
  if (e.status === 'manutencao') acoes.push(['retorno', 'Voltou da manutenção'], ['entrega', 'Entregar a alguém']);
  if (e.status === 'emprestado') acoes.push(['devolucao', 'Devolver ao estoque']);
  if (e.status !== 'baixado') acoes.push(['baixa', 'Dar baixa']);

  const { area, fechar } = abrirPainel(`
    <div class="painel-topo">
      <div>
        <h2>${esc(e.tipo)}</h2>
        <p class="muted">${e.patrimonio ? '<span class="mono">' + esc(e.patrimonio) + '</span> · ' : ''}
          <span class="tag ${s.classe}">${s.rotulo}</span></p>
      </div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button>
    </div>
    <dl class="dados">
      ${linha('Descrição', e.descricao)}
      ${linha('Marca', e.marca)}${linha('Modelo', e.modelo)}${linha('Nº de série', e.serie)}
      ${linha('Com quem', e.colaborador_nome)}
      ${linha('Setor', e.setor)}${linha('Local', e.localizacao)}
      ${linha('Condição', CONDICOES[e.condicao] || e.condicao)}
      ${e.valor != null ? `<dt>Valor</dt><dd>R$ ${Number(e.valor).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</dd>` : ''}
      ${linha('Observação', e.observacao)}
      <dt>Atualizado</dt><dd>${quando(e.atualizado_em)} ${e.atualizado_por ? 'por ' + esc(e.atualizado_por.split('@')[0]) : ''}</dd>
    </dl>
    <div class="acoes-grid">
      ${acoes.map(([acao, rot]) => `<button class="btn secundario" data-acao="${acao}">${rot}</button>`).join('')}
      <button class="btn fantasma" data-editar>Editar dados</button>
      ${S.dados.eu?.papel === 'supervisor' ? '<button class="btn perigo" data-excluir>Excluir</button>' : ''}
    </div>
    <h3 style="margin:18px 0 6px">Histórico</h3>
    <div id="hist-item" class="muted">carregando…</div>`);

  for (const b of area.querySelectorAll('[data-acao]')) {
    b.onclick = () => { fechar(); painelAcao(e, b.dataset.acao); };
  }
  area.querySelector('[data-editar]').onclick = () => { fechar(); painelEditar(e); };
  const btnExcluir = area.querySelector('[data-excluir]');
  if (btnExcluir) {
    btnExcluir.onclick = async () => {
      if (!confirm('Excluir ' + (e.patrimonio || e.tipo) + ' e todo o histórico dele?')) return;
      try {
        await api('DELETE', '/api/equipamentos/' + e.id);
        aviso('Excluído'); fechar(); carregar(true);
      } catch (err) { aviso(err.message, true); }
    };
  }
  api('GET', `/api/equipamentos/${e.id}/historico`).then((r) => {
    const alvo = document.querySelector('#hist-item');
    if (!alvo) return;
    const h = r.historico || [];
    alvo.innerHTML = h.length ? `<ul class="hist">${h.map((m) => `<li>
        <b>${esc(ACOES_ROTULO[m.acao] || m.acao)}</b>
        ${m.para_nome ? '→ ' + esc(m.para_nome) : ''}${m.de_nome && m.acao !== 'cadastro' ? ' (antes: ' + esc(m.de_nome) + ')' : ''}
        <br><span class="muted mono" style="font-size:.78rem">${quando(m.criado_em)} · ${esc((m.usuario || '').split('@')[0])}</span>
        ${m.observacao ? '<br><span class="muted">' + esc(m.observacao) + '</span>' : ''}
      </li>`).join('')}</ul>` : '<p class="muted">Sem movimentos.</p>';
  }).catch(() => {
    const alvo = document.querySelector('#hist-item');
    if (alvo) alvo.textContent = 'Não consegui carregar o histórico agora.';
  });
}

function painelAcao(e, acao) {
  const precisaPessoa = acao === 'entrega' || acao === 'transferencia';
  const titulos = {
    entrega: 'Entregar equipamento', transferencia: 'Passar para outra pessoa',
    devolucao: 'Devolver ao estoque', manutencao: 'Mandar para manutenção',
    retorno: 'Voltou da manutenção', baixa: 'Dar baixa',
  };
  const { area, fechar } = abrirPainel(`
    <div class="painel-topo">
      <div><h2>${titulos[acao] || acao}</h2>
        <p class="muted">${esc(e.tipo)} ${e.patrimonio ? '<span class="mono">' + esc(e.patrimonio) + '</span>' : ''}</p></div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button>
    </div>
    <form id="form-acao">
      ${precisaPessoa ? `<div class="campo">
        <label for="acao-pessoa">Colaborador *</label>
        <input id="acao-pessoa" name="colaborador_nome" list="lista-pessoas-acao" required autocomplete="off"
               placeholder="Nome de quem vai ficar com o item">
        <datalist id="lista-pessoas-acao">${(S.dados.colaboradores || [])
          .map((c) => `<option value="${esc(c.nome)}">`).join('')}</datalist>
        <p class="muted" style="font-size:.8rem">Nome novo é cadastrado na hora.</p>
      </div>
      <div class="campo">
        <label for="acao-setor">Setor</label>
        <input id="acao-setor" name="setor" list="lista-setores-acao" autocomplete="off" value="${esc(e.setor)}">
        <datalist id="lista-setores-acao">${listaSetores().map((s) => `<option value="${esc(s)}">`).join('')}</datalist>
      </div>` : ''}
      <div class="campo">
        <label for="acao-obs">Observação</label>
        <textarea id="acao-obs" name="observacao" placeholder="${acao === 'baixa' ? 'Por que está sendo baixado?' : 'Opcional'}"></textarea>
      </div>
      <button class="btn" type="submit">Confirmar</button>
    </form>`);

  area.querySelector('#form-acao').onsubmit = async (ev) => {
    ev.preventDefault();
    const d = { acao, ...valoresDoForm(ev.target) };
    ev.target.querySelector('button').disabled = true;
    try {
      await escrever('POST', `/api/equipamentos/${e.id}/mover`, d, titulos[acao]);
      aviso('Pronto: ' + (titulos[acao] || acao).toLowerCase());
      fechar();
      carregar(true);
    } catch (err) {
      aviso(err.message, true);
      ev.target.querySelector('button').disabled = false;
    }
  };
}

function painelEditar(e) {
  const { area, fechar } = abrirPainel(`
    <div class="painel-topo">
      <div><h2>Editar</h2><p class="muted">${esc(e.tipo)} ${esc(e.patrimonio || '')}</p></div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button>
    </div>
    <form id="form-editar" autocomplete="off">
      ${camposEquipamento(e, 'ed')}
      <button class="btn" type="submit">Salvar alterações</button>
    </form>`);
  const form = area.querySelector('#form-editar');
  ligarTrocaStatus(form, 'ed');
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const d = valoresDoForm(form);
    if (d.status !== 'com_colaborador') { d.colaborador_id = null; d.colaborador_nome = ''; }
    else if (d.colaborador_nome?.trim() === (e.colaborador_nome || '')) d.colaborador_id = e.colaborador_id;
    form.querySelector('button[type=submit]').disabled = true;
    try {
      await escrever('PATCH', '/api/equipamentos/' + e.id, d, 'A edição de ' + (e.patrimonio || e.tipo));
      aviso('Salvo'); fechar(); carregar(true);
    } catch (err) {
      aviso(err.message, true);
      form.querySelector('button[type=submit]').disabled = false;
    }
  };
}

function painelPessoa(p) {
  const nova = !p;
  const { area, fechar } = abrirPainel(`
    <div class="painel-topo">
      <div><h2>${nova ? 'Novo colaborador' : 'Editar colaborador'}</h2></div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button>
    </div>
    <form id="form-pessoa" autocomplete="off">
      <div class="campo"><label for="p-nome">Nome *</label>
        <input id="p-nome" name="nome" required value="${esc(p?.nome)}"></div>
      <div class="campo"><label for="p-setor">Setor</label>
        <input id="p-setor" name="setor" list="lista-setores-p" value="${esc(p?.setor)}">
        <datalist id="lista-setores-p">${listaSetores().map((s) => `<option value="${esc(s)}">`).join('')}</datalist></div>
      <div class="duplo">
        <div class="campo"><label for="p-cargo">Cargo</label>
          <input id="p-cargo" name="cargo" value="${esc(p?.cargo)}"></div>
        <div class="campo"><label for="p-email">E-mail</label>
          <input id="p-email" name="email" type="email" value="${esc(p?.email)}"></div>
      </div>
      <div class="campo"><label for="p-obs">Observação</label>
        <textarea id="p-obs" name="observacao">${esc(p?.observacao)}</textarea></div>
      <button class="btn" type="submit">Salvar</button>
    </form>`);
  area.querySelector('#form-pessoa').onsubmit = async (ev) => {
    ev.preventDefault();
    const d = valoresDoForm(ev.target);
    ev.target.querySelector('button[type=submit]').disabled = true;
    try {
      if (nova) await escrever('POST', '/api/colaboradores', d, 'O colaborador ' + d.nome);
      else await escrever('PATCH', '/api/colaboradores/' + p.id, d, 'A edição de ' + p.nome);
      aviso('Salvo'); fechar(); carregar(true);
    } catch (err) {
      aviso(err.message, true);
      ev.target.querySelector('button[type=submit]').disabled = false;
    }
  };
}

function painelMenu() {
  const { area, fechar } = abrirPainel(`
    <div class="painel-topo">
      <div><h2>Opções</h2><p class="muted">${esc(S.dados?.eu?.email || '')}</p></div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button>
    </div>
    <div class="lista">
      <a class="btn secundario" style="text-align:center;text-decoration:none;display:block"
         href="/api/exportar.csv">Baixar planilha (CSV)</a>
      <button class="btn secundario" data-senha>Trocar minha senha</button>
      <button class="btn fantasma" data-sair>Sair</button>
    </div>
    <p class="muted" style="font-size:.8rem;margin-top:14px">
      Dica: no celular, use o menu do navegador → "Adicionar à tela inicial" para abrir como aplicativo.</p>`);
  area.querySelector('[data-senha]').onclick = () => { fechar(); painelSenha(); };
  area.querySelector('[data-sair]').onclick = async () => {
    await api('POST', '/api/logout').catch(() => {});
    location.reload();
  };
}

function painelSenha() {
  const { area, fechar } = abrirPainel(`
    <div class="painel-topo"><div><h2>Trocar senha</h2></div>
      <button class="fechar" data-fechar aria-label="Fechar">✕</button></div>
    <form id="form-senha">
      <div class="campo"><label for="s-atual">Senha atual</label>
        <input id="s-atual" name="atual" type="password" required autocomplete="current-password"></div>
      <div class="campo"><label for="s-nova">Senha nova (8+ caracteres)</label>
        <input id="s-nova" name="nova" type="password" required minlength="8" autocomplete="new-password"></div>
      <button class="btn" type="submit">Salvar</button>
    </form>`);
  area.querySelector('#form-senha').onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api('POST', '/api/senha', valoresDoForm(ev.target));
      aviso('Senha trocada'); fechar();
    } catch (err) { aviso(err.message, true); }
  };
}

/* ───────────────────────── login ───────────────────────── */
function mostrarLogin() {
  $('#tela-app').hidden = true;
  $('#tela-login').hidden = false;
  $('#login-email').focus();
}

$('#form-login').onsubmit = async (ev) => {
  ev.preventDefault();
  const erro = $('#login-erro');
  erro.hidden = true;
  const botao = ev.target.querySelector('button');
  botao.disabled = true;
  try {
    await api('POST', '/api/login', { email: $('#login-email').value, senha: $('#login-senha').value });
    $('#tela-login').hidden = true;
    $('#tela-app').hidden = false;
    await carregar();
    enviarFila(true);
  } catch (e) {
    erro.textContent = e.message;
    erro.hidden = false;
  } finally {
    botao.disabled = false;
  }
};

/* ───────────────────────── início ───────────────────────── */
document.addEventListener('click', (ev) => {
  const item = ev.target.closest('.item[data-id]');
  if (item) painelItem(item.dataset.id);
});
for (const b of document.querySelectorAll('.rodape button')) {
  b.onclick = () => trocarAba(b.dataset.aba);
}
$('#btn-menu').onclick = () => painelMenu();
$('#btn-recarregar').onclick = () => { carregar(); enviarFila(); };
$('#btn-pendentes').onclick = () => enviarFila();
window.addEventListener('online', () => enviarFila());
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { carregar(true); enviarFila(true); }
});

(async function iniciar() {
  S.fila = lido('estoque_fila', []);
  S.ultimo = lido('estoque_ultimo', S.ultimo);
  pintarPendentes();
  try {
    await api('GET', '/api/me');
    $('#tela-app').hidden = false;
    await carregar();
    enviarFila(true);
  } catch (e) {
    mostrarLogin();
  }
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
  setInterval(() => { if (S.fila.length && navigator.onLine) enviarFila(true); }, 30000);
})();

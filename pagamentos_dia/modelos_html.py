# -*- coding: utf-8 -*-
"""Os dois modelos do HTML dos pagamentos do dia — PROVISÓRIO.

Ficam como TEXTO dentro de um `.py`, e não como `.html` solto, por causa da
esteira: o `codigo.zip` leva só `pagamentos_dia/*.py`, e um arquivo `.html`
aqui simplesmente não chegaria à máquina de quem usa (mudar o `build.yml`
para levá-lo custaria subir o `motor_minimo.txt`). Quem os preenche é o
`html_pagamentos.py`; aqui não há regra nenhuma.

Vieram do gerador que rodava FORA do app (`gerar_html_pagamentos.py`), com
quatro mudanças:

- o que é dado entra por UM ponto de cada modelo, como JSON (`__JSON__`,
  `__STORAGE__`, `__CFG__`, `__DATA__`), e o texto visível (`__TITULO__`,
  `__SUB__`, as datas) entra já escapado — nada é colado cru no meio do
  código;
- dinheiro viaja em CENTAVOS inteiros e o navegador soma inteiros: somar
  0,10 + 0,20 em ponto flutuante não dá 0,30;
- a marca "já paguei" do HTML geral é guardada pelo ID do lançamento, e não
  pela posição da linha — gerar de novo com uma linha a mais embaralhava as
  marcas, e marca na linha errada é pagamento que não sai;
- **nenhum dado da empresa mora aqui** (o repositório é público): o
  logotipo e o rodapé do PDF de pessoa física vêm de arquivos ao lado da
  planilha (`html_pagamentos.NOMES_LOGO` e `NOME_RODAPE`), e sem eles o PDF
  sai sem logotipo e sem rodapé. O jsPDF continua vindo do CDN: o HTML abre
  no navegador de quem usa, com internet, e embutir a biblioteca aqui seria
  meio megabyte a mais no `codigo.zip` por um recurso provisório.

Removível junto com o `html_pagamentos.py` — ver o docstring dele.
"""

#: HTML geral: todas as contas num HTML só, com "Copiar" em cada dado de
#: pagamento e a caixa "já paguei" que risca a linha (guardada no navegador).
MODELO_GERAL = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Pagamentos __TITULO__</title>
<style>
  :root{
    --bg:#f4f5f7; --card:#ffffff; --text:#1c1e21; --muted:#6b7280;
    --border:#e3e5e8; --accent:#0f6b4c; --accent-bg:#e8f5ef;
    --pix-bg:#eef4ff; --pix-text:#1d4ed8; --boleto-bg:#fff4e5; --boleto-text:#9a5b00;
    --ok:#0f9d58; --danger:#c0392b;
  }
  *{box-sizing:border-box;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);}
  .wrap{max-width:1100px;margin:0 auto;padding:24px 16px 60px;}
  h1{font-size:22px;margin:0 0 4px;}
  .sub{color:var(--muted);font-size:13px;margin-bottom:20px;}
  .sticky-tabs{position:sticky;top:0;background:var(--bg);z-index:10;padding:8px 0 12px;border-bottom:1px solid var(--border);margin-bottom:20px;}
  .tabs{display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:6px;}
  .tabs::-webkit-scrollbar{height:6px;}
  .tabs::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px;}
  .tab-btn{flex:0 0 auto;border:1px solid var(--border);background:var(--card);color:var(--text);padding:7px 12px;border-radius:20px;font-size:12.5px;cursor:pointer;white-space:nowrap;}
  .tab-btn.active{background:var(--text);color:#fff;border-color:var(--text);}
  .account{background:var(--card);border:1px solid var(--border);border-radius:12px;margin-bottom:22px;overflow:hidden;}
  .account-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);}
  .account-head h2{font-size:15px;margin:0;}
  .account-total{font-size:13px;color:var(--muted);}
  .account-total b{color:var(--text);font-size:14px;}
  table{width:100%;border-collapse:collapse;font-size:12.5px;}
  .table-scroll{overflow-x:auto;}
  th{text-align:left;padding:8px 10px;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;border-bottom:1px solid var(--border);white-space:nowrap;}
  td{padding:9px 10px;border-bottom:1px solid var(--border);vertical-align:top;}
  tr:last-child td{border-bottom:none;}
  .tipo-badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;}
  .tipo-pix{background:var(--pix-bg);color:var(--pix-text);}
  .tipo-boleto{background:var(--boleto-bg);color:var(--boleto-text);}
  .tipo-link{background:#efe6fa;color:#7327c9;}
  .no-data-note{font-size:11.5px;color:var(--muted);font-style:italic;}
  .code{font-family:"SF Mono",Consolas,Menlo,monospace;font-size:11.5px;word-break:break-all;}
  .copy-cell{display:flex;align-items:flex-start;gap:6px;}
  .copy-cell .code{flex:1;padding-top:2px;}
  .copybtn{flex:none;border:1px solid var(--border);background:var(--card);color:var(--text);border-radius:6px;padding:4px 8px;font-size:11px;cursor:pointer;line-height:1;}
  .copybtn:hover{background:#f0f1f3;}
  .copybtn.copied{background:var(--ok);color:#fff;border-color:var(--ok);}
  .valor{font-weight:700;white-space:nowrap;}
  .desc{color:var(--muted);font-size:11.5px;}
  .fav{font-size:12px;}
  .status-badge{font-size:10.5px;color:var(--muted);}
  .obs{font-size:10.5px;color:#b3261e;margin-top:3px;}
  .conf{font-size:10px;color:var(--muted);margin-top:2px;}
  .chk-cell{width:34px;text-align:center;}
  input.row-chk{width:16px;height:16px;cursor:pointer;}
  tr.row-checked{opacity:.42;}
  tr.row-checked .fav,tr.row-checked .desc,tr.row-checked .code{text-decoration:line-through;}
  .pago-badge{display:none;font-size:10px;font-weight:700;color:var(--danger);border:1px solid var(--danger);border-radius:4px;padding:1px 5px;margin-left:6px;letter-spacing:.03em;}
  tr.row-checked .pago-badge{display:inline-block;}
  .summary{background:var(--card);border:1px solid var(--border);border-radius:12px;margin-bottom:20px;overflow:hidden;}
  .summary td{padding:8px 10px;}
  .summary tbody tr:last-child td{border-bottom:1px solid var(--border);}
  .summary tfoot td{padding:10px;font-size:13.5px;border-bottom:none;}
  .summary tfoot{background:var(--accent-bg);}
  .marked-cell{color:var(--muted);font-size:11.5px;}
  .marked-cell b{color:var(--ok);}
  .toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--text);color:#fff;padding:8px 16px;border-radius:20px;font-size:12.5px;opacity:0;pointer-events:none;transition:opacity .2s;}
  .toast.show{opacity:1;}
  input.copy-source{position:absolute;left:-9999px;}
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --bg:#15161a; --card:#1f2024; --text:#f0f1f3; --muted:#9aa0a6; --border:#2c2d32;
      --accent-bg:#123726; --pix-bg:#16233f; --pix-text:#8fb4ff; --boleto-bg:#3a2a10; --boleto-text:#f0b25a;
    }
    :root:not([data-theme="light"]) .tipo-link{background:#33224a;color:#c9a6f0;}
    :root:not([data-theme="light"]) .obs{color:#ffb4a8;}
  }
  :root[data-theme="dark"]{
    --bg:#15161a; --card:#1f2024; --text:#f0f1f3; --muted:#9aa0a6; --border:#2c2d32;
    --accent-bg:#123726; --pix-bg:#16233f; --pix-text:#8fb4ff; --boleto-bg:#3a2a10; --boleto-text:#f0b25a;
  }
  :root[data-theme="dark"] .tipo-link{background:#33224a;color:#c9a6f0;}
  :root[data-theme="dark"] .obs{color:#ffb4a8;}
</style>
</head>
<body>
<div class="wrap">
  <h1>Pagamentos para colar no Sicoob / Inter</h1>
  <div class="sub">__TITULO__ &middot; __SUB__ &middot; clique no botao para copiar &middot; marque a caixa quando ja pagar</div>

  <div class="summary">
    <table>
      <thead><tr><th>Conta</th><th style="width:120px">Total</th><th style="width:140px">Marcado (pago)</th></tr></thead>
      <tbody id="summaryBody"></tbody>
      <tfoot><tr><td><b>Total geral</b></td><td id="grandTotal"><b></b></td><td id="grandMarked" class="marked-cell"></td></tr></tfoot>
    </table>
  </div>

  <div class="sticky-tabs">
    <div class="tabs" id="tabs"></div>
  </div>

  <div id="accounts"></div>
</div>

<div class="toast" id="toast">Copiado</div>
<input type="text" class="copy-source" id="copySource">

<script>
const DATA = __JSON__;
const STORAGE_KEY = __STORAGE__;

function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg || 'Copiado';
  t.classList.add('show');
  clearTimeout(showToast._h);
  showToast._h = setTimeout(()=>t.classList.remove('show'), 1100);
}
function copyText(text, btn){
  function done(ok){
    if(ok){
      showToast('Copiado');
      if(btn){ const orig = btn.textContent; btn.textContent = 'Copiado'; btn.classList.add('copied'); setTimeout(()=>{btn.textContent = orig; btn.classList.remove('copied');}, 900); }
    }
  }
  function fallback(){
    const input = document.getElementById('copySource');
    input.value = text; input.style.left = '0px'; input.focus(); input.select();
    try{ document.execCommand('copy'); done(true); }catch(e){ done(false); showToast('Selecione e copie manualmente'); }
    input.style.left = '-9999px';
  }
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(text).then(()=>done(true)).catch(()=>fallback()); } else { fallback(); }
}
function slug(s){ return s.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/(^-|-$)/g,''); }
function formatBR(n){ return (Number(n)||0).toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2}); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

let checkedState = {};
try{ checkedState = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }catch(e){ checkedState = {}; }
function saveChecked(){ try{ localStorage.setItem(STORAGE_KEY, JSON.stringify(checkedState)); }catch(e){} }

// A marca "ja paguei" e guardada pelo ID do lancamento no ERP, e nao pela
// posicao da linha: gerar o HTML de novo com uma linha a mais embaralharia
// as marcas, e uma linha marcada por engano e um pagamento que nao sai.
function rowKey(c, e, idx){ return e.id ? ('id:' + e.id) : (slug(c.nome) + '__' + idx); }
// Os valores viajam em CENTAVOS inteiros: somar 0,10 + 0,20 em ponto
// flutuante nao da 0,30, e esta tela soma dinheiro.
function reais(centavos){ return formatBR((Number(centavos)||0) / 100); }

function updateSummary(){
  let grandTotal = 0, grandMarked = 0, grandMarkedCount = 0, grandCount = 0;
  DATA.contas.forEach((c, ci) => {
    let total = 0, marked = 0, markedCount = 0;
    c.entries.forEach((e, idx) => {
      total += e.centavos;
      if(checkedState[rowKey(c, e, idx)]){ marked += e.centavos; markedCount++; }
    });
    grandTotal += total; grandMarked += marked; grandMarkedCount += markedCount; grandCount += c.entries.length;
    const row = document.getElementById('sumrow-' + ci);
    if(row){
      row.querySelector('.sum-total').textContent = 'R$ ' + reais(total);
      row.querySelector('.sum-marked').innerHTML = markedCount ? `<b>${markedCount}/${c.entries.length}</b> &middot; R$ ${reais(marked)}` : `0/${c.entries.length}`;
    }
    const head = document.getElementById('acc-' + ci + '-total');
    if(head) head.textContent = 'R$ ' + reais(total);
  });
  document.getElementById('grandTotal').innerHTML = '<b>R$ ' + reais(grandTotal) + '</b>';
  document.getElementById('grandMarked').innerHTML = grandMarkedCount ? `<b>${grandMarkedCount}/${grandCount}</b> &middot; R$ ${reais(grandMarked)}` : `0/${grandCount}`;
}
function renderSummary(){
  const body = document.getElementById('summaryBody');
  DATA.contas.forEach((c, ci) => {
    const tr = document.createElement('tr');
    tr.id = 'sumrow-' + ci;
    tr.innerHTML = `<td>${esc(c.nome)}</td><td class="sum-total"></td><td class="sum-marked marked-cell"></td>`;
    body.appendChild(tr);
  });
}
function renderAccounts(){
  const tabsEl = document.getElementById('tabs');
  const accEl = document.getElementById('accounts');
  DATA.contas.forEach((c, ci) => {
    const idx = ci;
    const id = 'acc-' + ci;
    const tabBtn = document.createElement('button');
    tabBtn.className = 'tab-btn' + (idx===0 ? ' active' : '');
    tabBtn.textContent = c.nome;
    tabBtn.onclick = () => { document.getElementById(id).scrollIntoView({behavior:'smooth', block:'start'}); };
    tabsEl.appendChild(tabBtn);

    const section = document.createElement('div');
    section.className = 'account'; section.id = id;
    const head = document.createElement('div');
    head.className = 'account-head';
    head.innerHTML = `<h2>${esc(c.nome)}</h2><div class="account-total">Total <b id="acc-${ci}-total">R$ ${esc(c.total)}</b></div>`;
    section.appendChild(head);

    const scrollWrap = document.createElement('div');
    scrollWrap.className = 'table-scroll';
    const table = document.createElement('table');
    table.innerHTML = `
      <thead><tr>
        <th class="chk-cell" title="Ja paguei">Ok</th>
        <th style="width:60px">Tipo</th>
        <th>Dados do pagamento (boleto / chave pix)</th>
        <th style="width:100px">Valor</th>
        <th>Fornecedor</th>
        <th>Descricao</th>
      </tr></thead><tbody></tbody>`;
    const tbody = table.querySelector('tbody');

    c.entries.forEach((e, idx) => {
      const tr = document.createElement('tr');
      const rowId = rowKey(c, e, idx);
      const isChecked = !!checkedState[rowId];
      if(isChecked) tr.classList.add('row-checked');
      const badgeClass = (e.tipo || '').startsWith('Pix') ? 'tipo-pix' : (e.tipo === 'Transferência' || e.tipo === 'Link' ? 'tipo-link' : 'tipo-boleto');
      const dadosCell = e.dados_limpo
        ? `<div class="copy-cell"><span class="code">${esc(e.dados_limpo)}</span><button class="copybtn" type="button">Copiar</button></div>`
        : `<div class="no-data-note">${esc(e.dados_original || 'Sem boleto/chave - ver observacao')}</div>`;
      tr.innerHTML = `
        <td class="chk-cell"><input type="checkbox" class="row-chk" ${isChecked ? 'checked' : ''}></td>
        <td><span class="tipo-badge ${badgeClass}">${esc(e.tipo)}</span></td>
        <td>${dadosCell}</td>
        <td><div class="copy-cell"><span class="code valor">${esc(e.valor)}</span><button class="copybtn" type="button">Copiar</button></div></td>
        <td><div class="fav">${esc(e.favorecido)}<span class="pago-badge">PAGO</span></div><div class="status-badge">${esc(e.status)}</div>${e.conferencia ? `<div class="conf">${esc(e.conferencia)}</div>` : ''}${e.obs ? `<div class="obs">${esc(e.obs)}</div>` : ''}</td>
        <td><div class="copy-cell"><span class="desc">${esc(e.descricao)}</span><button class="copybtn" type="button">Copiar</button></div></td>`;
      const btns = tr.querySelectorAll('.copybtn');
      let bi = 0;
      if(e.dados_limpo){ const b = btns[bi]; b.addEventListener('click', () => copyText(e.dados_limpo, b)); bi++; }
      { const b = btns[bi]; b.addEventListener('click', () => copyText(e.valor, b)); bi++; }
      { const b = btns[bi]; b.addEventListener('click', () => copyText(e.descricao, b)); }
      const chk = tr.querySelector('.row-chk');
      chk.addEventListener('change', () => { checkedState[rowId] = chk.checked; tr.classList.toggle('row-checked', chk.checked); saveChecked(); updateSummary(); });
      tbody.appendChild(tr);
    });

    scrollWrap.appendChild(table);
    section.appendChild(scrollWrap);
    accEl.appendChild(section);
  });

  const tabBtns = Array.from(tabsEl.children);
  const sections = DATA.contas.map((c, ci) => document.getElementById('acc-' + ci));
  window.addEventListener('scroll', () => {
    let activeIdx = 0;
    sections.forEach((s, i) => { if(s.getBoundingClientRect().top <= 90) activeIdx = i; });
    tabBtns.forEach((b,i)=>b.classList.toggle('active', i===activeIdx));
  }, {passive:true});
}
renderSummary(); renderAccounts(); updateSummary();
</script>
</body>
</html>
'''


#: HTML da conta PESSOA FISICA - APENAS LANÇAMENTO: seleção, "Gerar PDF" e o
#: modal do texto da primeira página; o PDF sai no layout do "Relatório de
#: Pagamentos por Vencimento" do Mais Controle, e o que foi gerado some da
#: tela (guardado no navegador, com "Restaurar").
MODELO_PF = r'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PF - pagar __HOJE_BR__</title>
<style>
  :root{--bg:#f4f5f7;--card:#fff;--text:#1c1e21;--muted:#6b7280;--border:#e3e5e8;--accent:#0f6b4c;--accent-bg:#e8f5ef;--pix:#1d4ed8;--pix-bg:#eef4ff;--bol:#9a5b00;--bol-bg:#fff4e5;--sel:#eef7f2}
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:13px}
  .wrap{max-width:1100px;margin:0 auto;padding:20px 16px 90px}
  h1{font-size:20px;margin:0 0 2px}
  .sub{color:var(--muted);font-size:12.5px;margin-bottom:14px}
  .bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--border);margin-bottom:12px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
  .bar .spacer{flex:1}
  .btn{border:1px solid var(--border);background:var(--card);color:var(--text);padding:8px 14px;border-radius:8px;font-size:13px;cursor:pointer}
  .btn:hover{background:#f0f1f3}
  .btn.primary{background:var(--text);color:#fff;border-color:var(--text);font-weight:600}
  .btn.primary:disabled{opacity:.35;cursor:not-allowed}
  .kpi{font-size:12.5px;color:var(--muted)} .kpi b{color:var(--text);font-size:14px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;padding:9px 10px;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;border-bottom:1px solid var(--border);background:#fafbfc}
  td{padding:9px 10px;border-bottom:1px solid var(--border);vertical-align:top}
  tr:last-child td{border-bottom:none}
  tr.sel td{background:var(--sel)}
  tr.row{cursor:pointer}
  .chk{width:36px;text-align:center}
  input[type=checkbox]{width:16px;height:16px;cursor:pointer}
  .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
  .b-pix{background:var(--pix-bg);color:var(--pix)} .b-bol{background:var(--bol-bg);color:var(--bol)} .b-out{background:#eee;color:#555}
  .fav{font-weight:600} .dados{color:var(--muted);font-size:11.5px;font-family:"SF Mono",Consolas,Menlo,monospace;word-break:break-all}
  .valor{font-weight:700;white-space:nowrap;text-align:right}
  .desc{font-size:12.5px} .cat{color:var(--muted);font-size:11.5px}
  .obra{font-size:12.5px} .item{color:var(--muted);font-size:11.5px}
  .empty{padding:40px;text-align:center;color:var(--muted)}
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;z-index:50;padding:16px}
  .overlay.show{display:flex}
  .modal{background:var(--card);border-radius:14px;width:min(720px,100%);padding:20px 22px;box-shadow:0 20px 60px rgba(0,0,0,.3)}
  .modal h2{margin:0 0 4px;font-size:17px}
  .modal p{margin:0 0 12px;color:var(--muted);font-size:12.5px}
  textarea{width:100%;min-height:170px;border:1px solid var(--border);border-radius:10px;padding:12px;font:inherit;font-size:14px;resize:vertical}
  .modal .actions{display:flex;gap:10px;justify-content:flex-end;margin-top:14px}
  .toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--text);color:#fff;padding:9px 16px;border-radius:20px;font-size:12.5px;opacity:0;pointer-events:none;transition:opacity .2s;z-index:60}
  .toast.show{opacity:1}
  .link{background:none;border:none;color:var(--muted);text-decoration:underline;cursor:pointer;font-size:12px;padding:0}
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){--bg:#15161a;--card:#1f2024;--text:#f0f1f3;--muted:#9aa0a6;--border:#2c2d32;--pix-bg:#16233f;--pix:#8fb4ff;--bol-bg:#3a2a10;--bol:#f0b25a;--sel:#173324;--accent-bg:#123726}
    :root:not([data-theme="light"]) th{background:#232428} :root:not([data-theme="light"]) .btn:hover{background:#2a2b30} :root:not([data-theme="light"]) .b-out{background:#333;color:#ccc}
  }
  :root[data-theme="dark"]{--bg:#15161a;--card:#1f2024;--text:#f0f1f3;--muted:#9aa0a6;--border:#2c2d32;--pix-bg:#16233f;--pix:#8fb4ff;--bol-bg:#3a2a10;--bol:#f0b25a;--sel:#173324;--accent-bg:#123726}
  :root[data-theme="dark"] th{background:#232428} :root[data-theme="dark"] .btn:hover{background:#2a2b30} :root[data-theme="dark"] .b-out{background:#333;color:#ccc}
</style>
</head>
<body>
<div class="wrap">
  <h1>PESSOA FÍSICA - APENAS LANÇAMENTO &middot; vencimentos de __INI_BR__ a __FIM_BR__ (pagar hoje, __HOJE_BR__)</h1>
  <div class="sub">Marque os pagamentos, clique em <b>Gerar PDF</b>, escreva o texto da primeira página (quem está pagando) e confirme. O PDF sai no layout do "Relatório de Pagamentos por Vencimento" do Mais Controle. O que for gerado some da lista (fica guardado; dá para restaurar).</div>

  <div class="bar">
    <button class="btn" id="btnTodos" type="button">Selecionar todos</button>
    <button class="btn" id="btnNenhum" type="button">Limpar seleção</button>
    <span class="kpi">Na tela: <b id="kTotal"></b> &middot; Selecionados: <b id="kSel">0</b> &middot; <b id="kSelValor">R$ 0,00</b></span>
    <span class="spacer"></span>
    <button class="link" id="btnRestaurar" type="button" hidden></button>
    <button class="btn primary" id="btnGerar" type="button" disabled>Gerar PDF</button>
  </div>

  <div class="card">
    <table>
      <thead><tr>
        <th class="chk"><input type="checkbox" id="chkAll" title="Selecionar todos"></th>
        <th style="width:80px">Venc.</th>
        <th style="width:70px">Tipo</th>
        <th>Favorecido / dados</th>
        <th style="width:110px;text-align:right">Valor</th>
        <th>Descrição</th>
        <th>Obra</th>
        <th style="width:110px">Nº doc</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="empty" id="empty" hidden>Nenhum pagamento pendente na tela.</div>
  </div>
</div>

<div class="overlay" id="overlay">
  <div class="modal">
    <h2>Texto da primeira página</h2>
    <p>O que você escrever aqui vai na primeira página do PDF, antes do relatório de lançamentos. <span id="mResumo"></span></p>
    <textarea id="txtMsg" placeholder="Ex.: NOME DE QUEM PAGA - BANCO"></textarea>
    <div class="actions">
      <button class="btn" id="btnCancelar" type="button">Cancelar</button>
      <button class="btn primary" id="btnConfirmar" type="button">Gerar PDF</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<script>
// Tudo o que vem do app entra por aqui, como JSON — nunca colado no meio do
// codigo. O logotipo e o rodape da empresa NAO moram no modelo (o repositorio
// e publico): o app os le de arquivos ao lado da planilha, quando existem.
const CFG = __CFG__;
const HOJE = CFG.hoje, HOJE_BR = CFG.hoje_br, INI_BR = CFG.ini_br, FIM_BR = CFG.fim_br, PERIODO = CFG.periodo;
const CONTA = CFG.conta;
const LOGO = CFG.logo || "";
const RODAPE = CFG.rodape || [];
const ITENS = __DATA__;
const KEY_REMOVIDOS = "pf_removidos_" + PERIODO;
const KEY_MSG = "pf_msg_" + PERIODO;

let removidos = new Set();
try { removidos = new Set(JSON.parse(localStorage.getItem(KEY_REMOVIDOS) || "[]")); } catch(e) {}
const selecionados = new Set();

// Dinheiro em CENTAVOS inteiros: somar em ponto flutuante nao fecha no centavo.
function brl(centavos){ return "R$ " + ((Number(centavos)||0) / 100).toLocaleString("pt-BR",{minimumFractionDigits:2,maximumFractionDigits:2}); }
function soma(lista){ return lista.reduce((s,i)=>s+i.centavos,0); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function visiveis(){ return ITENS.filter(i => !removidos.has(i.id)); }
function toast(m){ const t=document.getElementById("toast"); t.textContent=m; t.classList.add("show"); clearTimeout(toast._h); toast._h=setTimeout(()=>t.classList.remove("show"),1600); }

function render(){
  const tb = document.getElementById("tbody"); tb.innerHTML = "";
  const vis = visiveis();
  for (const it of vis){
    const tr = document.createElement("tr"); tr.className = "row" + (selecionados.has(it.id) ? " sel" : "");
    const badge = it.metodo === "Pix" ? "b-pix" : (it.metodo === "Boleto" ? "b-bol" : "b-out");
    tr.innerHTML = `
      <td class="chk"><input type="checkbox" ${selecionados.has(it.id) ? "checked" : ""}></td>
      <td class="dados" style="white-space:nowrap;font-family:inherit;font-size:12px;color:${it.venc < HOJE ? '#b3261e' : 'inherit'}">${esc(it.venc_br)}</td>
      <td><span class="badge ${badge}">${esc(it.metodo)}</span></td>
      <td><div class="fav">${esc(it.favorecido)}</div>${it.dados ? `<div class="dados">${esc(it.dados)}</div>` : ""}</td>
      <td class="valor">${brl(it.centavos)}</td>
      <td><div class="desc">${esc(it.descricao)}</div><div class="cat">${esc(it.categoria)}</div></td>
      <td><div class="obra">${esc(it.obras)}</div><div class="item">${esc(it.cc.map(c=>c.item).filter(Boolean).join(" · "))}</div></td>
      <td class="dados">${esc(it.doc)}</td>`;
    const chk = tr.querySelector("input");
    const toggle = (v) => { if (v) selecionados.add(it.id); else selecionados.delete(it.id); tr.classList.toggle("sel", v); chk.checked = v; atualiza(); };
    chk.addEventListener("click", e => { e.stopPropagation(); toggle(chk.checked); });
    tr.addEventListener("click", () => toggle(!selecionados.has(it.id)));
    tb.appendChild(tr);
  }
  document.getElementById("empty").hidden = vis.length > 0;
  atualiza();
}
function atualiza(){
  const vis = visiveis();
  const sel = vis.filter(i => selecionados.has(i.id));
  document.getElementById("kTotal").textContent = vis.length + " pagamentos · " + brl(soma(vis));
  document.getElementById("kSel").textContent = sel.length;
  document.getElementById("kSelValor").textContent = brl(soma(sel));
  document.getElementById("btnGerar").disabled = sel.length === 0;
  document.getElementById("btnGerar").textContent = sel.length ? `Gerar PDF (${sel.length})` : "Gerar PDF";
  document.getElementById("chkAll").checked = vis.length > 0 && sel.length === vis.length;
  const br = document.getElementById("btnRestaurar");
  br.hidden = removidos.size === 0; br.textContent = `Restaurar ${removidos.size} já gerado(s)`;
}
document.getElementById("btnTodos").onclick = () => { visiveis().forEach(i => selecionados.add(i.id)); render(); };
document.getElementById("btnNenhum").onclick = () => { selecionados.clear(); render(); };
document.getElementById("chkAll").onclick = (e) => { if (e.target.checked) visiveis().forEach(i => selecionados.add(i.id)); else selecionados.clear(); render(); };
document.getElementById("btnRestaurar").onclick = () => { if (confirm("Trazer de volta para a tela todos os pagamentos já gerados em PDF?")) { removidos.clear(); try{localStorage.removeItem(KEY_REMOVIDOS);}catch(e){} render(); } };

document.getElementById("btnGerar").onclick = () => {
  const sel = visiveis().filter(i => selecionados.has(i.id));
  if (!sel.length) return;
  document.getElementById("mResumo").textContent = `${sel.length} pagamento(s), ${brl(soma(sel))}.`;
  try { document.getElementById("txtMsg").value = localStorage.getItem(KEY_MSG) || ""; } catch(e) {}
  document.getElementById("overlay").classList.add("show");
  setTimeout(() => document.getElementById("txtMsg").focus(), 50);
};
document.getElementById("btnCancelar").onclick = () => document.getElementById("overlay").classList.remove("show");
document.getElementById("overlay").addEventListener("click", e => { if (e.target.id === "overlay") document.getElementById("overlay").classList.remove("show"); });
document.getElementById("btnConfirmar").onclick = () => {
  const sel = visiveis().filter(i => selecionados.has(i.id));
  const msg = document.getElementById("txtMsg").value;
  try { localStorage.setItem(KEY_MSG, msg); } catch(e) {}
  let doc;
  try { doc = gerarPDF(sel, msg); }
  catch (e) { alert("Não consegui gerar o PDF: " + e.message + "\n(Precisa de internet para carregar a biblioteca jsPDF.)"); return; }
  const nome = `Pagamentos ${CONTA} ${INI_BR.replace(/\//g,"-")} a ${FIM_BR.replace(/\//g,"-")} (${sel.length}).pdf`;
  doc.save(nome);
  sel.forEach(i => { removidos.add(i.id); selecionados.delete(i.id); });
  try { localStorage.setItem(KEY_REMOVIDOS, JSON.stringify([...removidos])); } catch(e) {}
  document.getElementById("overlay").classList.remove("show");
  render();
  toast(`PDF gerado com ${sel.length} pagamento(s); removidos da tela.`);
};

// ===================== PDF no layout do Mais Controle =====================
// Medidas tiradas do "Relatório de Pagamentos por Vencimento" (A4 paisagem, pontos).
const L = 33.8, R = 808.5, PAGE_H = 595.28, LIM = 556;
const COLS = [33.8, 123.8, 221.2, 351.8, 474.0, 604.5, 726.8, 808.5];
const HEAD = ["Status","Valor","Favorecido","Descrição e Categoria","Condição e Conta","Centro de Custo","Pago"];
const C_TXT = [31,41,55], C_SUB = [107,114,128], C_HEAD = [39,39,39], C_TIT = [102,102,102];
const F_BAR = [242,243,247], F_BAND = [229,229,229], F_SEP = [243,244,246];
const LH9 = 13.4, LH8 = 12.0;

function gerarPDF(sel, msg){
  if (!window.jspdf || !window.jspdf.jsPDF) throw new Error("biblioteca jsPDF não carregou");
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4", compress: true });
  doc.setLineHeightFactor(1.15);
  let pagina = 0;
  const total = soma(sel);

  function txt(s, x, y, size, bold, color, opts){
    doc.setFont("helvetica", bold ? "bold" : "normal"); doc.setFontSize(size); doc.setTextColor(color[0],color[1],color[2]);
    doc.text(String(s), x, y, Object.assign({ baseline: "top" }, opts||{}));
  }
  function w(s, size, bold){ doc.setFont("helvetica", bold ? "bold" : "normal"); doc.setFontSize(size); return doc.getTextWidth(String(s)); }
  function fill(x,y,wd,h,c){ doc.setFillColor(c[0],c[1],c[2]); doc.rect(x,y,wd,h,"F"); }
  function wrap(s, width, size, bold){ doc.setFont("helvetica", bold ? "bold" : "normal"); doc.setFontSize(size); return doc.splitTextToSize(String(s||""), width); }
  function numeroPagina(){ pagina++; txt(pagina, R, 570.9, 9, false, C_TXT, { align: "right" }); }
  function cabecalhoLogo(){
    // Sem logotipo configurado, o cabeçalho sai só com o título.
    if (LOGO) { try { doc.addImage(LOGO, "PNG", 34, 31, 135, 106); } catch (e) {} }
    txt("Relatório de Pagamentos por Vencimento", 183.8, 58.1, 22.5, false, C_TIT);
    txt("Emissão:", 183.8, 95.2, 10.5, true, C_TIT);
    txt(" " + HOJE_BR, 183.8 + w("Emissão:", 10.5, true), 95.2, 10.5, false, C_TIT);
  }
  function cabecalhoRelatorio(){
    cabecalhoLogo();
    // filtros
    fill(L, 152.2, R-L, 25.6, F_BAR);
    let x = 42.8;
    const par = [["Período:", `${INI_BR} a ${FIM_BR}`], ["Status:", "Todos"], ["Conta bancária:", CONTA]];
    for (const [k,v] of par){ txt(k, x, 157.7, 9, true, C_HEAD); x += w(k,9,true) + 4; txt(v, x, 157.7, 9, false, C_HEAD); x += w(v,9,false) + 10; }
    // totais
    const boxes = [[33.8,290.2,"Pago:", brl(0)], [293.2,549.0,"Em aberto:", brl(total)], [552.0,808.5,"Total do período:", brl(total)]];
    for (const [x0,x1,k,v] of boxes){
      fill(x0, 180.8, x1-x0, 25.4, F_BAR);
      const tw = w(k,9,true) + 3 + w(v,9,false); const sx = x0 + (x1-x0-tw)/2;
      txt(k, sx, 186.2, 9, true, C_HEAD); txt(v, sx + w(k,9,true) + 3, 186.2, 9, false, C_HEAD);
    }
    return 209.2;
  }
  // faixa "Vencimento: dd/mm/aaaa" + cabeçalho da tabela (um bloco por data, como no relatório original)
  function bandaVencimento(y, vencBR){
    fill(L, y, R-L, 27, F_BAND);
    txt("Vencimento: " + vencBR, 42.8, y + 5.2, 10.5, true, C_HEAD);
    y += 27;
    fill(L, y, R-L, 31.6, F_BAR);
    HEAD.forEach((h,i) => txt(h, COLS[i] + 12, y + 8.5, 9, true, C_HEAD));
    return y + 31.6;
  }
  function statusDe(it){
    if (it.venc < HOJE) return { t: "Vencido", c: [211,47,47] };
    if (it.venc === HOJE) return { t: "Vence hoje", c: [245,158,11] };
    return { t: "A vencer", c: [37,99,235] };
  }
  // monta as linhas de cada coluna: [{s, size, sub}]
  function colunas(it){
    const wid = i => COLS[i+1] - COLS[i] - 23;
    const c1 = [{s: brl(it.centavos), size: 9}, {s: it.metodo, size: 7.9, sub: true}];
    const c2 = wrap(it.favorecido, wid(2), 9).map(s => ({s, size: 9}));
    if (it.dados) wrap("Dados: " + it.dados, wid(2), 7.9).forEach(s => c2.push({s, size: 7.9, sub: true}));
    const c3 = wrap(it.descricao, wid(3), 9).map(s => ({s, size: 9}));
    if (it.categoria) wrap(it.categoria, wid(3), 7.9).forEach(s => c3.push({s, size: 7.9, sub: true}));
    const c4 = [{s: it.condicao, size: 9}];
    wrap(it.conta, wid(4), 7.9).forEach(s => c4.push({s, size: 7.9, sub: true}));
    if (it.doc) wrap("N° Doc: " + it.doc, wid(4), 7.9).forEach(s => c4.push({s, size: 7.9, sub: true}));
    const c5 = [];
    (it.cc.length ? it.cc : [{obra: it.obras, item: ""}]).forEach(c => {
      wrap(c.obra, wid(5), 9).forEach(s => c5.push({s, size: 9}));
      if (c.item) wrap(c.item, wid(5), 7.9).forEach(s => c5.push({s, size: 7.9, sub: true}));
    });
    const c6 = [{s: "-", size: 9}];
    return [null, c1, c2, c3, c4, c5, c6];
  }
  function altura(lines){ return lines.reduce((h,l) => h + (l.size === 9 ? LH9 : LH8), 0); }

  // ---------- página 1: texto livre ----------
  cabecalhoLogo();
  const linhasMsg = wrap(msg && msg.trim() ? msg : "", R-L-20, 11);
  let y = 165;
  for (const ln of linhasMsg){
    if (y > LIM){ numeroPagina(); doc.addPage(); y = 40; }
    txt(ln, L + 10, y, 11, false, C_HEAD); y += 16;
  }
  numeroPagina();

  // ---------- relatório ----------
  doc.addPage();
  y = cabecalhoRelatorio();
  const ordenados = [...sel].sort((a,b) => a.venc < b.venc ? -1 : a.venc > b.venc ? 1 : 0);
  let vencAtual = null;
  for (const it of ordenados){
    const cols = colunas(it);
    const hMax = Math.max(...cols.slice(1).map(altura));
    const rowH = Math.max(55, hMax + 22);
    if (it.venc !== vencAtual){
      if (y + 27 + 31.6 + rowH > LIM){ numeroPagina(); doc.addPage(); y = 33.8; }
      y = bandaVencimento(y, it.venc_br);
      vencAtual = it.venc;
    }
    if (y + rowH > LIM){ numeroPagina(); doc.addPage(); y = 33.8; }
    // badge
    const st = statusDe(it);
    const bw = Math.max(41.3, w(st.t, 8.2, false) + 12);
    doc.setFillColor(st.c[0], st.c[1], st.c[2]);
    doc.roundedRect(51.7, y + rowH/2 - 7.9, bw, 15.8, 4, 4, "F");
    txt(st.t, 51.7 + bw/2, y + rowH/2 - 4.6, 8.2, false, [255,255,255], { align: "center" });
    for (let i = 1; i < 7; i++){
      const lines = cols[i]; let ty = y + (rowH - altura(lines)) / 2;
      for (const l of lines){ txt(l.s, COLS[i] + 15, ty, l.size, false, l.sub ? C_SUB : C_TXT); ty += (l.size === 9 ? LH9 : LH8); }
    }
    fill(L, y + rowH - 0.75, R-L, 0.75, F_SEP);
    y += rowH;
  }
  // linha de totais e rodapé da empresa ficam na mesma página
  if (y + 8 + 30 + 30 > LIM){ numeroPagina(); doc.addPage(); y = 33.8; }
  y += 8;
  const partes = [["Pago:", brl(0)], ["Em aberto:", brl(total)], ["Total do período:", brl(total)]];
  let tw = 0; partes.forEach(([k,v]) => { tw += w(k,10.5,true) + 4 + w(v,10.5,true) + 22; }); tw -= 22;
  let x = R - tw;
  for (const [k,v] of partes){ txt(k, x, y, 10.5, true, C_HEAD); x += w(k,10.5,true) + 4; txt(v, x, y, 10.5, true, C_HEAD); x += w(v,10.5,true) + 22; }
  y += 30;
  // rodapé da empresa: vem do arquivo de rodapé ao lado da planilha (a 1ª
  // linha em negrito). Sem o arquivo, o PDF sai sem rodapé.
  if (RODAPE.length){
    if (y + 15 * RODAPE.length + 10 > LIM){ numeroPagina(); doc.addPage(); y = 62.9; }
    RODAPE.forEach((linha, i) => txt(linha, (L+R)/2, y + 15 * i, 10.5, i === 0, C_SUB, { align: "center" }));
  }
  numeroPagina();
  return doc;
}
// exposto para teste automatizado
window.__gerarPDFBase64 = (ids, msg) => { const sel = ITENS.filter(i => ids.includes(i.id)); return gerarPDF(sel, msg).output("datauristring"); };

render();
</script>
</body>
</html>
'''

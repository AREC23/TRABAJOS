"use strict";
// ---------- utilidades ----------
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const today = () => new Date().toLocaleDateString("sv");           // AAAA-MM-DD local
const state = { tab: "resumen", month: today().slice(0, 7), ov: null, cats: [], accs: [], cards: [], settings: {} };

async function api(method, path, body) {
  const r = await fetch("/api/" + path, {
    method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "Error " + r.status);
  return j;
}
const money = n => new Intl.NumberFormat(state.settings.locale || "es-MX",
  { style: "currency", currency: state.settings.currency || "MXN" }).format(n || 0);
const cls = n => (n < 0 ? "neg" : "pos");
const monthName = ym => new Date(ym + "-15").toLocaleDateString(state.settings.locale || "es-MX", { month: "long", year: "numeric" });
const shortMonth = ym => new Date(ym + "-15").toLocaleDateString(state.settings.locale || "es-MX", { month: "short" });
const fdate = d => d ? new Date(d + "T12:00").toLocaleDateString(state.settings.locale || "es-MX", { day: "2-digit", month: "short", year: "numeric" }) : "";
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 2800); }
const opts = (list, sel, blank) => (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
  list.map(x => `<option value="${x.id}" ${String(x.id) === String(sel) ? "selected" : ""}>${esc(x.name)}</option>`).join("");
const TYPE_LABEL = { ingreso: "Ingreso", gasto: "Gasto", transferencia: "Transferencia", pago_tarjeta: "Pago de tarjeta" };
const ACC_TYPES = { efectivo: "Efectivo", banco: "Cuenta bancaria", ahorro: "Ahorro", inversion: "Inversión" };

// ---------- gráficas SVG ----------
function barChart(series) {
  const W = 520, H = 200, pad = 28, max = Math.max(1, ...series.flatMap(s => [s.income, s.expense]));
  const bw = (W - pad) / series.length;
  let g = `<line x1="${pad}" y1="${H - 24}" x2="${W}" y2="${H - 24}" stroke="currentColor" opacity=".2"/>`;
  series.forEach((s, i) => {
    const x = pad + i * bw, h1 = (s.income / max) * (H - 50), h2 = (s.expense / max) * (H - 50);
    g += `<rect x="${x + bw * .12}" y="${H - 24 - h1}" width="${bw * .36}" height="${h1}" rx="3" fill="#16a34a"><title>Ingresos ${shortMonth(s.month)}: ${money(s.income)}</title></rect>
          <rect x="${x + bw * .52}" y="${H - 24 - h2}" width="${bw * .36}" height="${h2}" rx="3" fill="#ef4444"><title>Gastos ${shortMonth(s.month)}: ${money(s.expense)}</title></rect>
          <text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${shortMonth(s.month)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%"><text x="0" y="12">${money(max)}</text>${g}</svg>
    <div class="legend"><span><i style="background:#16a34a"></i>Ingresos</span><span><i style="background:#ef4444"></i>Gastos</span></div>`;
}
function donut(items) {
  const tot = items.reduce((a, b) => a + b.total, 0);
  if (!tot) return `<p class="mut">Sin gastos este mes.</p>`;
  let a0 = -Math.PI / 2, paths = "";
  const R = 70, r = 42, cx = 80, cy = 80;
  items.forEach(it => {
    const a1 = a0 + (it.total / tot) * Math.PI * 2 - (items.length > 1 ? .01 : 0);
    const big = a1 - a0 > Math.PI ? 1 : 0, p = (R_, a) => `${cx + R_ * Math.cos(a)},${cy + R_ * Math.sin(a)}`;
    paths += items.length === 1
      ? `<circle cx="${cx}" cy="${cy}" r="${(R + r) / 2}" fill="none" stroke="${it.color}" stroke-width="${R - r}"/>`
      : `<path d="M${p(R, a0)} A${R},${R} 0 ${big} 1 ${p(R, a1)} L${p(r, a1)} A${r},${r} 0 ${big} 0 ${p(r, a0)}Z" fill="${it.color}"><title>${esc(it.name)}: ${money(it.total)}</title></path>`;
    a0 += (it.total / tot) * Math.PI * 2;
  });
  return `<div class="row"><svg viewBox="0 0 160 160" width="160">${paths}</svg><div class="legend sp" style="flex-direction:column">
    ${items.slice(0, 8).map(it => `<span><i style="background:${it.color}"></i>${esc(it.name)} — ${money(it.total)} (${(100 * it.total / tot).toFixed(0)}%)</span>`).join("")}</div></div>`;
}
const progress = (pct, warnAt = 80) => `<div class="bar ${pct >= 100 ? "bad" : pct >= warnAt ? "warn" : ""}"><i style="width:${Math.min(100, pct)}%"></i></div>`;

// ---------- modal ----------
function modal(html) { $("#box").innerHTML = html; $("#modal").hidden = false; return $("#box"); }
function closeModal() { $("#modal").hidden = true; }
$("#modal").addEventListener("mousedown", e => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

function form(title, fieldsHtml, onSave, extraBtns = "") {
  const b = modal(`<h3>${title}</h3><form>${fieldsHtml}<div class="btns">${extraBtns}<button type="button" id="cancel">Cancelar</button><button class="primary">Guardar</button></div></form>`);
  $("#cancel", b).onclick = closeModal;
  $("form", b).onsubmit = async e => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    try { await onSave(data); closeModal(); await refresh(); toast("Guardado ✔"); } catch (err) { toast("⚠ " + err.message); }
  };
  return b;
}
const field = (label, input) => `<label>${label}</label>${input}`;
async function del(path, msg = "¿Eliminar este registro?") {
  if (!confirm(msg)) return;
  try { await api("DELETE", path); await refresh(); toast("Eliminado"); } catch (e) { toast("⚠ " + e.message); }
}

// ---------- formulario de movimiento ----------
function txForm(tx = {}) {
  let type = tx.type || "gasto";
  const catsOf = k => state.cats.filter(c => c.kind === k);
  const accs = state.accs.filter(a => !a.archived || a.id === tx.account_id);
  const cards = state.cards.filter(k => !k.archived || k.id === tx.card_id);
  const useCard = !!tx.card_id;
  const b = form(tx.id ? "Editar movimiento" : "Nuevo movimiento", `
    <div class="seg" id="seg">${Object.entries(TYPE_LABEL).map(([k, v]) => `<button type="button" data-t="${k}">${v}</button>`).join("")}</div>
    ${field("Monto", `<input name="amount" type="number" step="0.01" min="0.01" required value="${tx.amount ?? ""}" autofocus>`)}
    ${field("Fecha", `<input name="date" type="date" required value="${tx.date || today()}">`)}
    <div id="f_src"></div>
    <div id="f_cat">${field("Categoría", `<select name="category_id" id="catsel"></select>`)}</div>
    ${field("Nota", `<input name="note" value="${esc(tx.note || "")}" maxlength="200">`)}`,
    async d => {
      const body = { type, amount: d.amount, date: d.date, note: d.note, category_id: null, account_id: null, card_id: null, to_account_id: null, installments: 1 };
      if (type === "gasto" || type === "ingreso") body.category_id = d.category_id || null;
      if (type === "gasto" && d.src === "card") { body.card_id = d.card_id; body.installments = d.installments || 1; }
      else if (d.account_id) body.account_id = d.account_id;
      if (type === "transferencia") body.to_account_id = d.to_account_id;
      if (type === "pago_tarjeta") body.card_id = d.card_id;
      tx.id ? await api("PUT", "transactions/" + tx.id, body) : await api("POST", "transactions", body);
    }, tx.id ? `<button type="button" class="danger" id="deltx">Eliminar</button><span class="sp"></span>` : "");
  const render = () => {
    b.querySelectorAll("#seg button").forEach(x => x.classList.toggle("on", x.dataset.t === type));
    $("#f_cat").hidden = !(type === "gasto" || type === "ingreso");
    $("#catsel").innerHTML = opts(catsOf(type === "ingreso" ? "ingreso" : "gasto"), tx.category_id, "— Sin categoría —");
    let h = "";
    if (type === "gasto") {
      h = field("Pagado con", `<select name="src" id="src"><option value="acc">Cuenta / efectivo</option><option value="card" ${useCard ? "selected" : ""}>Tarjeta de crédito</option></select>`) +
        `<div id="srcdet"></div>`;
    } else if (type === "ingreso") h = field("Cuenta donde entra", `<select name="account_id">${opts(accs, tx.account_id)}</select>`);
    else if (type === "transferencia") h = field("Desde la cuenta", `<select name="account_id">${opts(accs, tx.account_id)}</select>`) + field("Hacia la cuenta", `<select name="to_account_id">${opts(accs, tx.to_account_id)}</select>`);
    else h = field("Pagar desde la cuenta", `<select name="account_id">${opts(accs, tx.account_id)}</select>`) + field("Tarjeta a pagar", `<select name="card_id">${opts(cards, tx.card_id)}</select>`);
    $("#f_src").innerHTML = h;
    if (type === "gasto") {
      const upd = () => {
        $("#srcdet").innerHTML = $("#src").value === "card"
          ? field("Tarjeta", `<select name="card_id">${opts(cards, tx.card_id)}</select>`) + field("Meses sin intereses (1 = pago único)", `<input name="installments" type="number" min="1" max="60" value="${tx.installments || 1}">`)
          : field("Cuenta", `<select name="account_id">${opts(accs, tx.account_id)}</select>`);
      };
      $("#src").onchange = upd; upd();
    }
  };
  b.querySelectorAll("#seg button").forEach(x => x.onclick = () => { type = x.dataset.t; render(); });
  if (tx.id) $("#deltx", b).onclick = async () => { closeModal(); await del("transactions/" + tx.id); };
  render();
}

// ---------- vistas ----------
const TABS = { resumen: "📊 Resumen", movimientos: "🧾 Movimientos", cuentas: "🏦 Cuentas", tarjetas: "💳 Tarjetas", presupuestos: "🎯 Presupuestos", ahorro: "🐷 Metas de ahorro", recurrentes: "🔁 Recurrentes", ajustes: "⚙️ Ajustes" };
const NOMONTH = ["cuentas", "tarjetas", "ahorro", "recurrentes", "ajustes"];

function vResumen() {
  const o = state.ov, s = o.summary;
  const kpi = (t, v, sub, c = "") => `<div class="card kpi"><h3>${t}</h3><div class="v ${c}">${v}</div><div class="s">${sub || ""}</div></div>`;
  const topDays = Object.entries(s.daily).sort((a, b) => b[1] - a[1])[0];
  return `
  ${o.alerts.map(a => `<div class="alert ${a.level}">⚠ ${esc(a.text)}</div>`).join("")}
  <div class="grid g4">
    ${kpi("Ingresos del mes", money(s.income), "", "pos")}
    ${kpi("Gastos del mes", money(s.expense), `${money(s.card_spend)} con tarjeta`, "neg")}
    ${kpi("Balance del mes", money(s.net), `Tasa de ahorro: ${s.savings_rate.toFixed(0)}%`, cls(s.net))}
    ${kpi("Patrimonio neto", money(o.net_worth), `Cuentas ${money(o.assets)} − tarjetas ${money(o.card_debt)}`, cls(o.net_worth))}
  </div><br>
  <div class="grid g2">
    <div class="card"><h3>Ingresos vs gastos (6 meses)</h3>${barChart(o.series)}</div>
    <div class="card"><h3>Gastos por categoría</h3>${donut(s.by_category)}</div>
    <div class="card"><h3>Cuentas</h3><table>${o.accounts.filter(a => !a.archived).map(a => `<tr><td>${esc(a.name)} <span class="tag">${ACC_TYPES[a.type] || a.type}</span></td><td class="r ${cls(a.balance)}">${money(a.balance)}</td></tr>`).join("") || "<tr><td class=mut>Sin cuentas</td></tr>"}</table></div>
    <div class="card"><h3>Tarjetas de crédito</h3>${o.cards.filter(k => !k.archived).map(k => `<div style="margin-bottom:12px"><div class="row"><b class="sp">${esc(k.name)}</b><span>${money(k.debt)} / ${money(k.credit_limit)}</span></div>${progress(k.usage)}
      <div class="mut" style="font-size:13px">Pagar ${money(k.statement_balance)} antes del ${fdate(k.due_date)}</div></div>`).join("") || "<p class=mut>Sin tarjetas.</p>"}</div>
    <div class="card"><h3>Presupuestos del mes</h3>${o.budgets.map(b => `<div style="margin-bottom:10px"><div class="row"><span class="sp">${esc(b.name)}</span><span class="${b.left < 0 ? "neg" : ""}">${money(b.spent)} / ${money(b.amount)}</span></div>${progress(b.pct)}</div>`).join("") || "<p class=mut>Aún no defines presupuestos.</p>"}</div>
    <div class="card"><h3>Metas de ahorro</h3>${o.goals.map(g => `<div style="margin-bottom:10px"><div class="row"><span class="sp">${esc(g.name)}</span><span>${money(g.saved)} / ${money(g.target)}</span></div>${progress(g.pct, 101)}</div>`).join("") || "<p class=mut>Sin metas.</p>"}</div>
  </div>
  ${topDays ? `<p class="mut">Día de mayor gasto: ${fdate(topDays[0])} (${money(topDays[1])}).</p>` : ""}`;
}

let txFilters = { type: "", category_id: "", account_id: "", card_id: "", q: "" };
async function vMovimientos() {
  const qs = new URLSearchParams({ month: state.month, ...Object.fromEntries(Object.entries(txFilters).filter(([, v]) => v)) });
  const list = await api("GET", "transactions?" + qs);
  const tot = list.reduce((a, t) => (t.type === "ingreso" ? a + t.amount : t.type === "gasto" ? a - t.amount : a), 0);
  return `<div class="filters">
    <select id="f_type">${`<option value="">Todos los tipos</option>` + Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}" ${txFilters.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <select id="f_category_id">${opts(state.cats, txFilters.category_id, "Todas las categorías")}</select>
    <select id="f_account_id">${opts(state.accs, txFilters.account_id, "Todas las cuentas")}</select>
    <select id="f_card_id">${opts(state.cards, txFilters.card_id, "Todas las tarjetas")}</select>
    <input id="f_q" placeholder="Buscar en notas…" value="${esc(txFilters.q)}">
    <button id="csv">⬇ Exportar CSV</button></div>
  <div class="card"><table><tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>Cuenta / Tarjeta</th><th class="r">Monto</th></tr>
  ${list.map(t => {
    const sign = t.type === "ingreso" ? "+" : t.type === "gasto" ? "−" : "";
    const c = t.type === "ingreso" ? "pos" : t.type === "gasto" ? "neg" : "";
    const where = t.type === "transferencia" ? `${esc(t.account)} → ${esc(t.to_account)}` : t.type === "pago_tarjeta" ? `${esc(t.account)} → 💳 ${esc(t.card)}` : t.card ? `💳 ${esc(t.card)}${t.installments > 1 ? ` · ${t.installments} MSI` : ""}` : esc(t.account);
    return `<tr><td>${fdate(t.date)}</td><td><span class="tag">${TYPE_LABEL[t.type]}</span></td><td>${esc(t.category || "")} <span class="mut">${esc(t.note)}</span></td><td>${where}</td><td class="r ${c}">${sign}${money(t.amount)}</td><td class="r"><button class="sm" data-edit="${t.id}">✏️</button></td></tr>`;
  }).join("") || `<tr><td colspan="6" class="mut">No hay movimientos con estos filtros.</td></tr>`}</table>
  <p class="mut">${list.length} movimientos · Neto (ingresos − gastos): <b class="${cls(tot)}">${money(tot)}</b></p></div>`;
}
function bindMovimientos() {
  for (const k of Object.keys(txFilters)) {
    const el = $("#f_" + k); if (!el) continue;
    el.onchange = el.oninput = () => { txFilters[k] = el.value; clearTimeout(bindMovimientos.t); bindMovimientos.t = setTimeout(render, k === "q" ? 300 : 0); };
  }
  $("#csv").onclick = () => location.href = "/api/export.csv";
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = async () => {
    const all = await api("GET", "transactions"); txForm(all.find(t => t.id == b.dataset.edit));
  });
  const q = $("#f_q"); if (q && document.activeElement !== q && txFilters.q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}

function vCuentas() {
  return `<div class="row" style="margin-bottom:12px"><span class="sp"></span><button class="primary" id="newacc">+ Nueva cuenta</button></div>
  <div class="card"><table><tr><th>Cuenta</th><th>Tipo</th><th class="r">Saldo actual</th><th></th></tr>
  ${state.accs.map(a => `<tr style="${a.archived ? "opacity:.5" : ""}"><td>${esc(a.name)}</td><td>${ACC_TYPES[a.type]}</td><td class="r ${cls(a.balance)}">${money(a.balance)}</td>
  <td class="r"><button class="sm" data-acc="${a.id}">Editar</button></td></tr>`).join("")}</table>
  <p class="mut">Saldo total: <b>${money(state.ov.assets)}</b> · Ahorro e inversión: <b>${money(state.ov.savings)}</b></p></div>`;
}
function accForm(a = { type: "banco", initial_balance: 0 }) {
  const b = form(a.id ? "Editar cuenta" : "Nueva cuenta",
    field("Nombre", `<input name="name" required value="${esc(a.name || "")}">`) +
    field("Tipo", `<select name="type">${Object.entries(ACC_TYPES).map(([k, v]) => `<option value="${k}" ${a.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>`) +
    field("Saldo inicial (con el que empiezas a registrar)", `<input name="initial_balance" type="number" step="0.01" value="${a.initial_balance}">`) +
    (a.id ? field("Estado", `<select name="archived"><option value="0">Activa</option><option value="1" ${a.archived ? "selected" : ""}>Archivada (oculta en formularios)</option></select>`) : ""),
    d => a.id ? api("PUT", "accounts/" + a.id, d) : api("POST", "accounts", d),
    a.id ? `<button type="button" class="danger" id="d">Eliminar</button><span class="sp"></span>` : "");
  if (a.id) $("#d", b).onclick = () => { closeModal(); del("accounts/" + a.id); };
}
function bindCuentas() {
  $("#newacc").onclick = () => accForm();
  document.querySelectorAll("[data-acc]").forEach(b => b.onclick = () => accForm(state.accs.find(a => a.id == b.dataset.acc)));
}

function vTarjetas() {
  return `<div class="row" style="margin-bottom:12px"><span class="sp"></span><button class="primary" id="newcard">+ Nueva tarjeta</button></div>
  <div class="grid g2">${state.cards.map(k => `<div class="card" style="${k.archived ? "opacity:.5" : ""}">
    <div class="row"><h3 class="sp" style="color:var(--tx);font-size:17px">💳 ${esc(k.name)}</h3><button class="sm" data-card="${k.id}">Editar</button></div>
    <div class="row"><div class="sp"><div class="mut">Deuda total</div><div class="neg" style="font-size:22px;font-weight:700">${money(k.debt)}</div></div>
      <div class="sp"><div class="mut">Disponible</div><div style="font-size:22px;font-weight:700">${money(k.available)}</div></div></div>
    ${progress(k.usage)}<div class="mut" style="font-size:13px;margin-bottom:8px">${k.usage.toFixed(0)}% usado de ${money(k.credit_limit)}</div>
    <table>
      <tr><td>Pago para no generar intereses</td><td class="r"><b>${money(k.statement_balance)}</b></td></tr>
      <tr><td>Fecha límite de pago</td><td class="r ${k.statement_balance > 0 && k.days_to_due <= 3 ? "neg" : ""}">${fdate(k.due_date)} (${k.days_to_due} d)</td></tr>
      <tr><td>Último corte / próximo corte</td><td class="r">${fdate(k.last_cut)} / ${fdate(k.next_cut)}</td></tr>
      <tr><td>Gastado en el ciclo actual</td><td class="r">${money(k.cycle_spend)}</td></tr>
      <tr><td>Mensualidades sin intereses al mes</td><td class="r">${money(k.msi_monthly)}</td></tr></table>
    ${k.msi.length ? `<h3 style="margin-top:12px">Compras a meses sin intereses</h3><table>${k.msi.map(m => `<tr><td>${esc(m.note || "Compra")}</td><td class="r">${money(m.monthly)} × ${m.remaining} restantes</td></tr>`).join("")}</table>` : ""}
    <div class="row" style="margin-top:12px"><button data-pay="${k.id}">Pagar tarjeta</button></div></div>`).join("") || `<div class="card mut">Agrega tu primera tarjeta de crédito.</div>`}</div>
  <h3 style="margin-top:20px">Mensualidades comprometidas (próximos meses)</h3>
  <div class="card"><div class="row">${state.ov.msi_commitments.map(c => `<div class="sp"><div class="mut">${monthName(c.month)}</div><b>${money(c.total)}</b></div>`).join("")}</div></div>`;
}
function cardForm(k = { cut_day: 1, pay_day: 20, credit_limit: 0, initial_debt: 0 }) {
  const b = form(k.id ? "Editar tarjeta" : "Nueva tarjeta",
    field("Nombre (ej. BBVA Oro)", `<input name="name" required value="${esc(k.name || "")}">`) +
    field("Límite de crédito", `<input name="credit_limit" type="number" step="0.01" value="${k.credit_limit}">`) +
    field("Día de corte (1-31)", `<input name="cut_day" type="number" min="1" max="31" value="${k.cut_day}">`) +
    field("Día límite de pago (1-31)", `<input name="pay_day" type="number" min="1" max="31" value="${k.pay_day}">`) +
    field("Deuda actual al empezar a registrar", `<input name="initial_debt" type="number" step="0.01" value="${k.initial_debt}">`) +
    (k.id ? field("Estado", `<select name="archived"><option value="0">Activa</option><option value="1" ${k.archived ? "selected" : ""}>Archivada</option></select>`) : ""),
    d => k.id ? api("PUT", "cards/" + k.id, d) : api("POST", "cards", d),
    k.id ? `<button type="button" class="danger" id="d">Eliminar</button><span class="sp"></span>` : "");
  if (k.id) $("#d", b).onclick = () => { closeModal(); del("cards/" + k.id); };
}
function bindTarjetas() {
  $("#newcard").onclick = () => cardForm();
  document.querySelectorAll("[data-card]").forEach(b => b.onclick = () => cardForm(state.cards.find(k => k.id == b.dataset.card)));
  document.querySelectorAll("[data-pay]").forEach(b => b.onclick = () => {
    const k = state.cards.find(x => x.id == b.dataset.pay);
    txForm({ type: "pago_tarjeta", card_id: k.id, amount: k.statement_balance || "" });
  });
}

function vPresupuestos() {
  const bs = state.ov.budgets, tot = bs.reduce((a, b) => a + b.amount, 0), sp = bs.reduce((a, b) => a + b.spent, 0);
  return `<div class="row" style="margin-bottom:12px"><span class="mut sp">Presupuesto mensual vs gasto real de ${monthName(state.month)}. Total: ${money(sp)} de ${money(tot)}</span><button class="primary" id="newbud">+ Presupuesto</button></div>
  <div class="card">${bs.map(b => `<div style="margin-bottom:14px"><div class="row"><b class="sp">${esc(b.name)}</b><span class="${b.left < 0 ? "neg" : "pos"}">${b.left < 0 ? "Excedido por " : "Quedan "}${money(Math.abs(b.left))}</span>
    <button class="sm" data-bud="${b.id}">✏️</button></div>${progress(b.pct)}<div class="mut" style="font-size:13px">${money(b.spent)} de ${money(b.amount)} (${b.pct.toFixed(0)}%)</div></div>`).join("") || `<p class="mut">Define cuánto quieres gastar al mes por categoría.</p>`}</div>`;
}
function budForm(b) {
  const used = new Set(state.ov.budgets.map(x => x.category_id));
  const avail = state.cats.filter(c => c.kind === "gasto" && (!used.has(c.id) || (b && b.category_id === c.id)));
  const bx = form(b ? "Editar presupuesto" : "Nuevo presupuesto",
    field("Categoría", `<select name="category_id" ${b ? "disabled" : ""}>${opts(avail, b?.category_id)}</select>`) +
    field("Monto mensual", `<input name="amount" type="number" min="1" step="0.01" required value="${b?.amount ?? ""}">`),
    d => b ? api("PUT", "budgets/" + b.id, { amount: d.amount }) : api("POST", "budgets", d),
    b ? `<button type="button" class="danger" id="d">Quitar</button><span class="sp"></span>` : "");
  if (b) $("#d", bx).onclick = () => { closeModal(); del("budgets/" + b.id, "¿Quitar este presupuesto?"); };
}
function bindPresupuestos() {
  $("#newbud").onclick = () => budForm();
  document.querySelectorAll("[data-bud]").forEach(b => b.onclick = () => budForm(state.ov.budgets.find(x => x.id == b.dataset.bud)));
}

function vAhorro() {
  return `<div class="row" style="margin-bottom:12px"><span class="mut sp">Aparta dinero para objetivos (viaje, fondo de emergencia, auto…).</span><button class="primary" id="newgoal">+ Nueva meta</button></div>
  <div class="grid g2">${state.ov.goals.map(g => `<div class="card"><div class="row"><h3 class="sp" style="color:var(--tx);font-size:17px">🎯 ${esc(g.name)}</h3><button class="sm" data-goal="${g.id}">Editar</button></div>
    <div style="font-size:22px;font-weight:700">${money(g.saved)} <span class="mut" style="font-size:14px">de ${money(g.target)}</span></div>${progress(g.pct, 101)}
    <p class="mut">${g.pct.toFixed(0)}% · Faltan ${money(g.missing)}${g.deadline ? ` · Meta: ${fdate(g.deadline)}` : ""}${g.monthly_needed != null && g.missing > 0 ? `<br>Necesitas ahorrar <b>${money(g.monthly_needed)}</b> al mes` : ""}</p>
    <div class="row"><button class="primary sm" data-dep="${g.id}">+ Aportar</button><button class="sm" data-hist="${g.id}">Historial</button></div></div>`).join("") || `<div class="card mut">Crea tu primera meta de ahorro.</div>`}</div>`;
}
function goalForm(g) {
  const b = form(g ? "Editar meta" : "Nueva meta",
    field("Nombre", `<input name="name" required value="${esc(g?.name || "")}">`) +
    field("Monto objetivo", `<input name="target" type="number" min="1" step="0.01" required value="${g?.target ?? ""}">`) +
    field("Fecha límite (opcional)", `<input name="deadline" type="date" value="${g?.deadline || ""}">`),
    d => g ? api("PUT", "goals/" + g.id, d) : api("POST", "goals", d),
    g ? `<button type="button" class="danger" id="d">Eliminar</button><span class="sp"></span>` : "");
  if (g) $("#d", b).onclick = () => { closeModal(); del("goals/" + g.id, "¿Eliminar la meta y todas sus aportaciones?"); };
}
async function depForm(goalId) {
  form("Aportar a la meta", field("Monto (usa negativo no permitido; para retirar, elimina la aportación)", `<input name="amount" type="number" min="0.01" step="0.01" required autofocus>`) +
    field("Fecha", `<input name="date" type="date" value="${today()}" required>`) + field("Nota", `<input name="note">`),
    d => api("POST", "goal_deposits", { ...d, goal_id: goalId }));
}
async function histModal(goalId) {
  const deps = (await api("GET", "goal_deposits")).filter(d => d.goal_id == goalId);
  const b = modal(`<h3>Aportaciones</h3><table>${deps.map(d => `<tr><td>${fdate(d.date)}</td><td>${esc(d.note)}</td><td class="r">${money(d.amount)}</td><td><button class="sm danger" data-d="${d.id}">✕</button></td></tr>`).join("") || "<tr><td class=mut>Sin aportaciones</td></tr>"}</table><div class="btns"><button id="x">Cerrar</button></div>`);
  $("#x", b).onclick = closeModal;
  b.querySelectorAll("[data-d]").forEach(x => x.onclick = async () => { closeModal(); await del("goal_deposits/" + x.dataset.d, "¿Eliminar esta aportación?"); });
}
function bindAhorro() {
  $("#newgoal").onclick = () => goalForm();
  document.querySelectorAll("[data-goal]").forEach(b => b.onclick = () => goalForm(state.ov.goals.find(g => g.id == b.dataset.goal)));
  document.querySelectorAll("[data-dep]").forEach(b => b.onclick = () => depForm(+b.dataset.dep));
  document.querySelectorAll("[data-hist]").forEach(b => b.onclick = () => histModal(+b.dataset.hist));
}

async function vRecurrentes() {
  state.rec = await api("GET", "recurring");
  const nm = (l, id) => l.find(x => x.id === id)?.name || "";
  return `<div class="row" style="margin-bottom:12px"><span class="mut sp">Sueldo, renta, suscripciones… se registran solos cada mes en su día.</span><button class="primary" id="newrec">+ Nuevo recurrente</button></div>
  <div class="card"><table><tr><th>Nombre</th><th>Tipo</th><th>Día</th><th>Cuenta / Tarjeta</th><th class="r">Monto</th><th></th></tr>
  ${state.rec.map(r => `<tr style="${r.active ? "" : "opacity:.5"}"><td>${esc(r.name)}</td><td><span class="tag">${TYPE_LABEL[r.type]}</span></td><td>${r.day}</td>
    <td>${r.card_id ? "💳 " + esc(nm(state.cards, r.card_id)) : esc(nm(state.accs, r.account_id))}</td>
    <td class="r ${r.type === "ingreso" ? "pos" : "neg"}">${money(r.amount)}</td><td class="r"><button class="sm" data-rec="${r.id}">Editar</button></td></tr>`).join("") || `<tr><td class="mut">Sin recurrentes.</td></tr>`}</table></div>`;
}
function recForm(r = { type: "gasto", day: +today().slice(8), start_date: today(), active: 1 }) {
  let type = r.type;
  const accs = state.accs.filter(a => !a.archived), cards = state.cards.filter(k => !k.archived);
  const b = form(r.id ? "Editar recurrente" : "Nuevo recurrente",
    `<div class="seg" id="seg"><button type="button" data-t="gasto">Gasto</button><button type="button" data-t="ingreso">Ingreso</button></div>` +
    field("Nombre", `<input name="name" required value="${esc(r.name || "")}">`) +
    field("Monto", `<input name="amount" type="number" step="0.01" min="0.01" required value="${r.amount ?? ""}">`) +
    field("Día del mes", `<input name="day" type="number" min="1" max="31" value="${r.day}">`) +
    field("Empieza el", `<input name="start_date" type="date" value="${r.start_date}">`) +
    `<div id="rcat"></div>` +
    field("Cuenta o tarjeta", `<select name="target" id="rtarget">${opts(accs, r.account_id).replace(/value="(\d+)"/g, 'value="a$1"')}${type === "gasto" ? "" : ""}${cards.map(k => `<option value="c${k.id}" ${r.card_id === k.id ? "selected" : ""}>💳 ${esc(k.name)}</option>`).join("")}</select>`) +
    field("Estado", `<select name="active"><option value="1">Activo</option><option value="0" ${r.active ? "" : "selected"}>Pausado</option></select>`),
    d => {
      const body = { type, name: d.name, amount: d.amount, day: d.day, start_date: d.start_date, active: d.active, category_id: d.category_id || null, account_id: null, card_id: null };
      if (d.target.startsWith("c") && type === "gasto") body.card_id = d.target.slice(1); else if (d.target.startsWith("a")) body.account_id = d.target.slice(1);
      else throw new Error("Los ingresos deben entrar a una cuenta");
      return r.id ? api("PUT", "recurring/" + r.id, body) : api("POST", "recurring", body);
    }, r.id ? `<button type="button" class="danger" id="d">Eliminar</button><span class="sp"></span>` : "");
  const render = () => {
    b.querySelectorAll("#seg button").forEach(x => x.classList.toggle("on", x.dataset.t === type));
    $("#rcat").innerHTML = field("Categoría", `<select name="category_id">${opts(state.cats.filter(c => c.kind === type), r.category_id, "— Sin categoría —")}</select>`);
  };
  b.querySelectorAll("#seg button").forEach(x => x.onclick = () => { type = x.dataset.t; render(); });
  if (r.id) $("#d", b).onclick = () => { closeModal(); del("recurring/" + r.id, "¿Eliminar? Los movimientos ya generados se conservan."); };
  render();
}
function bindRecurrentes() {
  $("#newrec").onclick = () => recForm();
  document.querySelectorAll("[data-rec]").forEach(b => b.onclick = () => recForm(state.rec.find(r => r.id == b.dataset.rec)));
}

async function vAjustes() {
  const files = ""; // los respaldos viven en la carpeta backups/
  return `<div class="grid g2">
  <div class="card"><h3>Moneda</h3><div class="row"><select id="cur" style="width:auto">${[["MXN", "es-MX", "Peso mexicano"], ["USD", "en-US", "Dólar USD"], ["COP", "es-CO", "Peso colombiano"], ["ARS", "es-AR", "Peso argentino"], ["CLP", "es-CL", "Peso chileno"], ["PEN", "es-PE", "Sol peruano"], ["EUR", "es-ES", "Euro"], ["GTQ", "es-GT", "Quetzal"], ["CRC", "es-CR", "Colón"], ["DOP", "es-DO", "Peso dominicano"], ["BOB", "es-BO", "Boliviano"], ["UYU", "es-UY", "Peso uruguayo"]].map(([c, l, n]) => `<option value="${c}|${l}" ${state.settings.currency === c ? "selected" : ""}>${n} (${c})</option>`).join("")}</select></div></div>
  <div class="card"><h3>Respaldo</h3><p>Se hace una copia automática cada día que abres el programa (se guardan las últimas 30 en la carpeta <code>backups/</code>).</p><button id="bk">Crear respaldo ahora</button> <button id="csv">⬇ Exportar movimientos a CSV</button></div>
  <div class="card"><h3>Categorías</h3><div class="row" style="margin-bottom:8px"><button class="sm primary" id="newcat">+ Nueva categoría</button></div>
    <table>${state.cats.map(c => `<tr><td><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${esc(c.color)}"></i> ${esc(c.name)}</td><td><span class="tag">${c.kind}</span></td><td class="r"><button class="sm" data-cat="${c.id}">✏️</button></td></tr>`).join("")}</table></div></div>`;
}
function catForm(c) {
  const b = form(c ? "Editar categoría" : "Nueva categoría",
    field("Nombre", `<input name="name" required value="${esc(c?.name || "")}">`) +
    field("Tipo", `<select name="kind" ${c ? "disabled" : ""}><option value="gasto" ${c?.kind === "gasto" ? "selected" : ""}>Gasto</option><option value="ingreso" ${c?.kind === "ingreso" ? "selected" : ""}>Ingreso</option></select>`) +
    field("Color", `<input name="color" type="color" value="${c?.color || "#6b7280"}">`),
    d => c ? api("PUT", "categories/" + c.id, { name: d.name, color: d.color }) : api("POST", "categories", d),
    c ? `<button type="button" class="danger" id="d">Eliminar</button><span class="sp"></span>` : "");
  if (c) $("#d", b).onclick = () => { closeModal(); del("categories/" + c.id); };
}
function bindAjustes() {
  $("#cur").onchange = async e => { const [currency, locale] = e.target.value.split("|"); await api("PUT", "settings", { currency, locale }); await refresh(); };
  $("#bk").onclick = async () => toast("Respaldo creado: " + (await api("POST", "backup", {})).file);
  $("#csv").onclick = () => location.href = "/api/export.csv";
  $("#newcat").onclick = () => catForm();
  document.querySelectorAll("[data-cat]").forEach(b => b.onclick = () => catForm(state.cats.find(c => c.id == b.dataset.cat)));
}

// ---------- ciclo principal ----------
const VIEWS = { resumen: [vResumen], movimientos: [vMovimientos, bindMovimientos], cuentas: [vCuentas, bindCuentas], tarjetas: [vTarjetas, bindTarjetas], presupuestos: [vPresupuestos, bindPresupuestos], ahorro: [vAhorro, bindAhorro], recurrentes: [vRecurrentes, bindRecurrentes], ajustes: [vAjustes, bindAjustes] };

async function refresh() {
  const [ov, cats] = await Promise.all([api("GET", "overview?month=" + state.month), api("GET", "categories")]);
  state.ov = ov; state.cats = cats; state.accs = ov.accounts; state.cards = ov.cards; state.settings = ov.settings;
  await render();
}
async function render() {
  $("#title").textContent = TABS[state.tab].replace(/^\S+\s/, "");
  $("#monthbar").style.visibility = NOMONTH.includes(state.tab) ? "hidden" : "visible";
  $("#month").value = state.month;
  $("#menu").innerHTML = Object.entries(TABS).map(([k, v]) => `<button data-t="${k}" class="${k === state.tab ? "on" : ""}">${v}</button>`).join("");
  $("#menu").querySelectorAll("button").forEach(b => b.onclick = () => { state.tab = b.dataset.t; render(); });
  const [v, bind] = VIEWS[state.tab];
  try { $("#view").innerHTML = await v(); } catch (e) { $("#view").innerHTML = `<div class="alert danger">${esc(e.message)}</div>`; return; }
  bind && bind();
}
function shiftMonth(n) { const [y, m] = state.month.split("-").map(Number); const d = new Date(y, m - 1 + n, 1); state.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; refresh(); }
$("#prev").onclick = () => shiftMonth(-1);
$("#next").onclick = () => shiftMonth(1);
$("#month").onchange = e => { if (e.target.value) { state.month = e.target.value; refresh(); } };
$("#addtx").onclick = () => txForm();
refresh().catch(e => { $("#view").innerHTML = `<div class="alert danger">No se pudo conectar con el servidor: ${esc(e.message)}</div>`; });

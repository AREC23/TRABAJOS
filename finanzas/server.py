#!/usr/bin/env python3
"""Finanzas personales - servidor local (solo Python estándar + SQLite).

Escucha únicamente en 127.0.0.1: nadie fuera de tu PC puede acceder.
Los datos viven en data/finanzas.db.
"""
import calendar
import csv
import io
import json
import mimetypes
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
BACKUPS = os.path.join(BASE, "backups")
STATIC = os.path.join(BASE, "static")
DB_PATH = os.path.join(DATA, "finanzas.db")
HOST, PORT = "127.0.0.1", int(os.environ.get("FINANZAS_PORT", "8765"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'banco',
  initial_balance REAL NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, credit_limit REAL NOT NULL DEFAULT 0,
  cut_day INTEGER NOT NULL DEFAULT 1, pay_day INTEGER NOT NULL DEFAULT 20,
  initial_debt REAL NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, color TEXT DEFAULT '#6b7280');
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, type TEXT NOT NULL, amount REAL NOT NULL,
  category_id INTEGER, account_id INTEGER, card_id INTEGER, to_account_id INTEGER,
  installments INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '', recurring_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);
CREATE TABLE IF NOT EXISTS recurring(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, amount REAL NOT NULL,
  category_id INTEGER, account_id INTEGER, card_id INTEGER, day INTEGER NOT NULL DEFAULT 1,
  start_date TEXT NOT NULL, last_run TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL UNIQUE, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS goals(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, target REAL NOT NULL, deadline TEXT, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS goal_deposits(
  id INTEGER PRIMARY KEY, goal_id INTEGER NOT NULL, date TEXT NOT NULL, amount REAL NOT NULL, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_CATS = {
    "gasto": [("Alimentos y restaurantes", "#f97316"), ("Supermercado", "#84cc16"),
              ("Transporte", "#0ea5e9"), ("Vivienda / Renta", "#8b5cf6"), ("Servicios (luz, agua, internet)", "#14b8a6"),
              ("Salud", "#ef4444"), ("Educación", "#6366f1"), ("Entretenimiento", "#ec4899"),
              ("Ropa y calzado", "#d946ef"), ("Suscripciones", "#f59e0b"), ("Mascotas", "#a16207"),
              ("Regalos", "#fb7185"), ("Viajes", "#06b6d4"), ("Intereses y comisiones", "#64748b"),
              ("Otros gastos", "#6b7280")],
    "ingreso": [("Salario", "#16a34a"), ("Negocio / Freelance", "#22c55e"), ("Inversiones", "#10b981"),
                ("Regalos recibidos", "#4ade80"), ("Otros ingresos", "#65a30d")],
}

# tabla -> columnas editables
FIELDS = {
    "accounts": ["name", "type", "initial_balance", "archived"],
    "cards": ["name", "credit_limit", "cut_day", "pay_day", "initial_debt", "archived"],
    "categories": ["name", "kind", "color"],
    "transactions": ["date", "type", "amount", "category_id", "account_id", "card_id",
                     "to_account_id", "installments", "note"],
    "recurring": ["name", "type", "amount", "category_id", "account_id", "card_id", "day",
                  "start_date", "active"],
    "budgets": ["category_id", "amount"],
    "goals": ["name", "target", "deadline", "note"],
    "goal_deposits": ["goal_id", "date", "amount", "note"],
}
REQUIRED = {
    "accounts": ["name"], "cards": ["name"], "categories": ["name", "kind"],
    "transactions": ["date", "type", "amount"], "recurring": ["name", "type", "amount", "start_date"],
    "budgets": ["category_id", "amount"], "goals": ["name", "target"],
    "goal_deposits": ["goal_id", "date", "amount"],
}
# (tabla, columna) que referencian a esta tabla: impiden borrar si hay uso
USED_BY = {
    "accounts": [("transactions", "account_id"), ("transactions", "to_account_id"), ("recurring", "account_id")],
    "cards": [("transactions", "card_id"), ("recurring", "card_id")],
    "categories": [("transactions", "category_id"), ("recurring", "category_id"), ("budgets", "category_id")],
}
TX_TYPES = {"ingreso", "gasto", "transferencia", "pago_tarjeta"}


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def connect():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    os.makedirs(DATA, exist_ok=True)
    c = connect()
    c.executescript(SCHEMA)
    if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        for kind, items in DEFAULT_CATS.items():
            c.executemany("INSERT INTO categories(name,kind,color) VALUES(?,?,?)",
                          [(n, kind, col) for n, col in items])
        c.execute("INSERT INTO accounts(name,type,initial_balance) VALUES('Efectivo','efectivo',0)")
        for k, v in {"currency": "MXN", "locale": "es-MX"}.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))
    c.commit()
    c.close()


def backup(reason="manual"):
    os.makedirs(BACKUPS, exist_ok=True)
    name = f"finanzas-{datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
    src, dst = connect(), sqlite3.connect(os.path.join(BACKUPS, name))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    files = sorted(f for f in os.listdir(BACKUPS) if f.endswith(".db"))
    for f in files[:-30]:  # conserva los últimos 30
        os.remove(os.path.join(BACKUPS, f))
    return name


def auto_backup():
    os.makedirs(BACKUPS, exist_ok=True)
    today = f"{date.today():%Y%m%d}"
    if os.path.exists(DB_PATH) and not any(f.startswith(f"finanzas-{today}") for f in os.listdir(BACKUPS)):
        backup("auto")


# ---------- fechas ----------
def clamp_day(y, m, d):
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def add_months(y, m, n):
    t = y * 12 + (m - 1) + n
    return t // 12, t % 12 + 1


def month_range(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


# ---------- validación ----------
def clean(table, data, c, partial=False):
    out = {}
    for f in FIELDS[table]:
        if f in data:
            out[f] = data[f]
    if not partial:
        for f in REQUIRED[table]:
            if out.get(f) in (None, ""):
                raise ApiError(f"Falta el campo '{f}'")
    for f, v in list(out.items()):
        if v == "":
            out[f] = None
        if f in ("amount", "target", "initial_balance", "credit_limit", "initial_debt") and out[f] is not None:
            try:
                out[f] = round(float(out[f]), 2)
            except (TypeError, ValueError):
                raise ApiError(f"'{f}' debe ser un número")
        if f in ("cut_day", "pay_day", "day", "installments", "archived", "active") and out[f] is not None:
            try:
                out[f] = int(out[f])
            except (TypeError, ValueError):
                raise ApiError(f"'{f}' debe ser un entero")
        if f in ("date", "start_date") and not valid_date(out[f]):
            raise ApiError("Fecha inválida (use AAAA-MM-DD)")
    if table == "transactions" or table == "recurring":
        t = out.get("type")
        if t is not None and t not in (TX_TYPES if table == "transactions" else {"ingreso", "gasto"}):
            raise ApiError("Tipo inválido")
        if "amount" in out and (out["amount"] is None or out["amount"] <= 0):
            raise ApiError("El monto debe ser mayor que 0")
        if not partial:
            acc, card, to = out.get("account_id"), out.get("card_id"), out.get("to_account_id")
            if t == "ingreso" and not acc:
                raise ApiError("Elige la cuenta donde entra el ingreso")
            if t == "gasto" and not (acc or card):
                raise ApiError("Elige la cuenta o la tarjeta del gasto")
            if t == "gasto" and acc and card:
                raise ApiError("Un gasto usa cuenta O tarjeta, no ambas")
            if table == "transactions":
                if t == "transferencia":
                    if not (acc and to) or acc == to:
                        raise ApiError("Elige cuenta origen y destino distintas")
                if t == "pago_tarjeta" and not (acc and card):
                    raise ApiError("Elige la cuenta de origen y la tarjeta a pagar")
                if t != "gasto" or not card:
                    out["installments"] = 1
                out["installments"] = max(1, out.get("installments") or 1)
            if table == "recurring":
                out["day"] = min(31, max(1, out.get("day") or 1))
    if table == "cards":
        for f in ("cut_day", "pay_day"):
            if f in out and not (1 <= (out[f] or 0) <= 31):
                raise ApiError("Los días de corte y pago deben estar entre 1 y 31")
    if table == "categories" and "kind" in out and out["kind"] not in ("gasto", "ingreso"):
        raise ApiError("Tipo de categoría inválido")
    for ref, tbl in (("account_id", "accounts"), ("to_account_id", "accounts"), ("card_id", "cards"),
                     ("category_id", "categories"), ("goal_id", "goals")):
        if out.get(ref) is not None and not c.execute(f"SELECT 1 FROM {tbl} WHERE id=?", (out[ref],)).fetchone():
            raise ApiError(f"Referencia inválida: {ref}")
    return out


# ---------- recurrentes ----------
def run_recurring(c):
    today = date.today()
    for r in c.execute("SELECT * FROM recurring WHERE active=1").fetchall():
        sy, sm = int(r["start_date"][:4]), int(r["start_date"][5:7])
        if r["last_run"]:
            sy, sm = add_months(int(r["last_run"][:4]), int(r["last_run"][5:7]), 1)
        y, m, last = sy, sm, r["last_run"]
        while (y, m) <= (today.year, today.month):
            d = clamp_day(y, m, r["day"])
            if d > today:
                break
            if f"{d:%Y-%m-%d}" >= r["start_date"]:
                c.execute("INSERT INTO transactions(date,type,amount,category_id,account_id,card_id,note,recurring_id)"
                          " VALUES(?,?,?,?,?,?,?,?)",
                          (f"{d:%Y-%m-%d}", r["type"], r["amount"], r["category_id"], r["account_id"],
                           r["card_id"], r["name"] + " (recurrente)", r["id"]))
            last = f"{y:04d}-{m:02d}"
            y, m = add_months(y, m, 1)
        if last != r["last_run"]:
            c.execute("UPDATE recurring SET last_run=? WHERE id=?", (last, r["id"]))
    c.commit()


# ---------- cálculos ----------
def r2(x):
    return round(x or 0, 2)


def account_balances(c, upto=None):
    cond, args = ("AND date<=?", (upto,)) if upto else ("", ())
    out = []
    for a in c.execute("SELECT * FROM accounts ORDER BY archived, name").fetchall():
        i = a["id"]
        def s(sql):
            return c.execute(sql + " " + cond, (i,) + args).fetchone()[0] or 0
        bal = (a["initial_balance"]
               + s("SELECT SUM(amount) FROM transactions WHERE type='ingreso' AND account_id=?")
               - s("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND account_id=?")
               - s("SELECT SUM(amount) FROM transactions WHERE type='transferencia' AND account_id=?")
               + s("SELECT SUM(amount) FROM transactions WHERE type='transferencia' AND to_account_id=?")
               - s("SELECT SUM(amount) FROM transactions WHERE type='pago_tarjeta' AND account_id=?"))
        out.append({**dict(a), "balance": r2(bal)})
    return out


def card_status(c, today=None):
    today = today or date.today()
    out = []
    for k in c.execute("SELECT * FROM cards ORDER BY archived, name").fetchall():
        i = k["id"]
        q = lambda sql, *a: c.execute(sql, (i,) + a).fetchone()[0] or 0
        charges = q("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND card_id=?")
        pays = q("SELECT SUM(amount) FROM transactions WHERE type='pago_tarjeta' AND card_id=?")
        debt = k["initial_debt"] + charges - pays
        # último corte y próxima fecha límite de pago
        cut = clamp_day(today.year, today.month, k["cut_day"])
        if cut > today:
            py, pm = add_months(today.year, today.month, -1)
            cut = clamp_day(py, pm, k["cut_day"])
        ny, nm = add_months(cut.year, cut.month, 1)
        next_cut = clamp_day(ny, nm, k["cut_day"])
        due = clamp_day(cut.year, cut.month, k["pay_day"])
        if k["pay_day"] <= k["cut_day"]:
            dy, dm = add_months(cut.year, cut.month, 1)
            due = clamp_day(dy, dm, k["pay_day"])
        cut_s = f"{cut:%Y-%m-%d}"
        stmt = (k["initial_debt"] + q("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND card_id=? AND date<=?", cut_s)
                - pays)
        cycle = q("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND card_id=? AND date>?", cut_s)
        # mensualidades sin intereses vigentes
        msi = []
        for t in c.execute("SELECT * FROM transactions WHERE type='gasto' AND card_id=? AND installments>1", (i,)):
            ty, tm = int(t["date"][:4]), int(t["date"][5:7])
            elapsed = (today.year - ty) * 12 + today.month - tm
            left = t["installments"] - elapsed
            if left > 0:
                msi.append({"id": t["id"], "note": t["note"], "total": t["amount"],
                            "monthly": r2(t["amount"] / t["installments"]),
                            "installments": t["installments"], "remaining": left})
        limit = k["credit_limit"]
        out.append({**dict(k), "debt": r2(debt), "available": r2(limit - debt),
                    "usage": r2(100 * debt / limit) if limit else 0,
                    "last_cut": cut_s, "next_cut": f"{next_cut:%Y-%m-%d}",
                    "due_date": f"{due:%Y-%m-%d}", "days_to_due": (due - today).days,
                    "statement_balance": r2(max(0, min(stmt, debt))), "cycle_spend": r2(cycle), "msi": msi,
                    "msi_monthly": r2(sum(m["monthly"] for m in msi))})
    return out


def month_summary(c, ym):
    a, b = month_range(ym)
    q = lambda sql, *args: c.execute(sql, args).fetchall()
    inc = q("SELECT SUM(amount) FROM transactions WHERE type='ingreso' AND date BETWEEN ? AND ?", a, b)[0][0] or 0
    exp = q("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND date BETWEEN ? AND ?", a, b)[0][0] or 0
    by_cat = [dict(r) for r in q(
        "SELECT COALESCE(c.name,'Sin categoría') name, COALESCE(c.color,'#9ca3af') color, c.id category_id, "
        "SUM(t.amount) total FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE t.type='gasto' AND t.date BETWEEN ? AND ? GROUP BY c.id ORDER BY total DESC", a, b)]
    by_card = q("SELECT SUM(amount) FROM transactions WHERE type='gasto' AND card_id IS NOT NULL AND date BETWEEN ? AND ?",
                a, b)[0][0] or 0
    inc_cat = [dict(r) for r in q(
        "SELECT COALESCE(c.name,'Sin categoría') name, COALESCE(c.color,'#9ca3af') color, SUM(t.amount) total "
        "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE t.type='ingreso' AND t.date BETWEEN ? AND ? GROUP BY c.id ORDER BY total DESC", a, b)]
    daily = {r["date"]: r["total"] for r in q(
        "SELECT date, SUM(amount) total FROM transactions WHERE type='gasto' AND date BETWEEN ? AND ? GROUP BY date", a, b)}
    return {"income": r2(inc), "expense": r2(exp), "net": r2(inc - exp), "card_spend": r2(by_card),
            "savings_rate": r2(100 * (inc - exp) / inc) if inc else 0,
            "by_category": [{**x, "total": r2(x["total"])} for x in by_cat],
            "income_by_category": [{**x, "total": r2(x["total"])} for x in inc_cat],
            "daily": {k: r2(v) for k, v in daily.items()}}


def budget_status(c, ym):
    a, b = month_range(ym)
    rows = c.execute(
        "SELECT b.id, b.category_id, b.amount, c.name, c.color, "
        "COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.type='gasto' AND t.category_id=b.category_id "
        "AND t.date BETWEEN ? AND ?),0) spent FROM budgets b JOIN categories c ON c.id=b.category_id ORDER BY c.name",
        (a, b)).fetchall()
    return [{**dict(r), "spent": r2(r["spent"]), "left": r2(r["amount"] - r["spent"]),
             "pct": r2(100 * r["spent"] / r["amount"]) if r["amount"] else 0} for r in rows]


def goals_status(c):
    out = []
    for g in c.execute("SELECT * FROM goals ORDER BY name").fetchall():
        saved = c.execute("SELECT SUM(amount) FROM goal_deposits WHERE goal_id=?", (g["id"],)).fetchone()[0] or 0
        item = {**dict(g), "saved": r2(saved), "pct": r2(100 * saved / g["target"]) if g["target"] else 0,
                "missing": r2(max(0, g["target"] - saved)), "monthly_needed": None}
        if g["deadline"] and valid_date(g["deadline"]):
            d = datetime.strptime(g["deadline"], "%Y-%m-%d").date()
            t = date.today()
            months = max(1, (d.year - t.year) * 12 + d.month - t.month)
            item["monthly_needed"] = r2(item["missing"] / months) if d >= t else None
        out.append(item)
    return out


def overview(c, ym):
    run_recurring(c)
    y, m = int(ym[:4]), int(ym[5:7])
    series = []
    for n in range(-5, 1):
        yy, mm = add_months(y, m, n)
        s = month_summary(c, f"{yy:04d}-{mm:02d}")
        series.append({"month": f"{yy:04d}-{mm:02d}", "income": s["income"], "expense": s["expense"]})
    accounts = account_balances(c)
    cards = card_status(c)
    active_acc = [a for a in accounts if not a["archived"]]
    assets = sum(a["balance"] for a in accounts)
    debt = sum(k["debt"] for k in cards)
    savings = sum(a["balance"] for a in accounts if a["type"] in ("ahorro", "inversion"))
    budgets = budget_status(c, ym)
    alerts = []
    for k in cards:
        if not k["archived"] and k["statement_balance"] > 0 and k["days_to_due"] <= 7:
            alerts.append({"level": "danger" if k["days_to_due"] <= 2 else "warn",
                           "text": f"Tarjeta {k['name']}: pagar {k['statement_balance']:.2f} antes del "
                                   f"{k['due_date']} ({k['days_to_due']} días)"})
        if not k["archived"] and k["usage"] >= 80:
            alerts.append({"level": "warn", "text": f"Tarjeta {k['name']} al {k['usage']:.0f}% de su límite"})
    for b in budgets:
        if b["pct"] >= 100:
            alerts.append({"level": "danger", "text": f"Presupuesto '{b['name']}' excedido ({b['pct']:.0f}%)"})
        elif b["pct"] >= 80:
            alerts.append({"level": "warn", "text": f"Presupuesto '{b['name']}' al {b['pct']:.0f}%"})
    # compromisos sin intereses próximos 6 meses
    commit = []
    for n in range(6):
        yy, mm = add_months(date.today().year, date.today().month, n)
        tot = 0
        for k in cards:
            for ms in k["msi"]:
                if ms["remaining"] > n:
                    tot += ms["monthly"]
        commit.append({"month": f"{yy:04d}-{mm:02d}", "total": r2(tot)})
    return {"month": ym, "summary": month_summary(c, ym), "series": series,
            "accounts": accounts, "cards": cards, "budgets": budgets, "goals": goals_status(c),
            "net_worth": r2(assets - debt), "assets": r2(assets), "card_debt": r2(debt), "savings": r2(savings),
            "alerts": alerts, "msi_commitments": commit,
            "settings": {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}}


def list_transactions(c, qs):
    where, args = [], []
    def p(k):
        return (qs.get(k) or [""])[0]
    if p("month"):
        a, b = month_range(p("month"))
        where.append("t.date BETWEEN ? AND ?")
        args += [a, b]
    if p("from"):
        where.append("t.date>=?"); args.append(p("from"))
    if p("to"):
        where.append("t.date<=?"); args.append(p("to"))
    if p("type"):
        where.append("t.type=?"); args.append(p("type"))
    if p("category_id"):
        where.append("t.category_id=?"); args.append(p("category_id"))
    if p("account_id"):
        where.append("(t.account_id=? OR t.to_account_id=?)"); args += [p("account_id")] * 2
    if p("card_id"):
        where.append("t.card_id=?"); args.append(p("card_id"))
    if p("q"):
        where.append("t.note LIKE ?"); args.append(f"%{p('q')}%")
    sql = ("SELECT t.*, c.name category, a.name account, k.name card, a2.name to_account "
           "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
           "LEFT JOIN accounts a ON a.id=t.account_id LEFT JOIN cards k ON k.id=t.card_id "
           "LEFT JOIN accounts a2 ON a2.id=t.to_account_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY t.date DESC, t.id DESC")
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def export_csv(c):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fecha", "tipo", "monto", "categoria", "cuenta", "tarjeta", "cuenta_destino", "meses_sin_intereses", "nota"])
    for t in list_transactions(c, {}):
        w.writerow([t["date"], t["type"], t["amount"], t["category"] or "", t["account"] or "", t["card"] or "",
                    t["to_account"] or "", t["installments"], t["note"] or ""])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM para que Excel respete acentos


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "Finanzas/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        h = (self.headers.get("Host") or "").split(":")[0]
        return h in ("127.0.0.1", "localhost")

    def _handle(self, method):
        if not self._host_ok():
            return self._send(403, {"error": "Host no permitido"})
        u = urlparse(self.path)
        try:
            if u.path.startswith("/api/"):
                if method != "GET" and "application/json" not in (self.headers.get("Content-Type") or ""):
                    raise ApiError("Content-Type debe ser application/json", 415)
                body = {}
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    body = json.loads(self.rfile.read(n) or b"{}")
                c = connect()
                try:
                    res = self.api(c, method, u.path[5:].strip("/").split("/"), parse_qs(u.query), body)
                    c.commit()
                finally:
                    c.close()
                if isinstance(res, tuple):
                    return self._send(200, res[0], res[1], res[2])
                return self._send(200, res)
            if method != "GET":
                return self._send(405, {"error": "Método no permitido"})
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            full = os.path.realpath(os.path.join(STATIC, path))
            if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
                return self._send(404, {"error": "No encontrado"})
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))
        except ApiError as e:
            self._send(e.code, {"error": str(e)})
        except json.JSONDecodeError:
            self._send(400, {"error": "JSON inválido"})
        except Exception as e:  # noqa
            import traceback; traceback.print_exc()
            self._send(500, {"error": f"Error interno: {e}"})

    do_GET = lambda self: self._handle("GET")
    do_POST = lambda self: self._handle("POST")
    do_PUT = lambda self: self._handle("PUT")
    do_DELETE = lambda self: self._handle("DELETE")

    def api(self, c, method, parts, qs, body):
        res = parts[0]
        if res == "overview" and method == "GET":
            ym = (qs.get("month") or [f"{date.today():%Y-%m}"])[0]
            if len(ym) != 7 or not valid_date(ym + "-01"):
                raise ApiError("Mes inválido")
            return overview(c, ym)
        if res == "transactions" and method == "GET" and len(parts) == 1:
            return list_transactions(c, qs)
        if res == "export.csv":
            return (export_csv(c), "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="movimientos-{date.today()}.csv"'})
        if res == "backup" and method == "POST":
            return {"file": backup("manual")}
        if res == "settings":
            if method == "PUT":
                for k in ("currency", "locale"):
                    if k in body:
                        c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(body[k])[:10]))
            return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
        if res == "goal_deposits" and method == "GET":
            return [dict(r) for r in c.execute("SELECT * FROM goal_deposits ORDER BY date DESC, id DESC")]
        if res not in FIELDS:
            raise ApiError("Ruta no encontrada", 404)
        if method == "GET":
            return [dict(r) for r in c.execute(f"SELECT * FROM {res} ORDER BY id")]
        if method == "POST":
            data = clean(res, body, c)
            if res == "recurring":
                data["last_run"] = None
            cols = ",".join(data)
            cur = c.execute(f"INSERT INTO {res}({cols}) VALUES({','.join('?' * len(data))})", list(data.values()))
            if res == "recurring":
                run_recurring(c)
            return {"id": cur.lastrowid}
        if len(parts) < 2 or not parts[1].isdigit():
            raise ApiError("Falta el id")
        rid = int(parts[1])
        if not c.execute(f"SELECT 1 FROM {res} WHERE id=?", (rid,)).fetchone():
            raise ApiError("No existe", 404)
        if method == "PUT":
            if res == "transactions":
                cur_row = dict(c.execute("SELECT * FROM transactions WHERE id=?", (rid,)).fetchone())
                data = clean(res, {**cur_row, **body}, c)
                data = {k: data[k] for k in FIELDS[res]}
            else:
                data = clean(res, body, c, partial=True)
            if data:
                c.execute(f"UPDATE {res} SET {','.join(k + '=?' for k in data)} WHERE id=?", list(data.values()) + [rid])
            return {"ok": True}
        if method == "DELETE":
            for tbl, col in USED_BY.get(res, []):
                n = c.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col}=?", (rid,)).fetchone()[0]
                if n:
                    raise ApiError(f"No se puede eliminar: tiene {n} registros asociados. "
                                   "Puedes archivarla/ocultarla en su lugar." if res != "categories" else
                                   f"No se puede eliminar: la categoría se usa en {n} registros.", 409)
            if res == "goals":
                c.execute("DELETE FROM goal_deposits WHERE goal_id=?", (rid,))
            if res == "recurring":
                c.execute("UPDATE transactions SET recurring_id=NULL WHERE recurring_id=?", (rid,))
            c.execute(f"DELETE FROM {res} WHERE id=?", (rid,))
            return {"ok": True}
        raise ApiError("Método no permitido", 405)


def main():
    init_db()
    auto_backup()
    c = connect()
    run_recurring(c)
    c.close()
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"El puerto {PORT} está ocupado (¿ya está abierto el programa?). Abriendo el navegador…")
        webbrowser.open(f"http://{HOST}:{PORT}")
        return
    try:  # bot de Telegram opcional (solo si ya se configuró con bot.py --setup)
        import bot
        if bot.load_config():
            threading.Thread(target=bot.run_forever, daemon=True).start()
    except Exception as e:  # noqa
        print("Bot de Telegram no iniciado:", e)
    url = f"http://{HOST}:{PORT}"
    print(f"Finanzas personales corriendo en {url}\nPresiona Ctrl+C para cerrar.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


if __name__ == "__main__":
    main()

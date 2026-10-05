#!/usr/bin/env python3
"""Bot de Telegram para Mis Finanzas (solo librería estándar).

Corre en TU PC y consulta a Telegram por mensajes nuevos (long polling): no abre ningún
puerto. Solo obedece a los IDs de Telegram que autorices en la configuración.

  python bot.py --setup   -> configura token y autoriza tu usuario (una sola vez)
  python bot.py           -> inicia el bot (o se inicia solo junto con server.py)
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta

import server as S

CONFIG = os.path.join(S.DATA, "telegram.json")


# ---------- configuración ----------
def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if cfg.get("token") and cfg.get("allowed_ids") else None
    except (OSError, ValueError):
        return None


def save_config(cfg):
    os.makedirs(S.DATA, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


# ---------- API de Telegram ----------
def tg(token, method, **params):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=params.get("timeout", 0) + 15) as r:
        return json.load(r)["result"]


# ---------- utilidades de texto ----------
def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


def words(s):
    return re.findall(r"[a-z0-9ñ]+", norm(s))


def has_word(text_words, w):
    return w in text_words


def fmt(n, cur="$"):
    return f"{'-' if n < 0 else ''}{cur}{abs(n):,.2f}"


SYN_GASTO = {
    "alimentos": "comida restaurante taco tacos cafe desayuno cena almuerzo comer pizza hamburguesa antojo",
    "supermercado": "super mercado despensa walmart costco soriana chedraui oxxo",
    "transporte": "uber didi taxi gasolina gas camion metro transporte estacionamiento caseta pasaje",
    "vivienda": "renta hipoteca alquiler casa",
    "servicios": "luz agua internet telefono celular cfe gas natural",
    "salud": "doctor medico farmacia medicina dentista consulta hospital",
    "educacion": "escuela colegiatura curso libro universidad",
    "suscripciones": "netflix spotify disney hbo youtube prime icloud suscripcion",
    "ropa": "ropa zapatos tenis camisa pantalon",
    "mascotas": "perro gato veterinario croquetas mascota",
    "regalos": "regalo regalos",
    "viajes": "viaje hotel vuelo avion airbnb",
    "intereses": "comision interes intereses anualidad",
    "entretenimiento": "cine bar fiesta juego concierto videojuego salida",
}
SYN_INGRESO = {
    "salario": "sueldo nomina salario quincena",
    "negocio": "freelance cliente proyecto venta ventas",
    "inversiones": "dividendo rendimiento rendimientos",
}
W_INGRESO = {"ingreso", "cobre", "recibi", "deposito", "depositaron", "gane", "sueldo", "nomina", "salario",
             "quincena", "pagaron", "cobro"}
W_PAGO = {"pago", "pague", "abono", "abone", "pagar"}
SKIP = {"gaste", "gasto", "gastos", "pague", "compre", "compra", "ingreso", "cobre", "recibi", "con", "en", "de",
        "la", "el", "mi", "a", "por", "hoy", "ayer", "anteayer", "una", "un", "tarjeta", "credito", "me",
        "pagaron", "depositaron", "msi", "meses", "sin", "intereses", "cuenta"}

AYUDA = """🤖 Mis Finanzas — comandos

Registrar (escribe normal):
• gasté 250 super
• gasté 1200 gasolina con visa
• compré 6000 laptop con visa a 6 msi
• ingreso 15000 sueldo bbva
• pago tarjeta visa 1000 bbva
• añade "ayer" para otra fecha: gasté 90 tacos ayer

Consultar:
• /resumen — ingresos, gastos y balance del mes
• /saldos — saldo de tus cuentas
• /tarjetas — deuda, disponible y fecha de pago
• /presupuestos — avance de presupuestos
• /ultimos — últimos 5 movimientos
• /borrar — elimina el último movimiento que registraste aquí"""


# ---------- lógica (independiente de Telegram, fácil de probar) ----------
class Session:
    last_id = None  # último movimiento creado por el bot


def find_by_name(items, tw, n):
    for it in items:
        if any(len(t) >= 3 and t in tw and t not in SKIP for t in words(it["name"])):
            return it
    return None


def pick_category(cats, kind, tw):
    pool = [c for c in cats if c["kind"] == kind]
    for c in pool:                                   # nombre directo
        if any(len(t) >= 4 and t in tw for t in words(c["name"])):
            return c
    syn = SYN_GASTO if kind == "gasto" else SYN_INGRESO
    for prefix, keys in syn.items():                 # sinónimos
        if any(k in tw for k in keys.split()):
            for c in pool:
                if norm(c["name"]).startswith(prefix):
                    return c
    return next((c for c in pool if norm(c["name"]).startswith("otros")), None)


def parse_and_save(c, text):
    n = norm(text)
    tw = set(words(text))
    # meses sin intereses
    inst = 1
    m = re.search(r"(\d+)\s*(?:msi|meses)", n)
    if m:
        inst = int(m.group(1))
        n_amount = n[:m.start()] + " " + n[m.end():]
    else:
        n_amount = n
    am = re.search(r"\$?\s*(\d[\d,]*(?:\.\d+)?)", n_amount)
    if not am:
        return None
    amount = float(am.group(1).replace(",", ""))
    if amount <= 0:
        return "El monto debe ser mayor que 0."
    d = date.today()
    if "anteayer" in tw:
        d -= timedelta(days=2)
    elif "ayer" in tw:
        d -= timedelta(days=1)

    accs = [a for a in S.account_balances(c) if not a["archived"]]
    cards = [k for k in S.card_status(c) if not k["archived"]]
    cats = [dict(r) for r in c.execute("SELECT * FROM categories")]
    card = find_by_name(cards, tw, n)
    acc = find_by_name(accs, tw, n)
    if not acc and "efectivo" in tw:
        acc = next((a for a in accs if a["type"] == "efectivo"), None)
    if not card and ({"tarjeta", "credito"} & tw) and len(cards) == 1:
        card = cards[0]

    first = (words(text) or [""])[0]
    if card and (tw & W_PAGO) and (first in W_PAGO or "tarjeta" in tw):
        kind = "pago_tarjeta"
    elif tw & W_INGRESO:
        kind = "ingreso"
    else:
        kind = "gasto"

    note = " ".join(w for w in re.sub(r"\$?\s*\d[\d,]*(?:\.\d+)?", " ", text).split()
                    if norm(w) not in SKIP and not (card and norm(w) in words(card["name"]))
                    and not (acc and norm(w) in words(acc["name"])))
    data = {"date": f"{d:%Y-%m-%d}", "type": kind, "amount": amount, "note": note[:200].capitalize()}
    lines = []
    if kind == "pago_tarjeta":
        if not card:
            return "¿Qué tarjeta pagas? Ej: pago tarjeta visa 1000 bbva"
        acc = acc or next((a for a in accs if a["type"] == "banco"), accs[0] if accs else None)
        if not acc:
            return "Primero crea una cuenta en la app."
        data.update(card_id=card["id"], account_id=acc["id"])
        lines.append(f"💳 Pago a {card['name']} desde {acc['name']}")
    elif kind == "ingreso":
        acc = acc or (accs[0] if len(accs) == 1 else next((a for a in accs if a["type"] == "banco"), accs[0] if accs else None))
        if not acc:
            return "Primero crea una cuenta en la app."
        cat = pick_category(cats, "ingreso", tw)
        data.update(account_id=acc["id"], category_id=cat and cat["id"])
        lines.append(f"💵 Ingreso en {acc['name']} · {cat['name'] if cat else 'Sin categoría'}")
    else:
        cat = pick_category(cats, "gasto", tw)
        data["category_id"] = cat and cat["id"]
        if card:
            data.update(card_id=card["id"], installments=max(1, inst))
            where = f"💳 {card['name']}" + (f" a {inst} meses sin intereses" if inst > 1 else "")
        else:
            acc = acc or next((a for a in accs if a["type"] == "efectivo"), accs[0] if accs else None)
            if not acc:
                return "Primero crea una cuenta en la app."
            data["account_id"] = acc["id"]
            where = f"🏦 {acc['name']}"
        lines.append(f"🧾 Gasto · {cat['name'] if cat else 'Sin categoría'} · {where}")
    clean = S.clean("transactions", data, c)
    cols = ",".join(clean)
    cur = c.execute(f"INSERT INTO transactions({cols}) VALUES({','.join('?' * len(clean))})", list(clean.values()))
    Session.last_id = cur.lastrowid
    c.commit()
    head = f"✅ {fmt(amount)} registrado ({d:%d/%m})" if d != date.today() else f"✅ {fmt(amount)} registrado"
    return head + "\n" + "\n".join(lines) + (f"\n📝 {data['note']}" if data["note"] else "") + "\n(/borrar para deshacer)"


def cmd_resumen(c):
    ym = f"{date.today():%Y-%m}"
    s = S.month_summary(c, ym)
    top = ", ".join(f"{x['name']} {fmt(x['total'])}" for x in s["by_category"][:3]) or "—"
    return (f"📊 {ym}\nIngresos: {fmt(s['income'])}\nGastos: {fmt(s['expense'])} (tarjeta {fmt(s['card_spend'])})\n"
            f"Balance: {fmt(s['net'])} · Ahorro {s['savings_rate']:.0f}%\nTop gastos: {top}")


def cmd_saldos(c):
    accs = [a for a in S.account_balances(c) if not a["archived"]]
    cards = [k for k in S.card_status(c) if not k["archived"]]
    tot, debt = sum(a["balance"] for a in accs), sum(k["debt"] for k in cards)
    return ("🏦 Cuentas\n" + "\n".join(f"• {a['name']}: {fmt(a['balance'])}" for a in accs)
            + f"\n\nTotal: {fmt(tot)}\nDeuda tarjetas: {fmt(debt)}\nPatrimonio neto: {fmt(tot - debt)}")


def cmd_tarjetas(c):
    cards = [k for k in S.card_status(c) if not k["archived"]]
    if not cards:
        return "No tienes tarjetas registradas."
    return "\n\n".join(f"💳 {k['name']}\nDeuda {fmt(k['debt'])} · Disponible {fmt(k['available'])} ({k['usage']:.0f}% usado)\n"
                       f"Pagar {fmt(k['statement_balance'])} antes del {k['due_date']} ({k['days_to_due']} días)"
                       for k in cards)


def cmd_presupuestos(c):
    bs = S.budget_status(c, f"{date.today():%Y-%m}")
    if not bs:
        return "No tienes presupuestos. Créalos en la app."
    return "🎯 Presupuestos del mes\n" + "\n".join(
        f"{'🔴' if b['pct'] >= 100 else '🟡' if b['pct'] >= 80 else '🟢'} {b['name']}: {fmt(b['spent'])} / {fmt(b['amount'])} ({b['pct']:.0f}%)" for b in bs)


def cmd_ultimos(c):
    rows = S.list_transactions(c, {})[:5]
    if not rows:
        return "Aún no hay movimientos."
    sign = {"ingreso": "+", "gasto": "-"}
    return "🧾 Últimos movimientos\n" + "\n".join(
        f"{r['date'][5:]} {sign.get(r['type'], '↔')}{fmt(r['amount'])} {r['category'] or r['type']} {r['note'] or ''}".strip() for r in rows)


def cmd_borrar(c):
    if not Session.last_id:
        return "No hay nada que deshacer (solo borro lo que registraste desde Telegram en esta sesión)."
    row = c.execute("SELECT amount, note FROM transactions WHERE id=?", (Session.last_id,)).fetchone()
    c.execute("DELETE FROM transactions WHERE id=?", (Session.last_id,))
    c.commit()
    Session.last_id = None
    return f"🗑 Eliminado: {fmt(row['amount'])} {row['note'] or ''}" if row else "Ya estaba eliminado."


COMMANDS = {"resumen": cmd_resumen, "saldos": cmd_saldos, "saldo": cmd_saldos, "tarjetas": cmd_tarjetas,
            "presupuestos": cmd_presupuestos, "presupuesto": cmd_presupuestos, "ultimos": cmd_ultimos,
            "borrar": cmd_borrar, "deshacer": cmd_borrar}
QUERY_WORDS = {"resumen": "resumen", "cuanto": "resumen", "saldo": "saldos", "saldos": "saldos", "tarjetas": "tarjetas",
               "presupuestos": "presupuestos", "ultimos": "ultimos", "borrar": "borrar", "deshacer": "borrar"}


def handle(text):
    """Recibe el texto del usuario y devuelve la respuesta."""
    text = (text or "").strip()
    if not text:
        return None
    c = S.connect()
    try:
        S.run_recurring(c)
        if text.startswith("/"):
            cmd = norm(text.split()[0][1:].split("@")[0])
            if cmd in ("start", "ayuda", "help"):
                return AYUDA
            if cmd in COMMANDS:
                return COMMANDS[cmd](c)
            return "Comando desconocido. Escribe /ayuda"
        res = parse_and_save(c, text)
        if res is not None:
            return res
        for w in words(text):
            if w in QUERY_WORDS:
                return COMMANDS[QUERY_WORDS[w]](c)
        return "No entendí. Ejemplo: «gasté 250 super» o escribe /ayuda"
    except S.ApiError as e:
        return f"⚠ {e}"
    except Exception as e:  # noqa
        return f"⚠ Error: {e}"
    finally:
        c.close()


# ---------- bucle principal ----------
def run_forever(stop=None):
    cfg = load_config()
    if not cfg:
        return
    token, allowed, offset = cfg["token"], set(cfg["allowed_ids"]), None
    print("🤖 Bot de Telegram activo.")
    warned = set()
    while not (stop and stop.is_set()):
        try:
            updates = tg(token, "getUpdates", timeout=30, offset=offset, allowed_updates=["message"])
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                uid, chat = (msg.get("from") or {}).get("id"), (msg.get("chat") or {}).get("id")
                if uid not in allowed:
                    if uid not in warned:
                        warned.add(uid)
                        print(f"Bot: mensaje ignorado de usuario no autorizado (id {uid}).")
                        tg(token, "sendMessage", chat_id=chat, text="No autorizado.")
                    continue
                reply = handle(msg.get("text"))
                if reply:
                    tg(token, "sendMessage", chat_id=chat, text=reply)
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                print("Bot: token inválido; revisa data/telegram.json o ejecuta bot.py --setup")
                return
            time.sleep(5)
        except Exception:
            time.sleep(5)  # sin internet u otro fallo temporal: reintenta


def setup():
    S.init_db()
    print("1) En Telegram abre @BotFather, escribe /newbot y sigue los pasos.\n2) Pega aquí el token que te da.")
    token = input("Token: ").strip()
    try:
        me = tg(token, "getMe")
    except Exception as e:
        sys.exit(f"Token inválido o sin internet: {e}")
    print(f"\nBot: @{me['username']}. Ahora ábrelo en Telegram y escríbele cualquier mensaje (ej. hola)...")
    off = None
    while True:
        for u in tg(token, "getUpdates", timeout=20, offset=off):
            off = u["update_id"] + 1
            m = u.get("message")
            if not m:
                continue
            f = m["from"]
            ok = input(f"Mensaje de {f.get('first_name', '')} (@{f.get('username', '-')}, id {f['id']}). ¿Es tu cuenta? [s/N]: ")
            if ok.lower().startswith("s"):
                save_config({"token": token, "allowed_ids": [f["id"]]})
                tg(token, "sendMessage", chat_id=m["chat"]["id"], text="✅ Listo. Escribe /ayuda para ver los comandos.")
                print("Configurado. Reinicia iniciar.bat (o ejecuta python bot.py).")
                return
            print("Ignorado. Esperando otro mensaje…")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup()
    else:
        S.init_db()
        if not load_config():
            sys.exit("Aún no está configurado. Ejecuta: python bot.py --setup")
        try:
            run_forever()
        except KeyboardInterrupt:
            pass

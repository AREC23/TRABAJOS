# 💰 Mis Finanzas (sistema personal, 100% local)

Controla ingresos, gastos, cuentas, tarjetas de crédito, presupuestos, ahorro y pagos recurrentes.
Todo se guarda en un archivo en **tu PC** (`data/finanzas.db`); el servidor solo escucha en `127.0.0.1`
(nadie en tu red ni en internet puede entrar) y no necesita internet ni instalar nada extra.

## Requisitos
Solo **Python 3.8+** (python.org; en Windows marca "Add Python to PATH").

## Cómo usarlo
- **Windows:** doble clic en `iniciar.bat`
- **Mac/Linux:** `./iniciar.sh`

Se abre el navegador en http://127.0.0.1:8765. Para cerrar, cierra la ventana negra (o Ctrl+C).

## Qué incluye
| Sección | Qué hace |
|---|---|
| Resumen | Ingresos, gastos, balance, tasa de ahorro, patrimonio neto, gráficas, alertas |
| Movimientos | Ingresos, gastos, transferencias entre cuentas y pagos de tarjeta; filtros, búsqueda, CSV |
| Cuentas | Efectivo, banco, ahorro, inversión con saldo calculado |
| Tarjetas | Límite, disponible, corte, fecha límite de pago, pago para no generar intereses, meses sin intereses |
| Presupuestos | Límite mensual por categoría con barras de avance y alertas al 80 % / 100 % |
| Metas de ahorro | Objetivos con aportaciones y cuánto ahorrar al mes |
| Recurrentes | Sueldo, renta, suscripciones: se registran solos cada mes |
| Ajustes | Moneda, categorías, respaldos |

## Cómo empezar
1. **Cuentas** → crea tus cuentas con su saldo actual como saldo inicial.
2. **Tarjetas** → agrega cada tarjeta (límite, día de corte, día de pago y deuda actual).
3. **Recurrentes** → registra sueldo, renta y suscripciones.
4. Usa **+ Movimiento** para el día a día. Una compra con tarjeta aumenta la deuda; el **pago de tarjeta** baja el saldo de tu cuenta y la deuda.

## Respaldos
Cada día que abres el programa se copia la base de datos a `backups/` (últimas 30). Para mover tus datos a otra PC, copia `data/finanzas.db`.

Nota: las compras a meses sin intereses se registran por su total al comprar; la tarjeta muestra la mensualidad y los meses restantes.

## 🤖 Bot de Telegram (opcional)
Registra y consulta desde el celular, sin abrir puertos (el bot consulta a Telegram desde tu PC; la PC debe estar encendida con `iniciar.bat` abierto).
1. En Telegram habla con **@BotFather**, escribe `/newbot` y copia el token.
2. Ejecuta `iniciar_bot.bat` (o `python bot.py --setup`), pega el token y escríbele "hola" a tu bot: confirma en la consola que ese ID es tuyo. Solo ese usuario podrá darle órdenes.
3. Reinicia `iniciar.bat`: el bot arranca junto con el programa.

Ejemplos: `gasté 250 super` · `gasté 1200 gasolina con visa` · `compré 6000 laptop con visa a 6 msi` · `ingreso 15000 sueldo bbva` · `pago tarjeta visa 1000 bbva` · `gasté 90 tacos ayer` · `/resumen` `/saldos` `/tarjetas` `/presupuestos` `/ultimos` `/borrar`.
El token se guarda en `data/telegram.json` (no se sube a git). Si lo filtras, revócalo en @BotFather con `/revoke`.

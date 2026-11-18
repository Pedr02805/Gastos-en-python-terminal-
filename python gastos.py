import csv
import os
import sqlite3
from datetime import datetime

CARPETA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(CARPETA, "gastos.db")


class GestorGastos:
    """Registra gastos personales en una base de datos SQLite."""

    def __init__(self, db=DB):
        self.conn = sqlite3.connect(db)
        self.conn.row_factory = sqlite3.Row  # permite acceder por nombre de columna
        self._crear_tablas()

    def _crear_tablas(self):
        with self.conn:  # confirma (commit) los cambios automáticamente
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gastos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    descripcion TEXT,
                    monto REAL NOT NULL CHECK (monto > 0)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS presupuestos (
                    mes TEXT PRIMARY KEY,
                    monto REAL NOT NULL CHECK (monto > 0)
                )
                """
            )

    # ---------- Gastos ----------
    def agregar(self, fecha, categoria, descripcion, monto):
        # Los "?" evitan inyección SQL: nunca se concatenan datos en la consulta.
        with self.conn:
            self.conn.execute(
                "INSERT INTO gastos (fecha, categoria, descripcion, monto) "
                "VALUES (?, ?, ?, ?)",
                (fecha, categoria, descripcion, monto),
            )

    def obtener(self, id_gasto):
        return self.conn.execute(
            "SELECT * FROM gastos WHERE id = ?", (id_gasto,)
        ).fetchone()

    def editar(self, id_gasto, fecha, categoria, descripcion, monto):
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE gastos SET fecha = ?, categoria = ?, descripcion = ?, "
                "monto = ? WHERE id = ?",
                (fecha, categoria, descripcion, monto, id_gasto),
            )
        return cursor.rowcount > 0

    def listar(self, mes=None):
        if mes:
            return self.conn.execute(
                "SELECT * FROM gastos WHERE substr(fecha, 1, 7) = ? "
                "ORDER BY fecha DESC, id DESC",
                (mes,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM gastos ORDER BY fecha DESC, id DESC"
        ).fetchall()

    def eliminar(self, id_gasto):
        with self.conn:
            cursor = self.conn.execute("DELETE FROM gastos WHERE id = ?", (id_gasto,))
        return cursor.rowcount > 0  # True si se borró algo

    # ---------- Resúmenes ----------
    def resumen_por_categoria(self, mes):
        return self.conn.execute(
            "SELECT categoria, SUM(monto) AS total, COUNT(*) AS cantidad "
            "FROM gastos WHERE substr(fecha, 1, 7) = ? "
            "GROUP BY categoria ORDER BY total DESC",
            (mes,),
        ).fetchall()

    def total_mes(self, mes):
        fila = self.conn.execute(
            "SELECT COALESCE(SUM(monto), 0) AS total FROM gastos "
            "WHERE substr(fecha, 1, 7) = ?",
            (mes,),
        ).fetchone()
        return fila["total"]

    # ---------- Presupuesto ----------
    def fijar_presupuesto(self, mes, monto):
        # Si el mes ya tiene presupuesto, lo actualiza (UPSERT).
        with self.conn:
            self.conn.execute(
                "INSERT INTO presupuestos (mes, monto) VALUES (?, ?) "
                "ON CONFLICT(mes) DO UPDATE SET monto = excluded.monto",
                (mes, monto),
            )

    def obtener_presupuesto(self, mes):
        fila = self.conn.execute(
            "SELECT monto FROM presupuestos WHERE mes = ?", (mes,)
        ).fetchone()
        return fila["monto"] if fila else None

    def estado_presupuesto(self, mes):
        """Devuelve (presupuesto, gastado, restante) o None si no hay presupuesto."""
        presupuesto = self.obtener_presupuesto(mes)
        if presupuesto is None:
            return None
        gastado = self.total_mes(mes)
        return presupuesto, gastado, presupuesto - gastado

    # ---------- Exportación ----------
    def exportar_csv(self, mes, ruta=None):
        filas = self.resumen_por_categoria(mes)
        if not filas:
            return None
        ruta = ruta or os.path.join(CARPETA, f"resumen_{mes}.csv")
        total = self.total_mes(mes)
        # utf-8-sig para que Excel muestre bien las tildes.
        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            escritor = csv.writer(f)
            escritor.writerow(["Categoría", "Total", "Porcentaje", "Cantidad"])
            for fila in filas:
                escritor.writerow(
                    [
                        fila["categoria"],
                        round(fila["total"], 2),
                        f"{fila['total'] / total * 100:.1f}%",
                        fila["cantidad"],
                    ]
                )
            escritor.writerow(["TOTAL", round(total, 2), "100%", ""])
            presupuesto = self.obtener_presupuesto(mes)
            if presupuesto is not None:
                escritor.writerow(["PRESUPUESTO", round(presupuesto, 2), "", ""])
                escritor.writerow(["RESTANTE", round(presupuesto - total, 2), "", ""])
        return ruta

    def exportar_txt(self, mes, ruta=None):
        filas = self.resumen_por_categoria(mes)
        if not filas:
            return None
        ruta = ruta or os.path.join(CARPETA, f"reporte_{mes}.txt")
        total = self.total_mes(mes)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(f"REPORTE DE GASTOS - {mes}\n")
            f.write("=" * 40 + "\n")
            for fila in filas:
                porcentaje = fila["total"] / total * 100
                f.write(
                    f"{fila['categoria']:<14} ${fila['total']:>10,.0f} "
                    f"{porcentaje:>5.1f}% ({fila['cantidad']} gastos)\n"
                )
            f.write("-" * 40 + "\n")
            f.write(f"{'TOTAL':<14} ${total:>10,.0f}\n")
            presupuesto = self.obtener_presupuesto(mes)
            if presupuesto is not None:
                f.write(f"Presupuesto: ${presupuesto:,.0f}\n")
                f.write(f"Restante:    ${presupuesto - total:,.0f}\n")
        return ruta

    def cerrar(self):
        self.conn.close()


# ---------- Presentación ----------
def formato_dinero(valor):
    return f"${valor:,.0f}"


def mostrar_gastos(filas):
    if not filas:
        print("No hay gastos para mostrar.")
        return
    print(f"\n{'ID':<4} {'Fecha':<11} {'Categoría':<14} {'Monto':>12}  Descripción")
    print("-" * 62)
    for f in filas:
        print(
            f"{f['id']:<4} {f['fecha']:<11} {f['categoria']:<14} "
            f"{formato_dinero(f['monto']):>12}  {f['descripcion'] or ''}"
        )


def mostrar_estado_presupuesto(gestor, mes):
    estado = gestor.estado_presupuesto(mes)
    if estado is None:
        print(f"(Sin presupuesto fijado para {mes}.)")
        return
    presupuesto, gastado, restante = estado
    porcentaje = gastado / presupuesto * 100
    print(
        f"Presupuesto {mes}: {formato_dinero(presupuesto)} | "
        f"Gastado: {formato_dinero(gastado)} ({porcentaje:.1f}%) | "
        f"Restante: {formato_dinero(restante)}"
    )
    if gastado > presupuesto:
        print(f"¡ALERTA! Te pasaste del presupuesto por {formato_dinero(-restante)}.")
    elif porcentaje >= 80:
        print("Aviso: ya gastaste el 80% o más de tu presupuesto.")


def mostrar_resumen(gestor, mes):
    filas = gestor.resumen_por_categoria(mes)
    if not filas:
        print(f"No hay gastos registrados en {mes}.")
        return
    total = gestor.total_mes(mes)
    print(f"\nResumen de {mes}")
    print(f"{'Categoría':<14} {'Total':>12} {'%':>6} {'N°':>4}")
    print("-" * 40)
    for f in filas:
        porcentaje = f["total"] / total * 100
        print(
            f"{f['categoria']:<14} {formato_dinero(f['total']):>12} "
            f"{porcentaje:>5.1f}% {f['cantidad']:>4}"
        )
    print("-" * 40)
    print(f"{'TOTAL':<14} {formato_dinero(total):>12}")
    mostrar_estado_presupuesto(gestor, mes)


# ---------- Entrada de datos con validación ----------
def pedir_monto(mensaje="Monto: "):
    try:
        monto = float(input(mensaje).strip().replace(",", ""))
    except ValueError:
        print("Monto inválido.")
        return None
    if monto <= 0:
        print("El monto debe ser mayor que cero.")
        return None
    return monto


def pedir_fecha():
    texto = input("Fecha AAAA-MM-DD (Enter = hoy): ").strip()
    if texto == "":
        return datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(texto, "%Y-%m-%d")
        return texto
    except ValueError:
        print("Formato de fecha inválido.")
        return None


def pedir_mes():
    texto = input("Mes AAAA-MM (Enter = mes actual): ").strip()
    if texto == "":
        return datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(texto, "%Y-%m")
        return texto
    except ValueError:
        print("Formato de mes inválido.")
        return None


def pedir_id():
    try:
        return int(input("ID del gasto: ").strip())
    except ValueError:
        print("Debes escribir un número entero.")
        return None


# ---------- Acciones del menú ----------
def accion_agregar(gestor):
    fecha = pedir_fecha()
    if fecha is None:
        return
    categoria = input("Categoría (ej. comida, transporte): ").strip().lower()
    if not categoria:
        print("La categoría no puede estar vacía.")
        return
    descripcion = input("Descripción (opcional): ").strip()
    monto = pedir_monto()
    if monto is None:
        return
    gestor.agregar(fecha, categoria, descripcion, monto)
    print("Gasto registrado.")
    # Alerta inmediata si el mes del gasto tiene presupuesto.
    mostrar_estado_presupuesto(gestor, fecha[:7])


def accion_editar(gestor):
    id_gasto = pedir_id()
    if id_gasto is None:
        return
    actual = gestor.obtener(id_gasto)
    if actual is None:
        print("No se encontró el gasto.")
        return
    print("Enter conserva el valor actual.")

    texto = input(f"Fecha AAAA-MM-DD [{actual['fecha']}]: ").strip()
    fecha = actual["fecha"]
    if texto:
        try:
            datetime.strptime(texto, "%Y-%m-%d")
            fecha = texto
        except ValueError:
            print("Formato de fecha inválido. Edición cancelada.")
            return

    categoria = input(f"Categoría [{actual['categoria']}]: ").strip().lower()
    categoria = categoria or actual["categoria"]

    descripcion = input(f"Descripción [{actual['descripcion'] or ''}]: ").strip()
    descripcion = descripcion or actual["descripcion"]

    texto = input(f"Monto [{actual['monto']:,.0f}]: ").strip()
    monto = actual["monto"]
    if texto:
        try:
            monto = float(texto.replace(",", ""))
        except ValueError:
            print("Monto inválido. Edición cancelada.")
            return
        if monto <= 0:
            print("El monto debe ser mayor que cero. Edición cancelada.")
            return

    gestor.editar(id_gasto, fecha, categoria, descripcion, monto)
    print("Gasto editado.")
    mostrar_estado_presupuesto(gestor, fecha[:7])


def accion_presupuesto(gestor):
    mes = pedir_mes()
    if mes is None:
        return
    actual = gestor.obtener_presupuesto(mes)
    if actual is not None:
        print(f"Presupuesto actual de {mes}: {formato_dinero(actual)}")
    monto = pedir_monto("Nuevo presupuesto: ")
    if monto is None:
        return
    gestor.fijar_presupuesto(mes, monto)
    print("Presupuesto guardado.")
    mostrar_estado_presupuesto(gestor, mes)


def accion_exportar(gestor):
    mes = pedir_mes()
    if mes is None:
        return
    ruta_csv = gestor.exportar_csv(mes)
    ruta_txt = gestor.exportar_txt(mes)
    if ruta_csv is None:
        print(f"No hay gastos en {mes} para exportar.")
    else:
        print("Archivos creados:")
        print(f"  CSV: {os.path.abspath(ruta_csv)}")
        print(f"  TXT: {os.path.abspath(ruta_txt)}")


# ---------- Menú principal ----------
def menu():
    gestor = GestorGastos()
    try:
        while True:
            print(
                "\n=== CONTROL DE GASTOS ===\n"
                "1. Agregar gasto\n"
                "2. Listar todos los gastos\n"
                "3. Listar gastos de un mes\n"
                "4. Resumen mensual por categoría\n"
                "5. Editar gasto\n"
                "6. Eliminar gasto\n"
                "7. Fijar presupuesto mensual\n"
                "8. Exportar resumen (CSV y TXT)\n"
                "9. Salir"
            )
            opcion = input("Opción: ").strip()

            if opcion == "1":
                accion_agregar(gestor)
            elif opcion == "2":
                mostrar_gastos(gestor.listar())
            elif opcion == "3":
                mes = pedir_mes()
                if mes:
                    mostrar_gastos(gestor.listar(mes))
            elif opcion == "4":
                mes = pedir_mes()
                if mes:
                    mostrar_resumen(gestor, mes)
            elif opcion == "5":
                accion_editar(gestor)
            elif opcion == "6":
                id_gasto = pedir_id()
                if id_gasto is not None:
                    print("Eliminado." if gestor.eliminar(id_gasto) else "No se encontró el gasto.")
            elif opcion == "7":
                accion_presupuesto(gestor)
            elif opcion == "8":
                accion_exportar(gestor)
            elif opcion == "9":
                print("Hasta luego.")
                break
            else:
                print("Opción no válida.")
    finally:
        gestor.cerrar()  # se cierra la conexión aunque ocurra un error


if __name__ == "__main__":
    menu()
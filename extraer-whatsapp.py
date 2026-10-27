#!/usr/bin/env python3
"""Extrae conversaciones de WhatsApp desde el ChatStorage.sqlite de un respaldo de iPhone.

Solo lectura: abre la base en modo inmutable y nunca escribe en ella.
No imprime el contenido de ningún mensaje en pantalla; en consola solo van conteos.
No recibe ni pide contraseñas: si el respaldo esta cifrado, se descifra ANTES, aparte.

Uso:
  python3 extraer-whatsapp.py --sqlite ChatStorage.sqlite --salida ./salida
  python3 extraer-whatsapp.py --respaldo ~/Library/.../Backup/<UDID> --salida ./salida
  python3 extraer-whatsapp.py --autoprueba        # control positivo, no necesita respaldo
"""
import argparse, csv, json, os, sqlite3, sys, unicodedata
from datetime import datetime, timezone

APPLE_EPOCH = 978307200  # 2001-01-01 UTC, desplazamiento de las fechas de Core Data
DOMINIO_WA = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
RUTA_WA = "ChatStorage.sqlite"

# Columnas que la extraccion necesita. Si el esquema real no las trae, se dice y se para:
# mas vale no extraer que extraer de menos sin avisar.
REQUERIDAS = {
    "ZWACHATSESSION": ["Z_PK", "ZCONTACTJID", "ZPARTNERNAME"],
    "ZWAMESSAGE": ["Z_PK", "ZCHATSESSION", "ZISFROMME", "ZMESSAGEDATE", "ZTEXT", "ZMESSAGETYPE"],
}


def abrir_solo_lectura(ruta):
    uri = "file:" + os.path.abspath(ruta).replace("?", "%3f").replace("#", "%23") + "?immutable=1"
    return sqlite3.connect(uri, uri=True)


def columnas(con, tabla):
    try:
        return [f[1] for f in con.execute(f'PRAGMA table_info("{tabla}")')]
    except sqlite3.DatabaseError:
        return []


def verificar_esquema(con):
    """Devuelve (ok, hallazgos). Nunca adivina: comprueba tabla por tabla y columna por columna."""
    hallazgos = []
    ok = True
    for tabla, cols in REQUERIDAS.items():
        presentes = columnas(con, tabla)
        if not presentes:
            hallazgos.append(f"FALTA la tabla {tabla}")
            ok = False
            continue
        faltan = [c for c in cols if c not in presentes]
        if faltan:
            hallazgos.append(f"{tabla}: faltan columnas {', '.join(faltan)}")
            ok = False
        else:
            hallazgos.append(f"{tabla}: ok ({len(presentes)} columnas)")
    # ZWAGROUPMEMBER es opcional: solo sirve para saber quien hablo en un grupo
    hallazgos.append("ZWAGROUPMEMBER: " + ("presente" if columnas(con, "ZWAGROUPMEMBER") else "ausente (grupos sin autor por miembro)"))
    return ok, hallazgos


def fecha(valor):
    if valor is None:
        return None
    try:
        return datetime.fromtimestamp(float(valor) + APPLE_EPOCH, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def seguro(nombre, respaldo):
    """Nombre de archivo que no se sale de la carpeta ni rompe en otro sistema."""
    base = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode()
    base = "".join(c if (c.isalnum() or c in " -_") else "_" for c in base).strip().replace(" ", "_")
    return (base or f"chat_{respaldo}")[:60]


def localizar_en_respaldo(dir_respaldo):
    """Resuelve el hash de ChatStorage.sqlite via Manifest.db de un respaldo SIN cifrar."""
    manifest = os.path.join(dir_respaldo, "Manifest.db")
    if not os.path.exists(manifest):
        sys.exit(f"no hay Manifest.db en {dir_respaldo}: ruta equivocada, o el respaldo esta cifrado "
                 "(desciframelo primero y pasame el ChatStorage.sqlite con --sqlite)")
    con = abrir_solo_lectura(manifest)
    fila = con.execute("SELECT fileID FROM Files WHERE domain=? AND relativePath=?",
                       (DOMINIO_WA, RUTA_WA)).fetchone()
    con.close()
    if not fila:
        sys.exit("el Manifest.db no trae ChatStorage.sqlite: ese respaldo no incluye WhatsApp "
                 "(respaldo cifrado o app excluida)")
    fid = fila[0]
    ruta = os.path.join(dir_respaldo, fid[:2], fid)
    if not os.path.exists(ruta):
        sys.exit(f"el manifiesto apunta a {fid[:2]}/{fid} y ese archivo no esta en el respaldo")
    return ruta


def extraer(ruta_sqlite, dir_salida, formatos):
    con = abrir_solo_lectura(ruta_sqlite)
    ok, hallazgos = verificar_esquema(con)
    print("-- esquema --")
    for h in hallazgos:
        print("   " + h)
    if not ok:
        sys.exit("el esquema no es el que esta extraccion sabe leer: no extraigo nada a medias")

    tiene_miembro = bool(columnas(con, "ZWAGROUPMEMBER"))
    autor_grupo = ("(SELECT gm.ZMEMBERJID FROM ZWAGROUPMEMBER gm WHERE gm.Z_PK = m.ZGROUPMEMBER)"
                   if tiene_miembro and "ZGROUPMEMBER" in columnas(con, "ZWAMESSAGE") else "NULL")

    os.makedirs(dir_salida, exist_ok=True)
    chats = con.execute(
        "SELECT Z_PK, ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION ORDER BY Z_PK").fetchall()

    resumen = {"origen": os.path.abspath(ruta_sqlite), "conversaciones": 0,
               "mensajes_texto": 0, "mensajes_multimedia": 0, "mensajes_totales": 0,
               "fecha_mas_antigua": None, "fecha_mas_reciente": None, "detalle": []}
    filas_csv = []

    for pk, jid, nombre in chats:
        msgs = con.execute(
            f"""SELECT m.ZMESSAGEDATE, m.ZISFROMME, m.ZTEXT, m.ZMESSAGETYPE, {autor_grupo}
                FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = ? ORDER BY m.ZMESSAGEDATE""", (pk,)).fetchall()
        salida, n_texto, n_media = [], 0, 0
        for fch, demi, texto, tipo, autor in msgs:
            es_texto = (tipo == 0) and texto is not None
            if es_texto:
                n_texto += 1
            else:
                n_media += 1
                continue  # sin multimedia, por encargo: se cuenta pero no se exporta
            reg = {"fecha": fecha(fch), "quien": "yo" if demi else (autor or jid or nombre or "contraparte"),
                   "texto": texto}
            salida.append(reg)
            filas_csv.append({"conversacion": nombre or jid or f"chat_{pk}", "jid": jid or "",
                              "fecha": reg["fecha"] or "", "quien": reg["quien"], "texto": texto})
            if reg["fecha"]:
                if not resumen["fecha_mas_antigua"] or reg["fecha"] < resumen["fecha_mas_antigua"]:
                    resumen["fecha_mas_antigua"] = reg["fecha"]
                if not resumen["fecha_mas_reciente"] or reg["fecha"] > resumen["fecha_mas_reciente"]:
                    resumen["fecha_mas_reciente"] = reg["fecha"]

        if "json" in formatos and salida:
            with open(os.path.join(dir_salida, f"{seguro(nombre or jid, pk)}.json"), "w", encoding="utf-8") as fh:
                json.dump({"conversacion": nombre or jid, "jid": jid, "mensajes": salida},
                          fh, ensure_ascii=False, indent=1)
        resumen["detalle"].append({"conversacion": nombre or jid or f"chat_{pk}", "jid": jid,
                                   "texto": n_texto, "multimedia": n_media})
        resumen["conversaciones"] += 1
        resumen["mensajes_texto"] += n_texto
        resumen["mensajes_multimedia"] += n_media

    # Cotejo independiente: el total que ve la base, contado por otra consulta
    resumen["mensajes_totales"] = con.execute("SELECT COUNT(*) FROM ZWAMESSAGE").fetchone()[0]
    resumen["cuadra"] = (resumen["mensajes_texto"] + resumen["mensajes_multimedia"]
                         == resumen["mensajes_totales"])
    con.close()

    if "csv" in formatos:
        with open(os.path.join(dir_salida, "todas-las-conversaciones.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["conversacion", "jid", "fecha", "quien", "texto"])
            w.writeheader()
            w.writerows(filas_csv)
    with open(os.path.join(dir_salida, "resumen.json"), "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)

    print("-- conteos --")
    print(f"   conversaciones:       {resumen['conversaciones']}")
    print(f"   mensajes de texto:    {resumen['mensajes_texto']}")
    print(f"   multimedia (omitidos):{resumen['mensajes_multimedia']}")
    print(f"   total en la base:     {resumen['mensajes_totales']}")
    print(f"   cuadra texto+media == total: {'SI' if resumen['cuadra'] else 'NO'}")
    print(f"   rango: {resumen['fecha_mas_antigua']}  ->  {resumen['fecha_mas_reciente']}")
    print(f"   salida en: {os.path.abspath(dir_salida)}")
    return 0 if resumen["cuadra"] else 2


def autoprueba():
    """Control positivo: base de juguete con el esquema real y conteos conocidos."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="autoprueba-wa-")
    try:
        db = os.path.join(tmp, "ChatStorage.sqlite")
        con = sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT, ZPARTNERNAME TEXT);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER,
                                 ZMESSAGEDATE REAL, ZTEXT TEXT, ZMESSAGETYPE INTEGER, ZGROUPMEMBER INTEGER);
        CREATE TABLE ZWAGROUPMEMBER (Z_PK INTEGER PRIMARY KEY, ZMEMBERJID TEXT);
        INSERT INTO ZWACHATSESSION VALUES (1,'ejemplo-uno@s.whatsapp.net','Cliente Uno'),
                                          (2,'ejemplo-dos@s.whatsapp.net','Cliente Dos');
        INSERT INTO ZWAGROUPMEMBER VALUES (7,'ejemplo-tres@s.whatsapp.net');
        """)
        # chat 1: 3 de texto (uno mio) + 1 multimedia ; chat 2: 2 de texto
        base = 750000000.0   # ~2024-10 en tiempo de Core Data
        con.executemany("INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?)", [
            (1, 1, 0, base + 0,   "Buenas, tienen mesa?", 0, None),
            (2, 1, 1, base + 60,  "Si, a las 8",          0, None),
            (3, 1, 0, base + 120, None,                   1, None),   # multimedia
            (4, 1, 0, base + 180, "Gracias",              0, 7),
            (5, 2, 1, base + 240, "Confirmado",           0, None),
            (6, 2, 0, base + 300, "Perfecto",             0, None),
        ])
        con.commit(); con.close()

        salida = os.path.join(tmp, "salida")
        print("=== AUTOPRUEBA (base de juguete, conteos conocidos) ===")
        extraer(db, salida, ["json", "csv"])
        r = json.load(open(os.path.join(salida, "resumen.json"), encoding="utf-8"))
        esperado = {"conversaciones": 2, "mensajes_texto": 5, "mensajes_multimedia": 1, "mensajes_totales": 6}
        fallas = [f"{k}: esperaba {v}, dio {r[k]}" for k, v in esperado.items() if r[k] != v]
        # el mensaje 4 debe venir atribuido al miembro del grupo, no al jid del chat
        c1 = json.load(open(os.path.join(salida, "Cliente_Uno.json"), encoding="utf-8"))
        if c1["mensajes"][-1]["quien"] != "ejemplo-tres@s.whatsapp.net":
            fallas.append("autor de grupo no resuelto por ZWAGROUPMEMBER")
        if c1["mensajes"][1]["quien"] != "yo":
            fallas.append("ZISFROMME no se refleja como 'yo'")
        if not r["detalle"] or r["detalle"][0]["multimedia"] != 1:
            fallas.append("el multimedia no quedo contado en el detalle")
        print("=== RESULTADO:", "TODO BIEN" if not fallas else "FALLAS: " + "; ".join(fallas), "===")
        return 0 if not fallas else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description="Extrae conversaciones de WhatsApp de un respaldo de iPhone (solo lectura).")
    p.add_argument("--sqlite", help="ruta a un ChatStorage.sqlite ya disponible")
    p.add_argument("--respaldo", help="carpeta del respaldo de Finder (solo si NO esta cifrado)")
    p.add_argument("--salida", default="./salida-whatsapp")
    p.add_argument("--formato", default="json,csv")
    p.add_argument("--autoprueba", action="store_true", help="corre el control positivo y sale")
    a = p.parse_args()
    if a.autoprueba:
        sys.exit(autoprueba())
    if not a.sqlite and not a.respaldo:
        p.error("dame --sqlite o --respaldo (o --autoprueba)")
    ruta = a.sqlite or localizar_en_respaldo(os.path.expanduser(a.respaldo))
    sys.exit(extraer(os.path.expanduser(ruta), os.path.expanduser(a.salida),
                     [f.strip() for f in a.formato.split(",")]))


if __name__ == "__main__":
    main()

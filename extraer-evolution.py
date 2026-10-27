#!/usr/bin/env python3
"""Extrae las conversaciones de UNA instancia de Evolution desde su Postgres. SOLO LECTURA.

La transaccion se fija en read-only del lado del servidor, asi que esta herramienta no puede
escribir ni por error. No imprime el texto de ningun mensaje: en consola solo van conteos, y los
telefonos de los conteos salen enmascarados.

  # define EVOLUTION_DB_URL en tu .env (ver .env.example); no la pases por la linea de comandos
  python3 extraer-evolution.py --instancia mi-instancia --salida ./salida
  python3 extraer-evolution.py --solo-conteos --instancia mi-instancia
"""
import argparse, csv, json, os, re, subprocess, sys, urllib.parse as up
from datetime import datetime, timezone

# La conexion NUNCA va en el codigo: sale de EVOLUTION_DB_URL (entorno o archivo .env local).
# Ver .env.example. Con --conf se puede apuntar a otro archivo de variables.
VAR_URL = "EVOLUTION_DB_URL"
# Donde vive el texto segun el tipo de mensaje de WhatsApp
TEXTO_SQL = """COALESCE(m.message->>'conversation',
                        m.message->'extendedTextMessage'->>'text')"""


def enmascarar(jid):
    """Deja solo los ultimos 4 digitos de CADA tramo numerico: cubre jid de grupo con guion."""
    return re.sub(r"\d{5,}", lambda t: "X" * (len(t.group()) - 4) + t.group()[-4:], jid or "")


def conexion():
    """Devuelve los datos de conexion. Orden: --conf, luego el entorno, luego ./.env."""
    uri = os.environ.get(VAR_URL)
    if not uri:
        for ruta in (os.environ.get("CONF_ENV"), ".env"):
            if ruta and os.path.exists(os.path.expanduser(ruta)):
                for l in open(os.path.expanduser(ruta), encoding="utf-8", errors="replace"):
                    l = l.strip()
                    if l.startswith(VAR_URL) or l.startswith("DATABASE_CONNECTION_URI"):
                        uri = l.split("=", 1)[1].strip().strip("'\"")
                        break
            if uri:
                break
    if not uri:
        sys.exit(f"falta {VAR_URL}: exportala en el entorno o ponla en un .env "
                 "(copia .env.example). Nunca la pongas en la linea de comandos.")
    pu = up.urlparse(uri)
    esquema = (up.parse_qs(pu.query).get("schema") or ["public"])[0]
    env = dict(os.environ)
    env["PGPASSWORD"] = up.unquote(pu.password or "")        # por entorno, nunca por argumento
    return pu, esquema, env, up.unquote(pu.password or "")


def consulta(sql):
    pu, esquema, env, clave = conexion()
    cmd = ["psql", "-h", pu.hostname, "-p", str(pu.port or 5432), "-U", up.unquote(pu.username),
           "-d", pu.path.lstrip("/"), "-v", "ON_ERROR_STOP=1", "-At", "-F", "\x1f",
           "-P", "pager=off",
           "-c", "SET default_transaction_read_only = on;",
           "-c", f'SET search_path TO "{esquema}";', "-c", sql]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    if r.returncode:
        msg = (r.stderr or "").replace(clave, "REDACTADO") if clave else (r.stderr or "")
        sys.exit("psql fallo: " + msg.strip()[:500])
    filas = [l.split("\x1f") for l in r.stdout.splitlines() if l and not l.startswith("SET")]
    return filas


def consulta_csv(sql):
    """Como consulta(), pero por COPY ... CSV: soporta texto con saltos de linea y comillas."""
    import csv as _csv, io
    pu, esquema, env, clave = conexion()
    cmd = ["psql", "-h", pu.hostname, "-p", str(pu.port or 5432), "-U", up.unquote(pu.username),
           "-d", pu.path.lstrip("/"), "-v", "ON_ERROR_STOP=1", "-At", "-P", "pager=off",
           "-c", "SET default_transaction_read_only = on;",
           "-c", f'SET search_path TO "{esquema}";',
           "-c", f"COPY ({sql}) TO STDOUT WITH (FORMAT csv)"]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    if r.returncode:
        msg = (r.stderr or "").replace(clave, "REDACTADO") if clave else (r.stderr or "")
        sys.exit("psql fallo: " + msg.strip()[:500])
    cuerpo = "\n".join(l for l in r.stdout.splitlines() if l != "SET")
    return list(_csv.reader(io.StringIO(cuerpo)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--instancia", required=True)
    p.add_argument("--conf", help="archivo de variables con EVOLUTION_DB_URL (por omision ./.env)")
    p.add_argument("--salida", default="./salida-evolution")
    p.add_argument("--solo-conteos", action="store_true")
    a = p.parse_args()
    if a.conf:
        os.environ["CONF_ENV"] = a.conf
    inst = a.instancia.replace("'", "''")

    ident = consulta(f"""SELECT id, name, "connectionStatus", to_char("createdAt",'YYYY-MM-DD')
                         FROM "Instance" WHERE name = '{inst}';""")
    if not ident:
        sys.exit(f"no existe la instancia '{a.instancia}'")
    iid, nombre, estado, creada = ident[0]

    tot = consulta(f"""SELECT count(*),
        count(*) FILTER (WHERE {TEXTO_SQL} IS NOT NULL),
        count(DISTINCT m.key->>'remoteJid'),
        to_char(to_timestamp(min(m."messageTimestamp")),'YYYY-MM-DD'),
        to_char(to_timestamp(max(m."messageTimestamp")),'YYYY-MM-DD')
        FROM "Message" m WHERE m."instanceId" = '{iid}';""")[0]
    n_todos, n_texto, n_chats, f_min, f_max = int(tot[0]), int(tot[1]), int(tot[2]), tot[3], tot[4]

    print(f"-- instancia {nombre} ({estado}, vinculada {creada}) --")
    print(f"   conversaciones con mensajes: {n_chats}")
    print(f"   mensajes totales:            {n_todos}")
    print(f"   de ellos con texto:          {n_texto}")
    print(f"   sin texto (multimedia etc):  {n_todos - n_texto}")
    print(f"   cuadra texto+sin_texto == total: {'SI' if n_texto + (n_todos-n_texto) == n_todos else 'NO'}")
    print(f"   rango de fechas: {f_min} -> {f_max}")
    if a.solo_conteos:
        return 0

    filas = consulta_csv(f"""SELECT m.key->>'remoteJid', m."messageTimestamp",
           CASE WHEN (m.key->>'fromMe')::boolean THEN 'yo' ELSE COALESCE(m.participant, m.key->>'remoteJid') END,
           {TEXTO_SQL}
        FROM "Message" m
        WHERE m."instanceId" = '{iid}' AND {TEXTO_SQL} IS NOT NULL
        ORDER BY m.key->>'remoteJid', m."messageTimestamp" """)

    malas = [f for f in filas if len(f) != 4]
    if malas:
        sys.exit(f"{len(malas)} filas no traen 4 campos: no exporto nada a medias")
    os.makedirs(a.salida, exist_ok=True)
    porchat, csvfilas = {}, []
    for jid, ts, quien, texto in filas:
        fecha = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts.isdigit() else None
        porchat.setdefault(jid, []).append({"fecha": fecha, "quien": quien, "texto": texto})
        csvfilas.append({"chat": jid, "fecha": fecha or "", "quien": quien, "texto": texto})

    for jid, msgs in porchat.items():
        seguro = re.sub(r"[^A-Za-z0-9._-]", "_", jid)[:60]
        with open(os.path.join(a.salida, f"{seguro}.json"), "w", encoding="utf-8") as fh:
            json.dump({"chat": jid, "mensajes": msgs}, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.salida, "todas-las-conversaciones.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["chat", "fecha", "quien", "texto"]); w.writeheader(); w.writerows(csvfilas)

    resumen = {"instancia": nombre, "vinculada": creada, "conversaciones_con_mensajes": n_chats,
               "mensajes_totales": n_todos, "con_texto": n_texto, "sin_texto": n_todos - n_texto,
               "rango": [f_min, f_max], "exportados": len(csvfilas),
               "cuadra_exportados_vs_con_texto": len(csvfilas) == n_texto,
               "por_chat": sorted(({"chat_enmascarado": enmascarar(j), "mensajes": len(m),
                                    "mas_antiguo": m[0]["fecha"][:10] if m[0]["fecha"] else None,
                                    "mas_reciente": m[-1]["fecha"][:10] if m[-1]["fecha"] else None}
                                   for j, m in porchat.items()), key=lambda d: -d["mensajes"])}
    with open(os.path.join(a.salida, "resumen.json"), "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)

    print(f"   exportados a archivo:        {len(csvfilas)}")
    print(f"   cuadra exportados == con texto: {'SI' if len(csvfilas) == n_texto else 'NO'}")
    print(f"   archivos en: {os.path.abspath(a.salida)} ({len(porchat)} json + csv + resumen)")
    return 0 if len(csvfilas) == n_texto else 2


if __name__ == "__main__":
    sys.exit(main())

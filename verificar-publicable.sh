#!/usr/bin/env bash
# Revisa que lo que va a publicarse no lleve secretos, datos reales ni rastros de la casa.
# Se excluye a SI MISMO de la revisión: su propio código es la lista de patrones prohibidos,
# así que buscarse encontraría cada palabra que busca. Eso no es un hallazgo, es un espejo.
# Se corre SOBRE EL ARCHIVO QUE VIAJA (git archive), no sobre el árbol de trabajo:
# un archivo ignorado o con export-ignore no viaja, y revisar el árbol da falsos positivos
# y falsos negativos a la vez.
set -u
DIR="${1:-}"
[ -z "$DIR" ] && { echo "uso: $0 <carpeta-con-lo-que-viaja>"; exit 64; }
[ -d "$DIR" ] || { echo "no existe la carpeta $DIR"; exit 64; }

fallas=0
revisar() {  # nombre, patrón (ERE), por qué
  local nombre="$1" patron="$2" porque="$3" hits
  # -e es obligatorio: un patrón que empieza con "-" (como el encabezado de una llave privada)
  # lo leería grep como banderas y devolvería CERO sin fallar. Caído y corregido el 23-oct.
  # --exclude-dir=.git: los registros internos de git traen el correo del autor y marcas de
  # tiempo de 10 digitos, que se leerian como dominio propio y como telefono. No son contenido.
  hits=$(grep -rInE --binary-files=without-match --exclude-dir=.git -e "$patron" "$DIR" 2>/dev/null \
         | grep -v '\.env\.example' | grep -v 'verificar-publicable\.sh' || true)
  if [ -n "$hits" ]; then
    echo "❌ $nombre — $porque"
    echo "$hits" | sed -E 's/^/     /' | head -5
    fallas=$((fallas+1))
  else
    echo "✅ $nombre"
  fi
}

revisar "URL con usuario y clave"  '[a-z+]+://[^/[:space:]:]+:[^/[:space:]@]+@' "una credencial dentro de una URL se publica entera"
revisar "llave privada"            '-----BEGIN [A-Z ]*PRIVATE KEY-----'          "material criptográfico"
revisar "token tipo glpat/ghp"     '(glpat-|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}' "token de GitLab, GitHub o Slack"
revisar "servidores de la casa"    '([a-z0-9-]+\.)?(habil\.mx|cicd\.habil|hb-cicd-gitlab)' "nombre de infraestructura interna"
revisar "IP privada"               '(^|[^0-9])(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)[0-9]{1,3}\.[0-9]{1,3}' "dirección de la red interna"
revisar "teléfono de 10+ dígitos"  '(^|[^0-9])[0-9]{10,}([^0-9]|$)'              "puede ser un número real de una persona"
# Los nombres propios que no deben publicarse (clientes, instancias, usuarios) NO van aquí:
# una lista de nombres prohibidos escrita en un archivo público publica justo lo que protege.
# Viven en un archivo externo, fuera de este repositorio, que se pasa por PATRONES_EXTRA:
# una expresión por línea. Las huellas tampoco servirían: un nombre corto se adivina probando.
if [ -n "${PATRONES_EXTRA:-}" ] && [ -f "$PATRONES_EXTRA" ]; then
  n=0
  while IFS= read -r linea; do
    case "$linea" in ""|\#*) continue ;; esac
    n=$((n+1))
    revisar "nombre reservado #$n" "$linea" "coincide con la lista privada de $PATRONES_EXTRA"
  done < "$PATRONES_EXTRA"
  echo "   ($n expresiones de la lista privada)"
  if [ "$n" -eq 0 ]; then
    echo "❌ la lista privada $PATRONES_EXTRA no tiene ninguna expresión válida"
    fallas=$((fallas+1))
  fi
elif [ "${SIN_LISTA_PRIVADA:-0}" = "1" ]; then
  echo "⚠️  nombres propios NO revisados — renuncia explícita con SIN_LISTA_PRIVADA=1"
else
  # FALLA CERRADO a proposito: un aviso que no cambia el resultado final es un falso verde,
  # y esta revision existe justo porque una lista de nombres se publico por descuido.
  echo "❌ nombres propios SIN REVISAR — define PATRONES_EXTRA con tu lista privada"
  echo "    (clientes, instancias, usuarios; una expresión por línea, fuera de este repo)"
  echo "    si de verdad no aplica, dilo explícitamente con SIN_LISTA_PRIVADA=1"
  fallas=$((fallas+1))
fi

revisar "atribución a IA"          '(Claude|Anthropic|ChatGPT|OpenAI|Copilot)'   "nada se atribuye a una IA"

echo
if [ "$fallas" -eq 0 ]; then echo "APTO PARA PUBLICAR: todas las revisiones en verde"; exit 0
else echo "NO PUBLICABLE: $fallas revisiones en rojo"; exit 1; fi

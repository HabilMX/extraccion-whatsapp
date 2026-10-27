# Extracción de conversaciones de WhatsApp

Dos herramientas de línea de comandos, en Python, para **sacar el texto de las conversaciones de
WhatsApp a archivos JSON y CSV**: una lee la copia de seguridad local de un iPhone y la otra lee la
base de datos de una instalación de [Evolution API](https://github.com/EvolutionAPI/evolution-api).

Sirven como primer paso de un proyecto de recuperación de información: convertir conversaciones en
texto cotejable, con los conteos a la vista para saber si falta algo.

## Qué hacen, y qué no

| Hacen | No hacen |
|---|---|
| Leen la fuente **sin escribir en ella** | No envían mensajes ni modifican la cuenta |
| Un JSON por conversación y un CSV con todo | No exportan fotos, audio ni video: los **cuentan** y los omiten |
| Dicen cuántas conversaciones, cuántos mensajes y el rango de fechas | No imprimen el texto de ningún mensaje en pantalla |
| Se detienen si el formato no es el que saben leer | No extraen «lo que se pueda» en silencio |

## Requisitos

- Python 3.9 o superior. **Sin dependencias**: solo biblioteca estándar.
- Para la vía de Evolution, el cliente `psql` instalado.

## Configuración

Ningún dato de conexión va en el código. Copia el ejemplo y pon tus valores:

```bash
cp .env.example .env
```

`.env` está en `.gitignore` y no se versiona. La contraseña viaja a `psql` por variable de entorno:
**nunca** por la línea de comandos, donde cualquier usuario de la máquina la vería en la lista de
procesos.

## Uso

**Desde la copia de seguridad de un iPhone** (hecha en Finder, sin cifrar):

```bash
python3 extraer-whatsapp.py \
  --respaldo ~/Library/Application\ Support/MobileSync/Backup/<identificador> \
  --salida ./salida
```

Encuentra el archivo de WhatsApp dentro de la copia resolviendo su nombre real en el `Manifest.db`.
Si la copia está cifrada, descífrala antes con la herramienta que prefieras y apunta directo al
archivo con `--sqlite`.

**Desde la base de datos de Evolution API:**

```bash
python3 extraer-evolution.py --instancia mi-instancia --salida ./salida
python3 extraer-evolution.py --instancia mi-instancia --solo-conteos   # solo los números
```

La consulta se ejecuta con la transacción fijada en **solo lectura del lado del servidor**, así que
no puede escribir ni por error.

## Cómo saber que funciona

```bash
python3 extraer-whatsapp.py --autoprueba
```

Construye una base de juguete con el mismo formato y conteos conocidos, extrae y coteja. Incluye un
mensaje de grupo, para comprobar que el autor se resuelve por el miembro y no por la conversación.

**Y la prueba que de verdad importa:** con una base de formato distinto, la herramienta **se detiene
con código 1 y no escribe nada**, en vez de reportar cero mensajes como si la conversación estuviera
vacía. Un cero de una herramienta no es un cero del mundo, y esa diferencia se prueba, no se supone.

## Antes de publicar algo que salga de aquí

```bash
./verificar-publicable.sh <carpeta>
```

Nueve revisiones sobre lo que va a publicarse: credenciales dentro de una URL, llaves privadas,
tokens, nombres de servidores, direcciones de red interna, números de teléfono y nombres de clientes.
Cada revisión está probada con un archivo trampa que debe hacerla fallar — porque un verificador que
nunca encuentra nada se ve igual que uno que no busca.

## Datos de otras personas

Una conversación tiene dos lados. El dueño de la cuenta puede consentir sobre la suya; **quien le
escribió no ha consentido nada**. Antes de que este texto alimente un buscador o un modelo, decide
qué conversaciones entran, anonimiza lo que identifique a una persona, y asegúrate de que la
finalidad esté cubierta por el aviso de privacidad que corresponda.

## Licencia

MIT. Ver [LICENSE](LICENSE).

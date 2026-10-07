# Catálogo SQLite y revisión en SQLiteBrowser

Esta fase permite importar y consultar metadatos FLAC/MP3 sin Qt y sin modificar los
archivos musicales. La GUI queda pendiente de validar primero el esquema y los datos
con SQLiteBrowser. `scripts/import_audio.py` es una herramienta de preparación y
revisión, no la interfaz CLI completa de Trackfolio.

## Tablas y relaciones

El catálogo usa varias tablas. La vista `track_details` reúne los datos para su consulta;
no sustituye las tablas normalizadas ni contiene otra copia de los metadatos.

| Tabla | Contenido |
| --- | --- |
| `libraries` | Raíz local de cada biblioteca. |
| `albums` | Agrupaciones provisionales de álbum: biblioteca, directorio, título, año, fecha y total de discos. |
| `tracks` | Título de pista, numeración, referencia opcional al álbum y letras cuando existen. |
| `artists` | Nombres acreditados e identificador externo opcional; el nombre no es único. |
| `genres` | Géneros, reutilizados cuando coincide exactamente el texto de su nombre. |
| `track_artists` | Créditos de artistas de pista, con rol y posición. |
| `album_artists` | Créditos de artistas de álbum, con rol y posición. |
| `track_genres` | Géneros de cada pista, con posición. |
| `audio_files` | Archivo físico, ruta relativa, formato, propiedades de audio y referencia/origen de la carátula. |
| `artworks` | Bytes de la imagen en un BLOB, SHA-256, MIME y dimensiones. |
| `raw_tags` | Etiquetas textuales leídas por archivo: clave, valor y posición dentro de esa clave. |
| `alembic_version` | Revisión del esquema aplicada por Alembic. |

Las claves foráneas conectan las tablas y se activan en cada conexión de la aplicación.
Las posiciones conservan el orden de artistas y géneros. Las relaciones permiten
varios artistas y géneros por pista, y un artista de álbum distinto del de la pista.

Una pista puede relacionarse con varios archivos físicos en el esquema. El importador
actual crea una pista por archivo nuevo: todavía no identifica automáticamente una
misma grabación en FLAC, MP3 u otras ediciones. `track_details` devuelve **una fila por
archivo**; si varios archivos comparten una pista, repetirán su `track_id`. Los créditos
y géneros se agregan por separado para evitar multiplicar filas al consultar la vista.

## Identidad y datos ausentes

Reimportar la misma ruta relativa dentro de la misma biblioteca actualiza sus datos y
conserva sus identificadores. Una copia en otra ruta o un archivo renombrado se considera
otro archivo; la ruta no demuestra que dos grabaciones sean iguales.

Los álbumes se agrupan provisionalmente por biblioteca, directorio y metadatos de álbum,
incluidos fecha, año, total de discos y artistas de álbum. Dos títulos iguales no bastan
para fusionarlos. Si falta el título pero existen otros datos de álbum, se conserva una
agrupación con título `NULL` para mantener esos datos y créditos. Un artista se reutiliza
por nombre exacto dentro del mismo contexto de álbum, o de biblioteca/directorio para
pistas sin álbum. Pueden existir entidades con
el mismo nombre en otros contextos: fusionarlas requiere una decisión posterior basada
en identificadores o revisión del usuario.

Un campo escalar ausente se guarda como `NULL`. Los artistas o géneros ausentes no
generan relaciones: en los contratos Python se representan con una tupla vacía y en
la vista agregada aparecen como `NULL`. La futura GUI deberá mostrarlos en blanco.
No se rellenan usando el nombre del archivo, otras pistas o información externa.

El año puede extraerse de una fecha presente: `DATE=1981` produce `album_date='1981'`
y `album_year=1981`. `raw_tags` conserva que la etiqueta original era `DATE`; no se
inventa una etiqueta `YEAR`. La numeración propia de cada pista tampoco se completa
con el total de discos de otro registro.

`raw_tags` conserva los valores textuales originales leídos, incluso los no utilizados
por el catálogo. No es una copia binaria de todas las estructuras del archivo. La
importación elimina duplicados exactos en las relaciones normalizadas, conservando
los valores leídos en `raw_tags`. Cambiar una entidad del catálogo no reescribe por sí
solo las etiquetas musicales.

## Carátulas

Se utiliza primero una imagen incrustada reconocible, con preferencia por la portada
frontal. Si no existe una válida, se intenta leer `album.jpg` del mismo directorio.
Si tampoco existe o no se reconoce, la referencia y las propiedades de carátula quedan
en `NULL`.

Los bytes se guardan en `artworks.data`, y las imágenes idénticas se reutilizan por su
SHA-256. `audio_files` registra si el origen fue `embedded` o `album.jpg`; en el segundo
caso también conserva la ruta relativa. La imagen sigue disponible en el catálogo
aunque después cambie el archivo externo. Esta fase no descarga ni genera carátulas.

## Importar para revisar

Desde la raíz del proyecto, con el entorno preparado, sustituir las rutas de ejemplo
por un archivo y una biblioteca reales:

```sh
uv sync --locked --group dev
uv run --locked python scripts/import_audio.py "/ruta/a/biblioteca/cancion.flac" --database data/trackfolio.sqlite3 --library-root "/ruta/a/biblioteca"
```

Los mismos argumentos funcionan en Windows usando sus rutas. El archivo debe estar
dentro de la raíz indicada. Si se omite `--library-root`, se utiliza el directorio del
archivo. El script prepara o reconoce el esquema antes de guardar el catálogo; una
base de datos ajena o de revisión desconocida se rechaza.

La base local de revisión es `data/trackfolio.sqlite3`. Los archivos SQLite y la música
están excluidos de Git. La raíz de biblioteca es una ubicación local: mover el proyecto
no mueve la música ni adapta automáticamente la raíz guardada en una base existente.

## Comprobar en SQLiteBrowser

1. Abrir `data/trackfolio.sqlite3` con **Abrir base de datos**.
2. En **Estructura de base de datos**, revisar las tablas anteriores y `track_details`.
3. En **Examinar datos**, seleccionar la vista `track_details` para ver los metadatos
   reunidos, o una tabla para comprobar sus relaciones.
4. En **Ejecutar SQL**, ejecutar estas consultas de revisión:

```sql
SELECT file_id, track_id, relative_path, format,
       title, artists, album, album_artists, album_year, album_date,
       genres, track_number, track_total, disc_number, disc_total,
       cover_source, cover_mime, cover_width, cover_height, cover_bytes
FROM track_details
ORDER BY file_id;

SELECT file_id,
       album_artists IS NULL AS sin_artista_de_album,
       lyrics IS NULL AS sin_letras,
       cover_source IS NULL AS sin_caratula
FROM track_details;

SELECT id, mime, width, height, length(data) AS bytes
FROM artworks;

SELECT version_num FROM alembic_version;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

La revisión aplicada debe ser `001_initial`, `foreign_key_check` no debe devolver
filas e `integrity_check` debe devolver `ok`. En `artworks`, SQLiteBrowser permite
examinar el BLOB de la imagen; la consulta anterior comprueba sus propiedades sin
mostrar el contenido binario.

En la muestra de validación, el resultado esperado es:

| Campo | Valor |
| --- | --- |
| Título / artista de pista | Run If You Can / Accept |
| Álbum / fecha / año | Breaker / 1981 / 1981 |
| Artista de álbum | `NULL` en la vista; sin filas en `album_artists` |
| Género | Heavy Metal |
| Pista / total de pistas | 3 / 10 |
| Disco / total de discos | 1 / 1 |
| Carátula | `embedded`, `image/jpeg`, 500 × 500, 385192 bytes |
| Letras | `NULL` |

La ausencia de artista de álbum es intencionada: el archivo sólo acredita al artista
de pista. Antes de iniciar la GUI se revisarán estos resultados y las relaciones del
esquema con el usuario.

## Migración canónica y SQL reproducible

La fuente del esquema es la migración Alembic empaquetada en
`src/trackfolio/infrastructure/migrations/versions/001_initial.py` y su definición
`initial_schema.py`. La aplicación la ejecuta mediante `migrate_database`; no crea
tablas por un camino independiente con `create_all`.

`migrations/001_initial.sql` se genera desde esa misma revisión para examinarla y
crear una base nueva desde SQLiteBrowser. Se regenera con:

```sh
uv run --locked python -m trackfolio.infrastructure.database --export-sql migrations/001_initial.sql
```

Para comprobar sólo la estructura, crear otra base vacía en SQLiteBrowser, abrir el
archivo SQL en **Ejecutar SQL** y ejecutar el script completo. Incluye la transacción,
las tablas, la vista, la revisión Alembic y la marca de identificación de Trackfolio.
No contiene la música ni los datos de la muestra y no se ejecuta sobre un catálogo
existente. Esta ruta permite revisar el mismo esquema que usa la migración en línea.

En desarrollo, `uv run --locked alembic upgrade head` aplica la migración sobre la
base configurada en `alembic.ini`, por defecto `data/trackfolio.sqlite3`. Las siguientes
modificaciones del esquema deberán convertirse en nuevas revisiones; el SQL inicial
no sustituye las migraciones de catálogos existentes.

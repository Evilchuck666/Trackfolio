# Plan de escritura de etiquetas FLAC y MP3

Estado: implementación funcional del 2 de noviembre de 2026, con el flujo simplificado
solicitado después de la primera entrega. La comprobación local y la validación por
plataforma de cada revisión se registran en [VALIDATION.md](../VALIDATION.md).
La [guía de uso y recuperación](tag-writing.md) describe los formatos y límites.
Desde el 3 de noviembre de 2026 también se actualiza opcionalmente `album.nfo`,
según el [plan implementado de NFO](album-nfo-plan.md). Se comparte operación,
registro y limpieza de respaldos; los resultados NFO se separan de los musicales.

## Resultado y alcance

Editar y guardar los valores en el catálogo, seleccionar una o varias canciones y
pulsar **Escribir etiquetas…**. El diálogo muestra inmediatamente las canciones,
la salida del progreso y únicamente **Cerrar** y **Escribir etiquetas**.

Pulsar escribir sobrescribe automáticamente todas las diferencias entre los diez
campos editables guardados y los archivos. Cada canción utiliza sus propios valores;
la selección múltiple no iguala títulos, artistas ni numeración por sí misma. Un valor
vacío guardado elimina su etiqueta. Los archivos sin diferencias se omiten.

La acción **Escribir etiquetas de todo el catálogo…** utiliza el mismo flujo con todas
las canciones, sin depender de la selección. Obtiene la lista completa de SQLite en un
trabajador antes de mostrar el diálogo, tras resolver los borradores pendientes.

No hay casillas de campos/archivos, revisión manual de diferencias, botones de informes
ni gestor de operaciones pendientes. Si se produce un error, un pop-up ofrece guardar
un informe JSON con los resultados y respaldos. El listado permanece visible durante
la preparación, escritura y finalización, incluidas las canciones con incidencias.

**Guardar** sigue editando únicamente SQLite. Antes de abrir el diálogo se resuelven
los borradores con Guardar/Descartar/Cancelar. Se congela la selección y se calculan
las diferencias contra los archivos actuales al ejecutar, sin usar una comparación
antigua ni cambiar automáticamente los destinatarios.

## Correspondencia de campos

| Campo del catálogo | FLAC | MP3 ID3v2 |
| --- | --- | --- |
| Canción | `TITLE` | `TIT2` |
| Artistas | Valores repetidos de `ARTIST` | Lista `TPE1` |
| Álbum | `ALBUM` | `TALB` |
| Año | `DATE` | `TDRC`, o representación v2.3 |
| Pista / total | `TRACKNUMBER` / `TRACKTOTAL` | `TRCK` |
| Disco / total | `DISCNUMBER` / `DISCTOTAL` | `TPOS` |
| Géneros | Valores repetidos de `GENRE` | Lista `TCON` |
| Líricas | `LYRICS` | Primera versión `USLT` expuesta por el lector |

- Se escribe únicamente lo que difiere; el audio, las imágenes y los metadatos ajenos
  al catálogo se conservan. No se incrusta `album.jpg` ni se renombran archivos.
  Si existe `album.nfo` junto al audio, se sincroniza una vez por carpeta con los
  valores coherentes de todas sus pistas catalogadas, sin ampliar la selección musical.
- Se actualiza la familia de alias de cada campo modificado, incluidos los `TXXX`
  reconocidos por el lector, para que no prevalezcan valores antiguos al importar.
- Los artistas y géneros conservan orden, Unicode y nombres completos, sin unir ni
  dividir por comas, punto y coma o `/`. Las listas vacías eliminan su familia.
- Se escriben los números y totales guardados. El total sin número vuelve a leerse
  como número ausente, sin inventar numeración.
- Al cambiar el año se conserva la precisión válida de la fecha. Si no es representable
  o produce una fecha inválida, se sustituye por el año guardado; vaciar el año elimina
  la fecha. Los años se serializan con cuatro dígitos, en el rango 1–9999.
- Si hay varias líricas ID3, se actualiza la primera versión expuesta por el lector,
  conservando su idioma y descripción y las otras versiones. No se pide otra selección.
- Se conserva ID3v2.3/v2.4; sin etiquetas se crea v2.4. ID3v2.2, ID3v1 coexistente y
  listas v2.3 que se unirían con pérdidas producen una incidencia, sin conversión.

## Escritura de un archivo

La preparación y escritura se ejecutan secuencialmente en un trabajador. Antes de
publicar se comprueba la raíz importada, los permisos, la identidad, tamaño, `mtime_ns`
y SHA-256 completo del original. Se rechazan enlaces simbólicos/junctions, enlaces duros,
rutas que escapen de la raíz y destinos físicos duplicados.

1. Obtener las instantáneas guardadas y calcular internamente todas las diferencias.
2. Preparar el escritor SQLite y crear un registro persistente de operación.
3. Crear un respaldo completo y exclusivo y verificar su hash.
4. Crear un temporal propio en el mismo directorio del original y editar esa copia.
5. Reabrir la copia para comprobar los valores, metadatos ajenos y hashes del audio.
6. Conservar y comprobar permisos y atributos según la plataforma.
7. Revalidar el original y el catálogo y registrar el hash posterior antes de publicar.
8. Sincronizar la copia, reemplazar el original y registrar el resultado.
9. Confirmar las observaciones en SQLite sin reimportar todo el archivo.

Los respaldos se conservan en
`<carpeta del audio>/.trackfolio-backups/<operación>/<id>-<nombre>.tfo-bak`.
Los temporales terminan en `.tmp`; ninguno se reimporta como música. No se utilizan
hardlinks como respaldo. Tras confirmar y registrar todo el lote correctamente,
sin errores ni cancelación, se elimina el directorio `.trackfolio-backups` completo
de cada carpeta afectada, con todos los UUID que contenga. Ante errores se conservan
las copias. Si falla la limpieza, se informa y se mantienen las rutas aún existentes.
La [guía](tag-writing.md) registra los límites de ACL, atributos y streams por plataforma.

La atomicidad es por archivo, no por lote ni entre música y SQLite. La revalidación
no constituye un compare-and-swap portable frente a otros programas que editen música.
Si una copia no se puede verificar o preservar, no se publica.

## SQLite, cancelación y errores

La instantánea incluye los valores musicales y `raw_tags`. La confirmación compara
esa instantánea bajo transacción y actualiza solamente las observaciones y la fecha
física afectada. No sustituye correcciones nuevas ni otros registros, roles o carátulas;
se aíslan las pistas y álbumes compartidos cuando hace falta.

El registro `Trackfolio/tag-writes/<id>/journal.json` conserva rutas, selección, cambios,
hashes, respaldos y estados. Se escribe mediante temporal, reemplazo y sincronización.
Si el archivo se publicó y la confirmación falla, queda como **catálogo pendiente**;
no se informa que el original quedó intacto ni se restaura a ciegas.

**Cerrar** durante un trabajo solicita cancelación cooperativa y espera a un punto
seguro antes de cerrar. Se conserva lo ya publicado. Los errores aislados permiten
continuar con los demás archivos; perder el catálogo o el registro y los fallos
esenciales de almacenamiento detienen los restantes. La ventana mantiene su respuesta.

La salida muestra resultados por archivo: escrito, catálogo pendiente, sin cambios,
no escribible, conflicto, fallido o pendiente. Los errores ofrecen exportación en un
pop-up; cancelar o finalizar sin errores no abre ese pop-up. Los registros y respaldos
permiten recuperación manual. El núcleo conserva `ReviewTagWrites` para inspeccionar
hashes y confirmar observaciones mediante sus contratos; no hay pantalla de recuperación
ni escrituras/restauraciones automáticas al iniciar la GUI.

## Componentes y aceptación

| Componente | Responsabilidad |
| --- | --- |
| `domain/tag_write.py` | Solicitudes, instantáneas, diferencias, estados, progreso e informe. |
| `application/write_tags.py` | `TagWriteService.execute` prepara todos los cambios y escribe; contratos sin Qt/ORM/Mutagen. |
| `infrastructure/tag_write.py` | Modificación Mutagen y verificación de audio, bloques y frames. |
| `infrastructure/tag_write_files.py` | Rutas, hashes, copias exclusivas, publicación, atributos y registros. |
| `infrastructure/tag_write_catalog.py` | Confirmación parcial con comparación de instantánea en SQLite. |
| `application/album_nfo.py` | Preparación, agregación, publicación y revisión de NFO mediante contratos. |
| `infrastructure/album_nfo.py` | Edición y verificación del XML, conservando contenido ajeno. |
| `interfaces/gui/tag_write_dialog.py` | Listado fijo, progreso, dos botones y pop-up de informe ante errores. |

Se reutilizan los casos internos de preparación, escritura y revisión técnica, sin
exponer su granularidad en la GUI. El esquema `002` y las dependencias no cambian.

La aceptación verifica:

- Editar → guardar → escribir → importar en otro catálogo y recuperar los diez campos.
- Eliminaciones, Unicode, listas, fechas, numeración y USLT, sin cambiar metadatos ajenos.
- Hash del audio real y conservación de imágenes, bloques, frames desconocidos y APEv2.
- Fallos antes/después de publicar, espacio insuficiente, archivos modificados, permisos,
  bloqueos, enlaces, cancelación e interrupción real del proceso con registro durable.
- Listado completo desde la apertura, escritura directa sin revisión, salida de progreso,
  cierre diferido y oferta de informe únicamente ante errores.
- Ruff, formato, mypy, pytest, diagnóstico, núcleo sin Qt y wheel fuera del checkout.
- Matriz Linux, Windows y macOS Intel/Apple Silicon, registrando por separado la revisión
  visual manual de escritorios y los resultados automáticos `offscreen`/nativos.

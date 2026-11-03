# Plan de incrustación de miniaturas al escribir etiquetas

Estado: propuesta pendiente de implementación, del 3 de noviembre de 2026.
Trabajo previsto sobre la rama local activa `thumbnail`, sin crear ramas ni publicar cambios.

## Resultado esperado

Al pulsar **Escribir etiquetas** en el diálogo de selección o de todo el catálogo,
buscar imágenes en la carpeta de cada canción destinataria e incrustar la elegida
como portada frontal en sus FLAC/MP3. Sustituir la portada frontal que ya contengan.
La operación también funcionará cuando no haya diferencias en las etiquetas de texto.
**Guardar** seguirá guardando las ediciones del catálogo sin modificar la música.

| Imágenes encontradas en la carpeta | Comportamiento |
| --- | --- |
| Ninguna | Escribir los cambios de texto/NFO que correspondan y conservar la portada incrustada actual. Si no tiene portada, seguirá sin ella. |
| Una | Utilizarla automáticamente, aunque ya exista otra portada incrustada. |
| Varias | Preguntar qué imagen usar antes de iniciar la publicación de archivos. Una elección por carpeta, compartida por sus canciones destinatarias. |

Se considerarán `.jpg`, `.jpeg` y `.png`, sin distinguir mayúsculas en la extensión.
Un único PNG tendrá el mismo tratamiento automático que un único JPG. No se dará
preferencia silenciosa a `album.jpg`, `folder.jpg` u otro nombre si hay varias imágenes.

La búsqueda se limita a la misma carpeta del audio, sin recorrer subcarpetas ni
carpetas superiores. No se utilizará como sustituto la miniatura de SQLite ni una
referencia `thumb` del NFO. La imagen original se lee sin modificarla ni renombrarla.
No se descargan imágenes ni se convierten JPEG a PNG o viceversa.

## Elección de imagen y cancelación

1. Resolver los borradores pendientes mediante Guardar/Descartar/Cancelar, como ahora,
   y congelar los identificadores de las canciones destinatarias.
2. Explorar las carpetas en un trabajador, agrupando por directorio físico y
   normalizando las raíces que sean alias, con las mismas reglas que la escritura NFO.
3. Si hay carpetas con varias imágenes, mostrar un diálogo Qt con sus candidatos:
   nombre, vista previa y dimensiones. Exigir una selección explícita en cada carpeta
   o permitir **Conservar portada actual** para omitir la imagen de esa carpeta.
4. Para un catálogo con muchas carpetas, presentar las elecciones en un mismo diálogo
   organizado por carpeta. No preguntar por cada canción ni bloquear el trabajador
   esperando a que Qt responda.
5. Confirmar las elecciones y preparar la escritura de texto, imágenes y NFO. Revalidar
   el inventario y los archivos elegidos antes de publicar.

Cancelar o cerrar el selector cancela ese intento completo antes de crear respaldos
o publicar música/NFO. Se podrá volver a intentarlo desde el diálogo principal.
Durante la exploración y publicación, **Cerrar** conservará la cancelación cooperativa
actual. La selección de portada será válida para ese intento; no se guardarán
preferencias implícitas para futuras operaciones.

Con selección parcial, sólo se incrustará la imagen en las canciones destinatarias.
Las pistas no seleccionadas de la misma carpeta no se escribirán. La agregación NFO
de álbum seguirá consultando las pistas necesarias sin ampliar esa selección musical.

## Significado de sobrescribir la miniatura

La imagen elegida sustituirá las imágenes marcadas como **portada frontal**, dejando
exactamente una portada frontal. Se conservarán contraportadas, libretos y otros
tipos de imágenes, con sus bytes, atributos y descripciones. Si antes sólo había una
imagen de otro tipo, se añadirá la frontal elegida y el lector la priorizará.

| Formato | Escritura propuesta |
| --- | --- |
| FLAC | Bloque `PICTURE` frontal, con los bytes originales de la imagen y su MIME/dimensiones. Conservar los demás bloques e imágenes. |
| MP3 | Frame `APIC` de tipo frontal, conservando la versión ID3 admitida. Evitar colisiones de descripción con imágenes de otros tipos. |

Estas representaciones corresponden a las APIs de
[FLAC Picture](https://mutagen.readthedocs.io/en/latest/api/flac.html#mutagen.flac.Picture)
y [ID3 APIC](https://mutagen.readthedocs.io/en/latest/api/id3_frames.html#mutagen.id3.APIC)
de Mutagen. No se recodifica el audio. Se mantienen las restricciones actuales sobre
versiones ID3 y archivos que no puedan preservarse de forma verificable.

Si ya hay exactamente una portada frontal con los mismos bytes y MIME, no es
necesario reemplazar el archivo sólo por esa imagen. Dos frontales duplicadas sí
requieren normalización. El segundo intento, sin cambios posteriores, será idempotente.

**Ninguna imagen** y **Conservar portada actual** significan ausencia de una petición
de cambio de portada; nunca una orden de borrarla. Este caso debe representarse
explícitamente en el dominio y no confundirse con una imagen vacía.

## Preparación de la fuente y comprobaciones

Añadir un adaptador de descubrimiento/lectura de imágenes independiente de Qt.
Reutilizar, extrayéndolo a un helper compartido si conviene, el reconocimiento JPEG/PNG
actual de `infrastructure/metadata.py`. Obtener el tipo real y las dimensiones del
contenido, sin asumir que la extensión garantiza el formato. La GUI comprobará que
puede decodificar las vistas previas y señalará las imágenes que no pueda representar.

Proponer un máximo de **15 MiB por imagen**, además de comprobar que el bloque/frame
resultante cabe en su formato. Una imagen vacía, ilegible, con formato no admitido o
fuera de los límites será una incidencia; no se tratará como una carpeta sin imágenes
ni provocará el borrado de la portada existente. Se podrá elegir otra imagen u omitir
la portada de esa carpeta. Si la única imagen no es utilizable, las canciones de esa
carpeta quedarán bloqueadas para ese intento; otras carpetas podrán continuar.
Un fallo al explorar la carpeta también será una incidencia, no un resultado de cero imágenes.

Registrar ruta, identidad, tamaño, fecha y SHA-256 de la imagen seleccionada. Congelar
sus bytes para que todas las canciones de la carpeta reciban el mismo contenido.
Revalidar la fuente antes de cada publicación: si cambia, desaparece o se sustituye,
registrar conflicto y conservar las canciones aún no publicadas. Si cambia el inventario
entre exploración y elección, volver a resolverlo sin elegir automáticamente otro archivo.

Aceptar las raíces importadas que sean alias normalizados; conservar su representación
POSIX en las consultas SQLite. No seguir enlaces simbólicos/junctions de las imágenes
ni de directorios internos, ni permitir rutas fuera de la raíz importada.

## Integración con la escritura recuperable

La portada debe formar parte de la misma planificación y del mismo reemplazo que las
etiquetas de texto de cada canción. No realizar un segundo guardado directo sobre el
original después de que el escritor haya terminado.

1. Incorporar al plan musical una intención de portada separada de `EDIT_FIELDS`:
   conservar, utilizar imagen elegida o ya coincidente. Una diferencia de portada
   por sí sola debe convertir la canción en escribible.
2. Crear el respaldo completo y el temporal de audio mediante las primitivas actuales.
3. Escribir los cambios de texto y la portada en ese temporal.
4. Reabrirlo y comprobar directamente sus bloques `PICTURE`/frames `APIC`: tipo frontal,
   cantidad, MIME y hash de los bytes incrustados deben coincidir con lo planificado.
5. Verificar el hash del audio y los metadatos/imágenes ajenos. Adaptar las firmas de
   preservación para permitir exclusivamente el cambio frontal solicitado, sin
   excluir de la comparación todas las imágenes o todos los frames APIC.
6. Revalidar imagen fuente, original musical y catálogo; sincronizar y publicar una vez.
7. Confirmar en SQLite los datos observados, incluida la portada incrustada, y registrar
   el resultado. Procesar después el NFO de acuerdo con las condiciones actuales.
8. Limpiar los respaldos sólo tras finalizar correctamente el conjunto audio/portada/NFO.
   Errores, conflictos, catálogo pendiente o cancelación conservan las copias del lote.

La verificación no puede basarse sólo en `read_metadata(...).artwork`: ese lector puede
devolver `album.jpg` como alternativa aunque la incrustación haya fallado. Es necesario
demostrar que los bytes están dentro del archivo musical.

Ampliar la reserva de espacio para considerar el crecimiento de los archivos y los
respaldos: una portada se repite en cada canción, aunque se lea una vez por carpeta.
El informe distinguirá portada conservada, incrustada, sustituida, ya coincidente u
omitida por elección, y mostrará la ruta fuente sin contar imágenes como canciones.

Versionar la ampliación del registro persistente y admitir las versiones anteriores,
que no contienen intenciones de portada. Guardar ruta fuente, huella y resultado,
sin serializar imágenes en base64 dentro de `journal.json`. La revisión técnica usará
los hashes y respaldos de audio y seguirá sin restaurar ni reescribir automáticamente.

## Catálogo y miniatura mostrada

Ampliar la instantánea y `SqliteTagCatalog.confirm`: actualmente confirma `raw_tags`
y cambios de fecha, pero no reemplaza la imagen del catálogo.

Tras una publicación correcta, almacenar/reutilizar la imagen en `artworks`, actualizar
`cover_artwork_id`, marcar la procedencia como `embedded` y retirar la ruta alternativa
de esa canción. Refrescar el detalle para mostrar la portada recién incrustada.
La comparación de instantáneas también debe proteger cambios concurrentes de portada.

Si la portada del audio ya coincide pero la imagen de SQLite está desactualizada,
sincronizar sólo esa observación del catálogo, sin reemplazar de nuevo el audio.
Sin fuente elegida, conservar la portada física y los datos de imagen actuales.
Un fallo de confirmación posterior a la publicación seguirá siendo **catálogo pendiente**.

## Componentes y orden de ejecución

| Fase | Componentes | Resultado verificable |
| --- | --- | --- |
| 1. Contratos y descubrimiento | `domain/tag_write.py`, nuevo adaptador de imágenes y puertos de aplicación. | Inventarios y decisiones explícitas, sin Qt ni escritura musical. |
| 2. Elección GUI | `controller.py`, diálogo de escritura y selector de portadas. | Varias imágenes se resuelven antes de publicar, con cancelación segura. |
| 3. Codec y verificación | `infrastructure/tag_write.py`, reconocimiento compartido de imágenes. | FLAC/MP3 contienen la frontal elegida y conservan audio y otras imágenes. |
| 4. Coordinación y catálogo | `application/write_tags.py`, `tag_write_catalog.py`, `tag_write_files.py`, `startup.py`. | Escritura sólo de portada, respaldo, confirmación, informe y recuperación compatibles. |
| 5. Entrega | Pruebas, probe, workflow y documentación. | Validación local y matriz CI registradas con su estado real. |

No se prevé modificar el esquema SQLite: la tabla de imágenes y las referencias
por archivo ya existen. Mantener el núcleo libre de Qt y reutilizar las dependencias
actuales para la lectura básica de imágenes y la escritura musical.

## Pruebas y aceptación

- Cero imágenes: conservar una portada existente; mantener sin portada una canción
  que carece de ella. No utilizar la miniatura de SQLite como fuente implícita.
- Una imagen JPG o PNG: incrustarla automáticamente en FLAC/MP3, con y sin frontal
  previa, incluso sin diferencias de texto. Incluir `.jpeg` y extensiones en mayúsculas.
- Varias imágenes: elección explícita por carpeta, vista previa, varias carpetas en
  una operación, omisión voluntaria y cancelación antes de publicar cualquier archivo.
- Selección parcial: sólo se escriben las canciones destinatarias. La misma imagen
  se usa en todas las seleccionadas de esa carpeta; cada carpeta conserva su elección.
- Reemplazar frontales duplicadas conservando contraportadas, libretos, imágenes
  desconocidas y APIC con descripciones que puedan colisionar. Preservar ID3v2.3/v2.4.
- Leer los bloques/frames incrustados con Mutagen y comprobar sus bytes, sin depender
  de `album.jpg`, la carátula de SQLite ni la vista previa de Qt para acreditar el resultado.
- Imagen ilegible/no admitida, límites, enlaces, cambios de fuente/inventario, rutas
  Unicode, raíces con alias y formato de rutas Windows en SQLite.
- Fallos antes/después de publicar, espacio insuficiente, cancelación y catálogo
  pendiente; respaldos conservados y reintento que respeta la elección nueva.
- Idempotencia y actualización de SQLite cuando sólo su miniatura esté desactualizada;
  compatibilidad de registros antiguos y revisión tras interrupción real del proceso.
- Integración Qt en trabajadores, selector accesible, detalle refrescado, progreso e
  informe de errores. Ejecución con CP1252 simulado y codificaciones explícitas en fixtures.

Actualizar `docs/tag-writing.md`, `docs/tag-write-plan.md`, README y `VALIDATION.md` al
implementar. Ejecutar Ruff, formato, mypy, pytest y diagnóstico; validar también el wheel
instalado fuera del checkout, primero sin Qt y después con GUI. Ampliar el probe y CI
para comprobar la incrustación real y registrar por separado Linux, Windows y macOS,
además de cualquier revisión visual manual pendiente.

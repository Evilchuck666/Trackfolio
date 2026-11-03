# Plan de actualización opcional de album.nfo

Estado: implementado el 3 de noviembre de 2026 sobre la rama local `update-nfo`.
La [guía de escritura](tag-writing.md#actualización-opcional-de-albumnfo) describe el uso
y [VALIDATION.md](../VALIDATION.md) recoge la validación local y las plataformas pendientes.
Este documento conserva el diseño de la entrega. No se han creado ramas ni publicado cambios.
Corrección posterior: se amplía el alcance a los títulos `track/title` tras reproducir
el caso «To War! → To War!2» de un NFO con lista de pistas. La primera entrega sólo
sincronizaba los datos generales del álbum.

## Resultado esperado y alcance

Al ejecutar **Escribir etiquetas…** o **Escribir etiquetas de todo el catálogo…**,
comprobar si existe `album.nfo` en la carpeta de cada archivo musical destinatario.
Si existe, actualizar sus datos de álbum a partir del catálogo guardado. Su ausencia
es normal: no crear el fichero, no mostrar un error y continuar con las etiquetas.
**Guardar** seguirá afectando únicamente al catálogo.

Supuesto de esta propuesta: NFO XML de metadatos con raíz `<album>`, compatible con
las [convenciones de Kodi](https://kodi.wiki/view/NFO_files/Albums) y su
[plantilla de álbum](https://kodi.wiki/view/NFO_files/Templates#album.nfo_Template).
El repositorio no contiene ejemplos NFO para comprobar otro formato. Los NFO de texto,
de URL o combinados y las estructuras no compatibles se conservarán y producirán
una incidencia explicativa. No se intentará convertirlos.

La búsqueda inicial se limita al nombre `album.nfo` en la misma carpeta del audio,
respetando las reglas de nombres del sistema de archivos. No se buscará en carpetas
superiores: un NFO situado sobre subcarpetas de discos queda fuera de esta entrega.
Esto evita asociar automáticamente un álbum distinto por proximidad.

La comprobación se realizará aunque las etiquetas musicales ya coincidan con el
catálogo: un NFO desactualizado debe poder corregirse sin reescribir el audio.
Cada ruta NFO se procesará una sola vez por operación.

## Datos y resolución del álbum

La selección determina las carpetas que se examinan. Para obtener sus valores de
álbum, consultar todas las pistas catalogadas de cada carpeta, incluidas las no
seleccionadas. Esa consulta no amplía los destinatarios de escritura de audio.
No utilizar la primera canción ni el último archivo procesado como autoridad.

| Dato | Regla propuesta | Destino XML |
| --- | --- | --- |
| Álbum | Todos los registros de la carpeta deben tener el mismo valor guardado. | `title` directo de `album`. |
| Año | Todos deben coincidir, incluida la ausencia de año. | `year`; actualizar también el año de `releasedate` si existe. |
| Géneros | Unión sin duplicados exactos de los géneros de todas las pistas, ordenada por ruta relativa y orden de cada lista. | Un `genre` directo por valor. |
| Artistas del álbum | Usar créditos `album_artists` coincidentes; si todos carecen de ellos, aceptar los artistas de pista únicamente cuando sean idénticos en todas las canciones. | `albumArtistCredits/artist`; actualizar `artistdesc` si existe. |
| Título de canción | Actualizar sólo las canciones destinatarias, asociadas de forma única por posición y disco. | `track/title` de una lista existente. |

No dividir nombres por separadores ni equiparar mayúsculas, espacios o variantes.
Un valor vacío coherente elimina el elemento gestionado; no inventar año ni artista.
Si faltan artistas de álbum y los artistas de pista difieren, conservar los créditos
NFO existentes: puede ser una recopilación. Los demás campos se podrán actualizar.

Si hay títulos/años incompatibles, créditos de álbum contradictorios o audio de la
carpeta sin catalogar que impida comprobar su composición, conservar el NFO completo
y registrar un conflicto. No mezclar álbumes ni importar automáticamente nuevas pistas.
La detección de audio no catalogado reutilizará el reconocimiento FLAC/MP3 del proyecto.

Para `releasedate`, conservar mes/día si el cambio de año produce una fecha válida;
en caso contrario, usar solamente el año. Un año vacío elimina `year` y `releasedate`.
Conservar `originalreleasedate`, cuya semántica es distinta. Las correspondencias
de fechas se fijarán en pruebas con las variantes de la plantilla citada.

Los identificadores y datos enriquecidos de los créditos no deben reasignarse a otro
artista. Conservarlos si el nombre coincide; si el cambio requeriría asociar un ID
existente a otro nombre, dejar el NFO intacto y registrar conflicto. No inventar IDs.

## Modificación y preservación del XML

Crear un adaptador NFO independiente de Mutagen. Analizar el documento y modificar
exclusivamente los elementos gestionados, distinguiendo hijos directos del álbum
de elementos homónimos anidados. Añadir los campos gestionados ausentes cuando haya
un valor, y evitar duplicados de campos escalares.

Conservar reseñas, sellos, identificadores, imágenes, puntuaciones, campos desconocidos,
atributos, comentarios e instrucciones de procesamiento. No reconstruir el documento
desde una plantilla. En listas de pistas existentes, actualizar los títulos de las
canciones destinatarias conservando el resto de los datos, orden, numeración,
duraciones y líricas. Sin correspondencia única por posición/disco, registrar conflicto.
La conservación del contenido será semántica; una escritura puede normalizar el
escape y la representación XML. Conservar codificación declarada, BOM y saltos de
línea cuando el serializador lo permita; rechazar una codificación no soportada.

Limitar el tamaño de entrada a 16 MiB, rechazar DTD y declaraciones de entidades y
no resolver recursos externos. Un XML vacío, malformado, con raíz distinta o con una
estructura que no pueda conservarse quedará intacto y se comunicará como incidencia.
Sin diferencias semánticas, conservar exactamente los bytes y la fecha del NFO.

## Integración con la escritura recuperable

El flujo actual prepara canciones en `PreviewTagWrites`, publica y confirma cada
audio en `WriteTagWrites`, y elimina respaldos al terminar correctamente. Además,
`TagWriteService.execute` retorna directamente si no hay audio que escribir.
Estos puntos deben adaptarse conjuntamente para admitir operaciones sólo de NFO.

1. Preparar las diferencias de audio y descubrir/agrupar los NFO de todas las carpetas
   destinatarias. Obtener una instantánea de los valores que contribuyen a cada NFO,
   la composición de la carpeta y la huella del documento existente.
2. Registrar los trabajos de audio y NFO bajo la misma operación, antes de publicar.
   Cada NFO tendrá identidad propia basada en su ruta, sin inventar un `file_id`.
3. Mantener la publicación y confirmación actual de cada archivo musical.
4. Procesar una vez cada NFO después de sus audios destinatarios. Publicarlo sólo si
   todos ellos quedaron confirmados o sin cambios. Ante fallos, conflictos, exclusiones,
   catálogo pendiente o cancelación en ese grupo, dejar su NFO pendiente. Otros grupos
   independientes podrán continuar si no hay un error fatal.
5. Revalidar los valores musicales agregados y la composición de la carpeta antes
   de publicar. Comparar valores de negocio: las confirmaciones de audio cambian
   `raw_tags` y pueden cambiar identidades internas sin invalidar el álbum previsto.
6. Crear respaldo exclusivo del NFO, verificarlo, editar una copia temporal en su
   carpeta, reabrirla y verificar tanto cambios como contenido ajeno y atributos.
7. Revalidar identidad y hash del original, registrar el hash final, sincronizar y
   publicar mediante reemplazo en el mismo volumen. Registrar si el reemplazo ya
   ocurrió aunque falle una comprobación posterior.
8. Finalizar el informe conjunto y ejecutar la limpieza de respaldos únicamente
   cuando audio y NFO hayan terminado correctamente, sin incidencias ni cancelación.

Aplicar al NFO las restricciones existentes de raíz importada, enlaces simbólicos,
junctions, enlaces duros, permisos y conservación de atributos. Reutilizar las
primitivas de archivos mediante contratos genéricos, sin simular que el NFO es audio.
Incluir su tamaño en la reserva de espacio y usar nombres de respaldo/temporal que
no colisionen con los musicales. Un NFO que aparezca, desaparezca o cambie después
de prepararlo se tratará como conflicto; no sobrescribirlo silenciosamente.

Un fallo de NFO conservará sus bytes originales si todavía no se publicó, mantendrá
los respaldos del lote y permitirá continuar con otros álbumes. Los audios ya escritos
conservarán su resultado real. No hay una transacción conjunta ni reversión automática.
Pérdida de registro/catálogo y fallos esenciales de almacenamiento seguirán deteniendo
los trabajos pendientes.

## Contratos, registro e interfaz

| Componente | Cambio previsto |
| --- | --- |
| `domain/tag_write.py` | Añadir planes/resultados NFO y su colección separada en el informe, conservando los resultados musicales. |
| `application/write_tags.py` | Contratos para lectura agregada y codec NFO; coordinación por carpeta, operaciones sólo NFO y finalización conjunta. |
| `application/album_nfo.py` | Agregación, preparación, publicación y revisión técnica de los NFO mediante contratos. |
| `application/tag_write_errors.py` | Errores compartidos entre escritura musical y NFO, reexportados por `write_tags.py` para compatibilidad. |
| `infrastructure/album_nfo.py` (nuevo) | Análisis, diferencias, edición XML y verificación de preservación. |
| `infrastructure/tag_write_catalog.py` | Consultar y revalidar valores de todas las pistas de la carpeta, incluidos créditos de álbum. |
| `infrastructure/tag_write_files.py` | Primitivas compartidas, respaldo/publicación NFO, registro y limpieza conjunta. |
| `startup.py` | Componer el adaptador nuevo en el servicio. |
| `interfaces/gui/tag_write_dialog.py` | Describir la actualización opcional, mostrar progreso/resultados NFO y permitir reintento si fallan. |

Los resultados NFO distinguirán actualizado, sin cambios, ausente, pendiente,
conflicto y fallido; indicarán ruta, motivo y respaldo. Incluirlos en la salida, el
informe JSON y el cálculo de finalización, sin añadir filas ficticias de canciones
ni contarlos como audio escrito. Ausente y sin cambios serán resultados correctos.
Los errores ofrecerán el mismo pop-up de exportación ya existente.

Versionar la ampliación de `journal.json` y admitir los registros anteriores, que
carecen de NFO. Guardar valores previstos, huellas, rutas, estados y resultado de
publicación de cada NFO. Extender `ReviewTagWrites` para inspeccionarlos y distinguir
original intacto, publicación verificada y conflicto; la revisión seguirá sin
reescribir ni restaurar archivos. Un NFO fallido no permitirá cerrar la operación
como totalmente resuelta ni eliminar los respaldos pendientes.

El reintento reconstruirá el plan desde el estado actual. Si el audio ya coincide,
se omitirá y se intentará corregir sólo el NFO. No requiere cambios de esquema SQLite.

## Orden de implementación y aceptación

1. Definir contratos, agregación de valores y compatibilidad del registro.
2. Implementar el codec XML y verificar preservación con fixtures representativos.
3. Integrar descubrimiento, publicación, cancelación y limpieza conjunta.
4. Incorporar progreso, informe y reintentos en el diálogo existente.
5. Actualizar `docs/tag-writing.md`, `docs/tag-write-plan.md` y `VALIDATION.md` con el
   comportamiento implementado y las comprobaciones realmente ejecutadas.

Añadir `tests/test_album_nfo.py` y ampliar las pruebas de escritura, limpieza y GUI:

- NFO ausente, válido, ya actualizado, no compatible y malformado; entidades/DTD y límite.
- Actualización de título, año/fecha, artistas y géneros; vaciados, Unicode y XML escapado.
- Conservación de campos ajenos, comentarios, atributos, IDs y listas de pistas anidadas.
- Corrección «To War! → To War!2» en `track/title`, con audio pendiente y ya actualizado;
  selección parcial, títulos vacíos, discos distintos y posiciones ausentes/ambiguas.
- Varias canciones comparten un NFO y sólo lo publican una vez; varias carpetas se aíslan.
- Selección parcial consulta todo el álbum sin escribir audio fuera de la selección;
  álbumes contradictorios y pistas sin catalogar producen conflicto.
- Audio sin diferencias con NFO pendiente; segunda ejecución idempotente sin reemplazos.
- Fallos antes/después del reemplazo, permisos, enlaces, espacio y cambios concurrentes
  en documento, catálogo o composición de carpeta.
- Fallo/cancelación de audio deja pendiente el NFO del grupo; fallo NFO conserva los
  resultados de audio y todos los respaldos; éxito conjunto permite la limpieza.
- Registro antiguo/nuevo, interrupción y revisión posterior; reintento sólo de NFO.
- Interfaz responsiva, estado final correcto e informe JSON con incidencias NFO.

Al implementar, ejecutar Ruff, comprobación de formato, mypy, pytest y diagnóstico del
proyecto; verificar el núcleo sin Qt y la integración GUI con el entorno disponible.
Validar permisos/reemplazos en Linux, Windows y macOS, registrando por separado lo
comprobado localmente y lo pendiente en otras plataformas.

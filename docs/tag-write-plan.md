# Plan de escritura de etiquetas FLAC y MP3

Estado: implementación funcional realizada el 2 de noviembre de 2026 y validada
localmente en Linux. La aceptación multiplataforma se registra por separado en
[VALIDATION.md](../VALIDATION.md); no se da por comprobada una plataforma sin su ejecución.
La [guía de uso, formatos y recuperación](tag-writing.md) describe el comportamiento
entregado. El resto del documento conserva el diseño y sus criterios de aceptación.

## Resultado y alcance

Editar y guardar los valores en el catálogo, seleccionar una o varias canciones y
pulsar **Escribir etiquetas…**. Revisar las diferencias entre los archivos y el
catálogo, elegir los campos y confirmar la escritura. Al importar esos archivos en
un catálogo nuevo se deben recuperar los valores escritos.

**Guardar** mantiene su comportamiento de edición de SQLite. La escritura musical
será una acción independiente y explícita, válida también tras editar en grupo.
Una selección múltiple utilizará los valores guardados de cada canción: escribir
etiquetas no uniformará por sí solo los títulos o la numeración.

La primera entrega cubrirá los diez campos editables actuales. No cambiará portadas,
artistas de álbum, rutas, nombres de archivo ni propiedades del audio. No añadirá
conversión de formatos, búsqueda de metadatos, sincronización automática ni deshacer
atómico de todo el lote. Los respaldos permitirán restauración manual documentada.

## 1. Qué se puede reutilizar y qué falta

- `CatalogEntry` conserva `library_root`, `relative_path` y los metadatos deseados.
  `EditableTrack` proporciona una instantánea para detectar cambios del catálogo.
- `read_metadata()` detecta FLAC/MP3 por contenido y ofrece una comprobación semántica
  independiente de Qt. Su normalización de alias deberá compartirse con el escritor.
- `raw_tags` conserva valores textuales, pero no todas las estructuras binarias,
  imágenes, frames desconocidos ni variantes de ID3. **No reconstruir un archivo a
  partir de las filas de SQLite**: abrir y modificar una copia del original completo.
- Las ediciones actuales preservan `raw_tags`. No existe un historial persistente de
  qué campos cambió el usuario ni una huella del archivo en la última importación.
  Por ello, la primera versión comparará el archivo actual con el catálogo y pedirá
  elegir los campos; no supondrá que toda diferencia procede de una edición local.
- El token de edición actual no incluye `raw_tags`. La confirmación del escritor
  necesitará una instantánea que cubra también esas observaciones y la identidad del
  catálogo, para no reemplazar una lectura más reciente realizada por otra operación.
- No existen escritor musical, vista previa, respaldo de audio ni recuperación de
  operaciones interrumpidas. El respaldo existente protege migraciones de SQLite.

No se prevén dependencias nuevas. Mutagen ya pertenece al núcleo. El esquema `002`
puede mantenerse: las operaciones pendientes se registrarán fuera de SQLite y las
observaciones textuales seguirán utilizando `raw_tags`.

## 2. Solicitud y vista previa

Antes de preparar la vista previa, resolver los cambios sin guardar mediante
**Guardar / Descartar / Cancelar**. No escribir un borrador que todavía no esté
confirmado en SQLite. Congelar la selección y la identidad del catálogo para la
operación; nunca recalcular los destinatarios desde la selección que haya después.

La vista previa tendrá una fila por archivo y detalle por campo con:

- Ruta, formato y versión de etiquetas detectados.
- Valor actual del archivo y valor guardado en el catálogo, incluidas listas ordenadas.
- Diferencias, eliminaciones explícitas y etiquetas físicas adicionales afectadas.
- Estado: sin cambios, listo, conflicto o no escribible, con su motivo.
- Tamaño estimado de las copias y ubicación de los respaldos.

Ofrecer casillas de campos, inicialmente sin marcar. Al marcar un campo se aplicará
el valor particular de cada canción; las filas sin diferencias efectivas se omitirán.
Un valor vacío marcado significa **borrar**, no conservar. Mostrar claramente el
número de archivos y campos que se borrarán antes de habilitar **Escribir etiquetas**.

Un archivo ausente no impide editar SQLite. En la vista previa aparecerá como no
escribible. Permitir excluirlo y confirmar el subconjunto válido, sin ocultar sus
incidencias ni resolver automáticamente una biblioteca trasladada a otro equipo.

La comparación parte del archivo tal como está ahora: un cambio externo anterior a
la vista previa se mostrará como diferencia. Los cambios posteriores invalidarán esa
vista previa y exigirán revisarla de nuevo para ese archivo.

## 3. Correspondencia y reglas por formato

| Campo del catálogo | FLAC: Vorbis comments canónicos | MP3: ID3v2 |
| --- | --- | --- |
| Canción | `TITLE` | `TIT2` |
| Artistas | Valores repetidos de `ARTIST` | Lista de `TPE1` |
| Álbum | `ALBUM` | `TALB` |
| Año | `DATE`, con tratamiento de fecha descrito abajo | `TDRC` en v2.4; representación de fecha de v2.3 |
| Pista / total | `TRACKNUMBER` / `TRACKTOTAL` | Par `TRCK` |
| Disco / total | `DISCNUMBER` / `DISCTOTAL` | Par `TPOS` |
| Géneros | Valores repetidos de `GENRE` | Lista de `TCON` |
| Líricas | `LYRICS` | `USLT`, identificado por idioma y descripción |

Las reglas siguientes son decisiones de esta entrega:

1. **Campos omitidos:** conservar sus valores y estructuras originales. No vaciar
   todas las etiquetas y volverlas a crear. No incrustar la imagen `album.jpg`.
2. **Alias:** inventariar todos los que reconoce el lector, incluidos `TXXX`, totales
   separados y nombres alternativos de líricas. Al modificar un campo, actualizar o
   retirar únicamente su familia de alias para que una etiqueta antigua no prevalezca
   al releer. Incluir esas retiradas en la vista previa y comprobarlas en las pruebas.
3. **Nombres múltiples:** conservar orden, Unicode y nombres completos. No dividir
   ni unir silenciosamente por comas, punto y coma o `/`.
4. **Numeración:** al modificar una mitad de `TRCK` o `TPOS`, conservar la otra desde
   el archivo, aunque el catálogo tenga otra corrección pendiente en ese campo.
   Probar número sin total y total sin número; la representación de total sin número
   deberá volver a leerse como `(None, total)`. Si no es representable fielmente,
   bloquear esa combinación. Aplicar la misma regla a alias FLAC con pares `n/total`.
5. **Año y fecha:** conservar la fecha física si su año ya coincide. Si cambia el año,
   conservar mes/día y demás precisión solo cuando la fecha resultante sea válida y
   representable. Para vaciar el año o resolver, por ejemplo, un 29 de febrero inválido,
   exigir una decisión explícita en la vista previa: omitir ese campo o reemplazar la
   fecha por el año confirmado/eliminarla. Mostrar la fecha completa antes y después.
   Serializar los años con cuatro dígitos y mantener el rango 1–9999 del editor.
6. **Líricas:** conservar el idioma y la descripción si hay una sola entrada `USLT`.
   Crear una entrada sin descripción y con idioma `und` cuando no exista. Si hay varias
   entradas, pedir cuál actualizar o borrar; no eliminar versiones de otros idiomas.
   Un alias textual que tenga prioridad en el lector también debe resolverse en la vista.
7. **ID3:** conservar v2.3 o v2.4 cuando sea posible; crear v2.4 si no hay etiquetas.
   No convertir versiones ni elegir separadores con pérdidas automáticamente. Las
   combinaciones que no preserven las listas, frames o etiquetas legadas deben quedar
   no escribibles, con explicación. La primera entrega no convertirá ID3v2.2 ni
   modificará archivos con ID3v1 coexistente hasta tener una política y pruebas de
   preservación por campo; estos casos se comunicarán como incompatibles, no como éxito.

Mutagen permite guardar comentarios FLAC y ofrece controles específicos para ID3.
Su comportamiento por defecto puede convertir a v2.4 y unir valores al guardar v2.3;
la implementación deberá configurar y verificar esas operaciones expresamente.
Fuentes: [FLAC](https://mutagen.readthedocs.io/en/latest/api/flac.html),
[versiones de ID3](https://mutagen.readthedocs.io/en/latest/user/id3.html) y
[API de ID3](https://mutagen.readthedocs.io/en/latest/api/id3.html).

La fase inicial de prototipos deberá cerrar la matriz exacta de versiones y casos
escribibles antes de conectar la acción a archivos del usuario. No se anunciará una
compatibilidad más amplia que la probada.

## 4. Rutas, copias y escritura de un archivo

Resolver la ruta desde la raíz de biblioteca y su ruta relativa. Reutilizar las reglas
de pertenencia a la raíz y rechazo de enlaces/junctions, comprobándolas de nuevo antes
de publicar. Rechazar archivos no regulares, rutas que escapen de la raíz y enlaces
duros detectados: reemplazar uno puede separar identidades compartidas inesperadamente.
Deduplicar destinos físicos; si dos entradas proponen valores incompatibles para el
mismo archivo, exigir resolver el conflicto.

Registrar identidad del archivo, tamaño, `mtime_ns` y SHA-256 completo; tamaño y fecha
no bastan por sí solos. Calcular hashes mediante streaming, con progreso y cancelación.
Guardar también las instantáneas relevantes del catálogo y la huella de la selección
de campos confirmada. No bloquear SQLite durante las copias o el cálculo de hashes.

Secuencia por archivo:

1. Revalidar archivo, permisos del archivo y del directorio, catálogo y solicitud
   confirmada. Respetar un original de solo lectura aunque su directorio admita reemplazos.
2. Crear un respaldo completo y exclusivo, comprobar que su hash coincide con la vista
   previa y conservarlo aunque termine bien la operación. Si no se puede crear o
   verificar, no tocar el original.
3. Crear desde ese respaldo verificado una copia temporal en el mismo directorio/volumen
   del original. Editarla mediante Mutagen, cerrar los manejadores y volver a abrirla
   para verificar contra el respaldo.
4. Comprobar valores seleccionados, metadatos no seleccionados, imágenes y estructuras
   ajenas. Verificar que los segmentos de audio conservan su hash; no usar solamente
   duración o el MD5 declarado de FLAC como prueba de integridad.
5. Conservar permisos y atributos que soporte la plataforma. Si no se pueden conservar
   atributos relevantes de ese archivo, detenerlo antes del reemplazo. El cambio de
   tamaño/fecha de modificación propio de la escritura es esperado.
6. Revalidar la identidad y el hash del original y registrar de forma persistente la
   intención de reemplazo junto con el hash esperado del temporal.
7. Sincronizar el temporal a disco y publicarlo con un reemplazo del sistema operativo.
   Sincronizar el directorio cuando se admita, comprobar el resultado y registrar el
   estado confirmado antes de continuar.
8. Actualizar la observación del archivo en el catálogo según la sección siguiente.

Backups propuestos: `<carpeta del audio>/.trackfolio-backups/<operación>/` con nombres
como `01.flac.tfo-bak`. Temporales con sufijo `.tmp`. Ninguno terminará en `.flac` o
`.mp3`, para que el explorador actual no los importe como canciones nuevas. No usar
enlaces duros como respaldo. Mostrar sus rutas en el informe y no borrarlos
automáticamente; limpiar solo temporales propios que ya no sean necesarios.

El reemplazo debe usar el mismo sistema de archivos. No presentar el conjunto de
archivos ni SQLite como una transacción global. Tampoco prometer que la comprobación
previa impida todas las carreras con programas externos: los bloqueos cooperativos
y la revalidación reducen ese riesgo, pero no constituyen un compare-and-swap portable.
Probar la publicación y los bloqueos reales en Windows y sistemas locales soportados.
Referencia: [os.replace en Python 3.13](https://docs.python.org/3.13/library/os.html#os.replace).
No asumir que `copy2` conserva todos los metadatos del sistema: documentar y comprobar
sus límites de propietario, ACL, atributos y streams por plataforma, según la
[documentación de shutil](https://docs.python.org/3.13/library/shutil.html#shutil.copy2).

## 5. SQLite, resultados parciales y recuperación

No reutilizar `CatalogRepository.save()` ni reimportar automáticamente todo el archivo:
eso podría reemplazar otras correcciones guardadas en el catálogo que no se eligieron
para escribir. Añadir una operación de confirmación con comparación de instantánea que:

- Actualice `raw_tags` del `file_id` con la última lectura verificada.
- Registre la fecha física resultante si escribir el año obligó a modificarla,
  conservando los demás campos y aislando álbumes/pistas compartidos cuando proceda.
- Preserve todas las correcciones musicales no incluidas en la operación, así como
  otros archivos, roles de artista y carátulas del catálogo.

Si cambia el catálogo entre la escritura y esa confirmación, no sobrescribir la nueva
edición ni restaurar el audio a ciegas: informar **archivo escrito / catálogo pendiente**.
No abrir un escritor ni migrar SQLite durante la vista previa. Al ejecutar, comprobar
primero el acceso y preparar una revisión antigua con el respaldo existente, antes de
publicar archivos musicales.

Crear un registro persistente de operación en la carpeta de datos de usuario,
`tag-writes/<id>/journal.json`, con ubicación e identidad del catálogo, rutas, cambios
confirmados, hashes, respaldos y estado de cada archivo. Actualizarlo mediante escritura
temporal y reemplazo, con sincronización a disco cuando la plataforma lo permita.
Crear el registro y reservar los nombres propios de respaldo/temporal antes de copiar.
Si falla el registro antes de publicar, detener la operación.

Estados mínimos: pendiente, respaldo verificado, temporal verificado, publicación
pendiente, archivo escrito, catálogo confirmado, omitido, conflicto y fallido. Un fallo
después de reemplazar no se confundirá con «no se escribió»; conservar la intención
previa permite resolver ese intervalo después de un cierre inesperado.

Al iniciar, detectar operaciones incompletas y mostrar su estado. Comparar el archivo
con los hashes anterior y posterior: confirmar lo ya publicado, descartar temporales
no publicados o marcar conflicto si no coincide. Reconciliar SQLite solo si su
instantánea sigue siendo válida. No reanudar escrituras, restaurar backups ni borrar
evidencias automáticamente; la revisión del usuario precederá a cualquier nueva escritura.

Cada archivo constituye una unidad independiente. Cancelar conserva los ya escritos,
abandona los pendientes y espera a que el archivo en curso llegue a un estado seguro.
Ante fallos aislados continuar con los demás; ante pérdida del catálogo, del registro
de operación o de almacenamiento esencial, detener el lote y mostrar resultados parciales.

El informe distinguirá archivos escritos y confirmados, escritos con catálogo pendiente,
sin cambios, excluidos/no compatibles, conflictos, fallos y pendientes por cancelación.
Permitirá copiar o exportar rutas, errores y ubicaciones de respaldo para recuperar una
operación aunque la interfaz se cierre.

## 6. Contratos y distribución del código

| Componente propuesto | Responsabilidad |
| --- | --- |
| `domain/tag_write.py` | Plan inmutable por archivo/campo, huellas, progreso, estados e informe. |
| `application/write_tags.py` | `PreviewTagWrites`, `WriteTagWrites` y revisión de operaciones pendientes; validación y coordinación sin Qt/ORM/Mutagen. |
| Contrato de catálogo | Obtener la selección guardada, comprobar instantáneas y confirmar observaciones sin reimportación completa. |
| Contrato de escritor | Inspeccionar formato, preparar copia editada y verificar preservación y audio. |
| Contratos de archivos y registro | Resolver rutas, respaldar, publicar, registrar estados y limpiar temporales propios. |
| `infrastructure/tag_write.py` | Adaptadores Mutagen FLAC/ID3, correspondencias y verificación por formato. |
| `infrastructure/tag_write_files.py` | Copias, hashes, identidades, publicación y registro persistente. |
| `infrastructure/catalog_edit.py` o adaptador específico | Confirmación parcial y transaccional de la observación del archivo. |
| `interfaces/gui/tag_write_dialog.py` | Vista previa, selección de campos, progreso y resultados. |

Los contratos públicos utilizarán tipos Python y permitirán otras interfaces futuras.
Procesar secuencialmente, con consumo acotado de memoria y un único lote activo.
La verificación de audio necesitará identificar correctamente los segmentos FLAC y
MPEG excluyendo etiquetas, incluidos encabezados y etiquetas finales; cubrir ese
análisis con pruebas específicas en vez de depender de atributos privados de Mutagen.

En la GUI, añadir la acción junto a Editar y conectarla desde `startup.py`. Preparación
y ejecución irán en trabajadores; los widgets solo recibirán resultados y progreso.
Deshabilitar selección, importación, cambio de catálogo y edición durante la ejecución.
Mantener la ventana receptiva, ofrecer cancelación cooperativa y diferir el cierre.
Al finalizar, refrescar las observaciones y conservar los `file_id` seleccionados.

## 7. Orden de implementación y aceptación

1. **Prototipos y matriz de formatos.** Probar escrituras y relecturas con la versión
   bloqueada de Mutagen: listas, alias, fechas, totales sin número, USLT y preservación
   de frames/bloques. Documentar los casos incompatibles y la segmentación del audio.
2. **Contratos y vista previa del núcleo.** Solicitud por selección/campos, diferencias,
   eliminaciones, incompatibilidades y conflictos, sin escribir audio, catálogos ni backups.
3. **Adaptadores por formato.** Editar únicamente copias temporales, verificar audio
   y etiquetas y demostrar preservación de información no editada.
4. **Publicación recuperable.** Respaldos, registro persistente, revalidación, reemplazo,
   confirmación selectiva en SQLite y recuperación tras interrupciones.
5. **Orquestación por lote.** Progreso de lectura/copia/escritura/verificación,
   cancelación, conteos exactos y resultados parciales. No confundir éxito de archivo
   con éxito de catálogo ni iniciar escrituras con una vista previa caducada.
6. **GUI.** Resolver borradores, seleccionar campos y archivos, revisar y confirmar,
   ejecutar, cancelar/cerrar y exportar el informe. Usar selección múltiple existente.
7. **Entrega portable.** Pruebas, documentación, paquete instalado y matriz de CI.

Pruebas necesarias:

- Ida y vuelta de los diez campos, vaciados, listas ordenadas, Unicode y nombres con
  separadores literales. Alias en conflicto, fechas completas, año 1/9999 y año bisiesto.
- FLAC con varias imágenes, comentarios adicionales y otros bloques; MP3 v2.3/v2.4,
  varias USLT, APIC, TXXX, ReplayGain, identificadores y frames desconocidos.
- Rechazo explícito de casos legados o multivaluados que no puedan preservarse.
- Hash del audio antes/después y comprobación de etiquetas no editadas; incluir
  muestras pequeñas redistribuibles con audio válido además de los contenedores sintéticos.
- Archivo ausente, corrupto, sin permisos, bloqueado en Windows, enlaces/junctions,
  enlaces duros, destinos duplicados y archivos cambiados después de la vista previa.
- Falta de espacio y fallos al copiar, verificar, registrar, reemplazar, cerrar o
  confirmar SQLite. Original intacto antes de publicar y respaldo siempre disponible.
- Interrupción del proceso en cada transición del registro, especialmente entre el
  reemplazo y su confirmación. Recuperación sin duplicar escrituras ni perder evidencias.
- Correcciones no seleccionadas conservadas, pistas/álbumes compartidos y conflicto
  del catálogo después de haber escrito un archivo.
- GUI con uno y varios archivos, cero cambios, borradores, progreso, cancelación,
  cierre y respuestas tardías. Esperar eventos finales, no estados intermedios de reposo.

Criterio principal: **editar → guardar catálogo → escribir campos elegidos → importar
en un catálogo nuevo → comprobar los valores escritos**, preservando audio e información
no elegida. Las correcciones que deliberadamente no se escribieron seguirán siendo
locales al catálogo original y podrán perderse al reimportar, como ocurre actualmente.

Ejecutar Ruff, formato, mypy y pytest con dependencias bloqueadas; mantener el núcleo
sin Qt y probar el wheel fuera del checkout. Ampliar el diagnóstico para un ciclo de
escritura sobre muestras temporales. Comprobar Windows, Linux y macOS Intel/Apple Silicon
en CI y registrar la revisión visual nativa por separado de `offscreen`.

Al implementar, actualizar README, arquitectura, modelo del catálogo, planes de edición
e importación y VALIDATION. Marcar esta entrega como completada solo cuando el flujo
entero, la recuperación y las comprobaciones anteriores estén terminados.

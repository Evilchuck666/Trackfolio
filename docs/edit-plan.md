# Plan de edición de canciones en la GUI

Estado: propuesto el 9 de octubre de 2026; pendiente de implementación.

## Resultado y alcance

Seleccionar una canción, pulsar **Editar**, modificar sus campos y confirmar con
**Guardar**. La lista y el detalle mostrarán los valores guardados; cerrar y volver a
abrir el catálogo conservará la edición. **Cancelar** recuperará los valores anteriores.

Este plan toma como primera entrega la **edición del catálogo SQLite**. Funcionará aunque
la música original no esté disponible. La escritura de etiquetas en FLAC/MP3 requiere
otro adaptador y un diseño de recuperación entre archivos y SQLite; queda fuera de esta
entrega. Esta decisión de alcance se puede cambiar antes de implementar.

La unidad de edición será la fila seleccionada, identificada por `file_id`. Por ejemplo,
cambiar **Abbath → Accept** reasignará el artista de esa canción al Accept existente,
conservando los créditos de las demás canciones y la identidad de ambos artistas.

| Campo actual | Edición y representación |
| --- | --- |
| Canción | Texto; vacío se guarda como `NULL`. |
| Artista(s) | Lista ordenada de nombres; selección de artistas existentes o creación de un nombre nuevo. |
| Álbum | Texto; vacío elimina el título, conservando los demás datos de álbum. |
| Año | Entero entre 1 y 9999, o vacío. |
| Pista y total de pistas | Enteros positivos, o vacío, de forma independiente. |
| Disco y total de discos | Enteros positivos, o vacío, de forma independiente. |
| Género(s) | Lista ordenada de nombres, o lista vacía. |
| Líricas | Texto plano, con sus saltos de línea; vacío se guarda como `NULL`. |

Son los diez campos que muestra actualmente el detalle. Fecha y artistas de álbum,
portada, rutas y propiedades técnicas conservarán sus valores. El año se tratará como
un dato explícito del catálogo: cambiarlo no reescribirá la fecha de álbum importada.
La edición por lotes, el renombrado global de artistas y la gestión de álbumes completos
quedan para entregas posteriores.

## 1. Reglas de edición y validación

- Guardar únicamente los campos modificados. Diferenciar un campo omitido de una
  solicitud de vaciarlo: `None` para escalares y tupla vacía para colecciones.
- Mantener el texto de los valores no vacíos, incluidos espacios, mayúsculas y Unicode.
  Un título, álbum o nombre compuesto exclusivamente de espacios se considerará vacío.
  Las líricas conservarán su contenido literal, sin interpretar HTML.
- Validar los números en el núcleo, además de facilitar su entrada en la GUI. Rechazar
  texto no numérico, fracciones, cero y negativos. Admitir número sin total y total sin
  número. Si ambos están presentes, exigir que el número no supere su total al modificar
  esa pareja; una inconsistencia previa no bloqueará una corrección de otro campo.
- Deduplicar nombres exactos en artistas y géneros, conservando su primera posición.
  No convertir mayúsculas ni añadir búsquedas aproximadas a la regla de identidad.
- Representar artistas y géneros mediante un control de lista, con acciones para añadir,
  quitar y ordenar. Cada elemento contendrá un nombre completo: no separar texto por
  comas o punto y coma, porque esos caracteres pueden formar parte del nombre.
- Preparar un borrador y cancelarlo no escribirá datos ni actualizará el esquema.
  Guardar sin cambios tampoco abrirá un escritor.

## 2. Contratos y casos de uso independientes de Qt

Crear `domain/catalog_edit.py` y `application/edit_catalog.py`. Mantener los contratos
de importación y consulta existentes; no convertir `TrackMetadata` en un formulario ni
utilizar `CatalogRepository.save()` para guardar el borrador.

| Contrato propuesto | Responsabilidad |
| --- | --- |
| `EditableTrack` | Instantánea del registro: `file_id`, valores editables y token de comparación. |
| `TrackEditPatch` | Campos modificados y sus valores tipados, incluidas las eliminaciones explícitas. |
| `ArtistChoice` | Nombre exacto y referencia opcional al artista existente. |
| `CatalogEditRepository` | Leer la instantánea, buscar artistas/géneros y aplicar un cambio atómico. |
| `CatalogEditSession` y su fábrica | Abrir y cerrar el acceso de edición a un catálogo existente. |
| `GetEditableTrack` | Obtener los valores del borrador, diferenciando los roles de los créditos. |
| `FindArtists` / `FindGenres` | Buscar sugerencias sin cargar detalles ni carátulas. |
| `UpdateCatalogTrack` | Validar y persistir el cambio; devolver detalle y resumen confirmados. |

Usar dataclasses inmutables, tuplas y errores de aplicación. El núcleo no importará Qt,
SQLAlchemy ni Mutagen. La GUI traducirá texto y selecciones a esos contratos, y el punto
de composición de `startup.py` inyectará los adaptadores.

Separar en la fábrica la apertura de lectura de la apertura del escritor. Obtener el
borrador o sugerencias usará conexiones de solo lectura; sólo un cambio válido y
efectivo solicitará el acceso de escritura y, si corresponde, la migración.

El token de comparación representará los valores musicales y relaciones relevantes,
sin incluir BLOBs ni objetos del ORM. Debe detectar cambios externos en el registro y
en su álbum, y mantenerse válido ante la consolidación de IDs de artista de `001 → 002`:
comparar nombres exactos, roles y posiciones, no los IDs redundantes que elimina esa
migración. La fábrica resolverá los nombres a los IDs vigentes al guardar.

Definir errores recuperables para datos inválidos, registro eliminado, conflicto de
edición y fallo de escritura. Los errores de validación identificarán el campo afectado.

## 3. Persistencia de una edición

Implementar un adaptador dedicado, por ejemplo
`infrastructure/catalog_edit.py`, reutilizando las tablas y helpers adecuados del
repositorio. El método actual `SqliteCatalogRepository.write()` reemplaza también
créditos, `raw_tags`, carátula y propiedades técnicas: no es la operación de edición.

Cada guardado se ejecutará en una única transacción:

1. Abrir el catálogo existente mediante `writable_engine`, con URI `mode=rw`, sin crear
   un archivo si desapareció. Reservar el escritor antes de releer y comparar el token.
2. Comprobar esquema, existencia del archivo y correspondencia con la instantánea.
   Ante un cambio externo, devolver conflicto antes de modificar datos.
3. Si varios archivos comparten `track_id`, copiar la pista y todas sus relaciones para
   el archivo seleccionado antes de editar. Su `file_id` se conserva; su `track_id`
   podrá cambiar. Los demás archivos seguirán vinculados a la pista original.
4. Aplicar los cambios escalares y resolver las relaciones afectadas.
5. Confirmar y devolver detalle y resumen coherentes. Un fallo en cualquier paso
   revertirá también las entidades o relaciones creadas dentro de la transacción.

### Artistas y géneros

Reutilizar la resolución de artistas por nombre exacto y el índice `uq_artists_name`.
Si existe Accept, utilizar su ID. Si el usuario introduce un nombre nuevo, crearlo al
guardar, con inserción protegida por el índice único. No modificar `artists.name` para
corregir el artista de una canción ni borrar entidades que queden sin referencias.

Cambiar **Artista(s)** sustituirá exclusivamente los créditos de rol `artist` de la
pista editada, con posiciones consecutivas. Conservar otros roles, como `composer`,
y todos los créditos de álbum. La consulta actual de detalle aplana los roles; el
editor tendrá una lectura específica y la presentación de **Artista(s)** y sus
resúmenes mostrará el rol `artist`, sin incluir compositores como intérpretes.
Los demás créditos seguirán almacenados y consultables en `track_details`.

Aplicar la misma reutilización exacta a géneros y conservar el orden de la lista.
No reescribir ninguna de estas relaciones si el campo correspondiente no cambió.

### Álbumes y total de discos

Un álbum puede estar compartido por muchas canciones. Cambiar título o año desde
una canción resolverá la agrupación resultante y reasignará únicamente su `album_id`.
No actualizar directamente la fila compartida ni dejar su `import_key` desfasada.

Extraer y compartir el cálculo de identidad de álbum usado en `_album_id()`: biblioteca,
directorio, título, fecha, año, total de discos y artistas de álbum. Si el álbum resultante
existe, reutilizarlo sin sustituir sus créditos. Si se crea, conservar también los roles
de álbum no editables. Si una agrupación existente tiene créditos adicionales
incompatibles, devolver un conflicto de agrupación y conservar el borrador, sin fusionar
los datos ni crear otra fila con el mismo `import_key`.

El total de discos mostrado procede de `tracks.disc_total`. Editarlo cambiará ese valor
en la pista seleccionada; no cambiará `albums.disc_total` ni completará otras pistas.
Para título/año, conservar fecha, total y créditos del álbum anterior. Vaciar el título
no elimina un álbum que aún tiene otros datos; si no queda ningún dato de álbum, usar
`album_id = NULL`.

### Esquema y catálogos anteriores

Esta entrega puede usar `002_unique_artists` sin añadir tablas: el token se obtiene de
una instantánea, no de una nueva columna. Conservar las revisiones y exportaciones SQL
actuales. Abrir catálogos `001_initial` para consultar o preparar un borrador seguirá
sin migrarlos.

El primer guardado efectivo sobre `001` reutilizará la validación, respaldo consistente
y actualización transaccional existentes. Revalidar el cambio después de migrar y
mostrar la ruta del respaldo. Un error de edición no aplicará parcialmente el borrador;
si la migración ya se confirmó, el catálogo podrá quedar actualizado a `002`, con la
copia anterior disponible. El acceso de edición tendrá una fábrica propia y no dependerá
del caso de uso ni del formulario de importación.

## 4. Interacción y estados de la GUI

Añadir **Editar**, **Guardar** y **Cancelar** al panel de detalle y sus acciones de
teclado: `Ctrl+E` en Linux/Windows y `Cmd+E` en macOS para Editar; el atajo estándar de
Guardar (`Ctrl+S` / `Cmd+S`) mediante `QKeySequence.StandardKey.Save`; `Escape` para
Cancelar. Mantener la tabla como selector; la edición se realizará en el detalle.
Usar los mismos recursos, estilos Fusion y controles Qt en Linux, Windows y macOS.

| Estado | Comportamiento |
| --- | --- |
| Sin selección o cargando | Edición deshabilitada. |
| Consulta | Campos de lectura; Editar disponible con detalle cargado. |
| Editando sin cambios | Campos habilitados, Guardar deshabilitado y Cancelar disponible. |
| Editando con cambios | Indicador «Cambios sin guardar» y Guardar disponible si los datos son válidos. |
| Guardando | Borrador y navegación bloqueados; estado «Guardando cambios…». |
| Error o conflicto | Borrador conservado y explicación visible; permitir corregir, reintentar o cancelar. |
| Guardado | Volver a consulta, actualizar resumen y detalle, conservar selección y confirmar el guardado. |

Guardar conservará el borrador hasta confirmar la transacción. Cancelar descartará el
borrador y releerá el registro para mostrar también los cambios externos, si los hubo.
Un conflicto ofrecerá recargar el registro o seguir revisando el borrador; no sobrescribirá
automáticamente datos externos.

Al cambiar de canción, abrir otro catálogo, actualizar la lista, importar o cerrar,
resolver antes los cambios pendientes con **Guardar / Descartar / Cancelar**. Guardar
continuará la acción solicitada sólo después de completarse con éxito; Descartar la
continuará sin guardar; Cancelar mantendrá selección y borrador. Con un borrador sin
cambios, salir del modo edición sin diálogo.

Modificar `_selection_changed()`: actualmente limpia el detalle antes de avisar al
controlador. La nueva navegación debe solicitar autorización al estado de edición
antes de limpiar los campos; si se cancela, restaurar la selección con señales bloqueadas.

El controlador conservará instantánea y borrador por catálogo y `file_id`. Las respuestas
de consultas anteriores, cambios programáticos de campos y búsquedas tardías de artistas
no marcarán el formulario como modificado ni reemplazarán un borrador activo.

## 5. Trabajo asíncrono, cierre e importación

- Ejecutar lecturas de edición, sugerencias y escritura fuera del hilo gráfico.
  Aplicar resultados sólo en el hilo Qt y comprobar sus identificadores de solicitud.
- Mantener un único escritor por ventana. Antes de guardar, invalidar las consultas
  incompatibles, esperar que terminen y liberar sus conexiones. Reutilizar el patrón de
  importación que espera también a `activeThreadCount()`, sin bloquear el bucle Qt.
- Liberar el escritor antes de volver a consultar. Distinguir «guardado confirmado»
  de un fallo posterior al refrescar la vista: éste no debe presentarse como pérdida de
  la edición ni provocar otra escritura automática.
- Durante el guardado, diferir el cierre hasta conocer el resultado. No terminar el
  trabajador a mitad de una transacción ni destruir sus objetos Qt mientras siga activo.
  Ante un fallo, mantener la ventana y el borrador para que el usuario decida.

**Reimportación:** esta entrega mantiene la política actual: volver a importar una ruta
relee sus etiquetas y reemplaza los valores del catálogo, incluidas las correcciones
manuales. El formulario de actualización indicará: «Se volverán a leer los metadatos de
los archivos y se sustituirán los valores del catálogo». El editor identificará el destino
como «Cambios en el catálogo» para que la operación resulte clara.

Conservar correcciones automáticamente frente a una reimportación necesitaría un modelo
de valores manuales por campo y una nueva migración; no se incorporará implícitamente a
este incremento. Las etiquetas originales almacenadas en `raw_tags` se mantendrán
intactas al editar y sólo se sustituirán cuando el importador relea el archivo.

Compartir la separación de pistas referenciadas por varios archivos con el escritor de
importación para que una actualización por ruta tampoco modifique archivos hermanos.
Se conservará `track_id` en el caso habitual de una pista por archivo; la excepción se
documentará y probará junto a la edición.

## 6. Comprobaciones y aceptación

| Nivel | Casos necesarios |
| --- | --- |
| Núcleo sin Qt | Patch parcial, borrado explícito, validación numérica, listas ordenadas, nombres exactos y edición sin cambios. |
| SQLite temporal | Abbath → Accept reutiliza su ID sin afectar otras canciones; artistas nuevos, múltiples y créditos con otros roles. |
| Relaciones | Álbum compartido, vaciado parcial de álbum, pista compartida y preservación de roles, géneros, portada, audio y `raw_tags`. |
| Concurrencia y fallos | Dos editores sobre la misma canción, registro eliminado, catálogo bloqueado, permisos y rollback sin escrituras parciales. |
| Compatibilidad | Edición sin música presente; lectura de `001` intacta, primer guardado con respaldo, repetición en `002` sin respaldo nuevo. |
| GUI real | Editar/Guardar/Cancelar, errores junto al campo, navegación con cambios pendientes, cierre y respuestas asíncronas atrasadas. |
| Integración | Guardar, cerrar y reabrir SQLite; lista y detalle coinciden; reimportar reemplaza la corrección según la política declarada. |

Añadir `tests/test_catalog_edit.py`, `tests/test_edit_gui.py` y
`tests/test_edit_gui_integration.py`; ampliar las pruebas existentes de consulta,
persistencia e importación donde cambie su comportamiento. Usar `Path` para rutas,
cerrar conexiones SQLite explícitamente y emplear un bucle Qt nativo para las esperas
asíncronas, conservando las correcciones recientes de Windows y macOS.

Ejecutar Ruff, formato, mypy y las suites pertinentes con `uv run --locked`. Comprobar
el núcleo sin PySide6, GUI con `offscreen`, wheel instalado fuera del checkout y la matriz
existente de Linux, Windows, macOS Intel y Apple Silicon. Si se añaden recursos visuales,
actualizar su manifiesto y la comprobación del paquete.

Revisar manualmente la ventana real con una copia del catálogo y un álbum compartido:
corregir una canción, vaciar valores, usar artistas múltiples, comprobar el teclado y
cancelar cambios. Registrar en `VALIDATION.md` qué plataformas y revisiones visuales se
ejecutaron, distinguiéndolas de las pruebas automatizadas. No usar la base personal para
pruebas que cambian o reimportan metadatos.

## 7. Orden de implementación

| Paso | Entrega | Criterio de cierre |
| --- | --- | --- |
| 1 | Valores, patch, contratos y validación del núcleo. | Casos de uso comprobados sin Qt. |
| 2 | Lectura específica, resolución de identidades y escritura transaccional. | Corrección por canción, aislamiento de relaciones y conflictos probados con SQLite. |
| 3 | Fábrica de edición, compatibilidad `001/002` y composición. | Guardar funciona sin audio y actualiza catálogos antiguos con respaldo. |
| 4 | Controles, listas de artistas/géneros y estado del borrador. | Editar, Guardar y Cancelar funcionan en los widgets reales. |
| 5 | Coordinación asíncrona, navegación, cierre e importación. | No se pierden borradores ni se aplican respuestas atrasadas; reimportación explícita y aislada por archivo. |
| 6 | Integración, paquete, matriz multiplataforma y documentación. | Comprobaciones superadas y evidencia registrada, con límites de revisión visual indicados. |

Al terminar, actualizar README, arquitectura y guía de base de datos para explicar
la edición de catálogo, su alcance por canción y el comportamiento al reimportar.
Marcar este plan como implementado únicamente después de completar esas comprobaciones.

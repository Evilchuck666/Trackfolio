# Plan de artistas únicos por nombre en el catálogo

Estado: implementado el 9 de octubre de 2026. Este documento conserva el diseño de la
entrega; las comprobaciones ejecutadas se registran en [VALIDATION.md](../VALIDATION.md).

## Regla acordada y resultado

Cada nombre de artista identifica una única entidad en todo el catálogo. Todas sus
canciones y álbumes comparten el mismo `artist_id`, también cuando proceden de distintas
carpetas o bibliotecas. Esta regla sustituye la reutilización limitada al álbum actual.

La comparación será por nombre exacto, igual que la reutilización actual de géneros.
Se conserva el texto leído: esta entrega no añade conversión de mayúsculas, eliminación
de espacios, búsqueda aproximada ni alias. `Accept` y `ACCEPT` seguirán siendo textos
distintos. La identidad se determina por `name`; `external_id` permanece como dato opcional.

Para corregir una canción de **Abbath** a **Accept**, se resolverá el identificador único
de Accept y se sustituirá el crédito de esa canción. La identidad y el nombre de Abbath
se conservarán para sus otros créditos. Este cambio prepara esa operación; la edición
de canciones en la GUI se implementará en otra entrega.

## Estado comprobado del catálogo de trabajo

La revisión de `data/database.tfo` se hizo exclusivamente en modo de lectura:

| Dato | Antes de la migración | Tras `002`, verificado |
| --- | --- | --- |
| Revisión | `001_initial` | `002_unique_artists` |
| Artistas | 13 filas | 2 filas |
| Abbath | 2 filas, IDs 1 y 2 | Una fila, ID 1 |
| Accept | 11 filas, IDs 3 a 13 | Una fila, ID 3 |
| Álbumes | 13 | 13, mismos IDs |
| Canciones y archivos | 139 y 139 | 139 y 139, mismos IDs |
| Créditos de pista y álbum | 139 y 0 | Mismo número, roles y posiciones |

Todos los `external_id` de esta muestra eran `NULL`. La tabla registra el punto de partida
del diseño; la comprobación de la migración figura en `VALIDATION.md`. La migración no
modifica archivos musicales.

## 1. Esquema vigente y unicidad

Añadir la revisión Alembic `002_unique_artists`, posterior a `001_initial`, y un índice
único global `uq_artists_name` sobre `artists.name`. Este índice proporciona la garantía
de unicidad sin reconstruir la tabla `artists` ni sus relaciones en SQLite.

Crear `src/trackfolio/infrastructure/schema.py` para el esquema vigente y su revisión.
Puede derivar las tablas del snapshot inicial mediante copias de su metadata y añadir
el índice nuevo. Los módulos de ejecución utilizarán este esquema vigente.

Conservar intactos el snapshot `migrations/initial_schema.py`, la revisión
`versions/001_initial.py` y `migrations/001_initial.sql`. Una instalación nueva ejecuta
`001` y después `002`; un catálogo existente se actualiza mediante la revisión nueva.

Adaptar la validación compartida del esquema para comprobar la revisión, estructura,
vista e índice único esperado: global, sin condición `WHERE`, sobre `name` con igualdad
exacta (`BINARY`). Un archivo marcado como `002` sin la garantía de unicidad
se rechazará como incompatible. Revisiones futuras desconocidas y bases ajenas seguirán
siendo rechazadas.

## 2. Consolidación de los datos existentes

La migración completa se ejecuta dentro de una transacción:

1. Agrupar las filas de `artists` por nombre exacto y elegir `MIN(id)` como ID canónico.
2. Conservar el `external_id` del canónico. Si es `NULL`, tomar el primer valor no nulo
   del grupo por orden de ID, cuando exista.
3. Redirigir `track_artists.artist_id` y `album_artists.artist_id` de cada duplicado al
   ID canónico correspondiente.
4. Eliminar exclusivamente las filas de artista redundantes, incluidas las que no
   tienen créditos. Conservar cualquier artista cuyo nombre sea único.
5. Crear el índice único y registrar la revisión `002_unique_artists`.

Las claves primarias de los créditos son propietario, rol y posición. Cambiar el
`artist_id` mantiene sus filas, roles y orden. No se borran créditos ni se renumeran sus
posiciones durante esta migración. Tampoco se cambian álbumes, pistas, archivos,
carátulas, géneros, líricas o `raw_tags`.

Usar operaciones SQL reproducibles para que la revisión también pueda generar SQL
offline. No basar el merge en filas recorridas por la GUI ni en la lectura de música.
La elección del canónico será determinista a partir de los IDs existentes; repetir la
actualización no cambiará ese resultado.

Antes de actualizar un catálogo existente, crear una copia de respaldo consistente
mediante la API de backup de SQLite, con nombre independiente y sin sobrescribir otra
copia. Si falla el respaldo, no iniciar la migración. Si falla la consolidación o el
índice, revertir toda la transacción, incluida la revisión de Alembic.

Repetir la actualización sobre `002` no crea otra copia ni altera datos. El downgrade
retira el índice y permite el esquema anterior; recuperar las filas duplicadas originales
requiere restaurar el respaldo, porque la consolidación no se deshace reconstruyendo IDs.

## 3. Reutilización en el importador

Simplificar [`_artist_id`](../src/trackfolio/infrastructure/catalog.py):

- Recibir únicamente conexión y nombre.
- Buscar en todo `artists` por igualdad exacta de nombre.
- Reutilizar el ID existente o crear el artista si todavía no existe.
- Quitar el contexto de álbum, biblioteca y directorio de esta búsqueda y sus llamadas.
- Mantener la caché por archivo y la deduplicación exacta de créditos de `_unique_labels`.
- Resolver inserciones mediante el índice único, evitando que escritores concurrentes
  creen dos filas para el mismo nombre: insertar con `ON CONFLICT(name) DO NOTHING`
  y recuperar el ID por nombre dentro de la transacción. Mantener las esperas acotadas.

El artista de una pista y el artista de un álbum compartirán ID cuando tengan el mismo
nombre; sus relaciones, roles y posiciones seguirán separados. El criterio de agrupación
de álbumes se mantiene: dos ediciones o carpetas distintas pueden contener álbumes
distintos y compartir artistas.

Reimportar conservará `file_id` y `track_id`. En la prueba **Abbath → Accept**, se
reimportará la misma canción con el crédito corregido y se comprobará que reutiliza
Accept, sin crear otro artista ni cambiar el nombre de Abbath o los créditos de otras
canciones. La prueba mantendrá los metadatos de álbum y `album_artists` sin cambios para
aislar la corrección del crédito de pista. Las etiquetas originales almacenadas se
actualizarán según el archivo leído,
con el comportamiento habitual de reimportación.

## 4. Compatibilidad y ejecución de la actualización

Antes de esta entrega, `database.py`, `session.py` y `migrations/env.py` importaban la
revisión y metadata de `001`, e `import_target.py` sólo migraba catálogos nuevos. Los
puntos de entrada se adaptan conjuntamente:

| Punto de entrada | Comportamiento previsto |
| --- | --- |
| `open_catalog` | Admitir catálogos reconocidos `001` y `002` en modo de lectura. Abrir no modifica el archivo ni lo migra. |
| `SqliteImportTargetFactory.validate` | Validar ambos esquemas sin escribir, crear copias o migrar. |
| `SqliteImportTargetFactory.open(update)` | Tras cerrar las consultas GUI, respaldar y migrar `001` antes de escribir; comprobar después el esquema vigente. |
| `open(create)` / `migrate_database` | Crear hasta la revisión vigente usando Alembic. Aplicar la actualización cuando la base existente sea reconocida. |
| Script de importación individual | Mantener sus argumentos; su llamada a `migrate_database` utilizará la misma actualización. |
| Actualización sin importar música | Ampliar `python -m trackfolio.infrastructure.database` con `--upgrade <catálogo>` para respaldar y migrar explícitamente. |

La escritura exige `002` y su índice único. Evitar caminos alternativos que sigan
guardando artistas sobre el esquema viejo. Compartir validación, respaldo y migración
entre los puntos de entrada; conservar el modo `rw` al actualizar un archivo existente
para que una desaparición del destino no cree un catálogo vacío de reemplazo.

La importación mantendrá la apertura diferida del escritor: si no hay audio válido o se
cancela antes de abrirlo, el catálogo viejo permanece en `001`. El comando explícito
permite consolidarlo sin releer los 139 archivos de música. Al terminar una importación
se reabre el lector mediante el ciclo de vida existente.

Conservar `initial_schema_sql()` y su exportación histórica a `001`. Añadir la exportación
del esquema completo vigente a un artefacto separado, por ejemplo
`migrations/002_current.sql`, usando la misma cadena de Alembic. Documentar que ese SQL
completo crea una base nueva; un catálogo poblado se actualiza con la migración en línea.

## 5. Pruebas y criterios de aceptación

- El mismo nombre comparte ID entre álbumes, directorios, raíces/bibliotecas y canciones
  sin álbum; un nombre nuevo crea una única fila.
- Créditos de pista y de álbum comparten identidad cuando corresponde, conservando
  roles, artistas múltiples y orden. Los nombres distintos conservan entidades distintas.
- El test contextual actual de catálogo pasa a esperar **2 álbumes y 1 artista**, con
  los mismos archivos y todas las etiquetas originales.
- Reimportación repetida conserva IDs y no aumenta artistas; corrección de una canción
  **Abbath → Accept** reutiliza Accept y deja los demás créditos intactos.
- El índice rechaza una segunda fila con el mismo nombre, incluso en una inserción
  directa; el comportamiento entre dos escritores respeta la unicidad.
- Una base temporal poblada en `001` se consolida a `002`: `MIN(id)` se conserva, ambas
  tablas de créditos mantienen filas/roles/posiciones y no se altera `raw_tags` ni BLOBs.
- Probar grupos con `external_id` canónico presente o ausente y artistas sin referencias.
- Comprobar `PRAGMA foreign_key_check` sin filas e `integrity_check = ok` después del merge.
- Fallos de respaldo o fallos inyectados tras redirigir créditos y antes de crear el índice
  dejan el catálogo anterior utilizable, con sus datos y revisión originales.
- Repetir la migración es idempotente; el respaldo conserva el catálogo anterior y el
  downgrade retira sólo la garantía nueva.
- Lectura de `001`/`002` conserva bytes; formulario de importación no migra; apertura del
  escritor actualiza `001`; revisión desconocida o `002` sin índice se rechazan.
- Separar la prueba del SQL histórico de `001` de la prueba del esquema vigente: hoy
  `test_export_matches_migrated_schema_and_committed_artifact` compara el inicial con `head`.
- Wheel instalado fuera del checkout contiene esquema vigente y revisión `002`, y genera,
  migra e importa correctamente con el núcleo sin Qt y con la GUI.

Modificar `tests/test_catalog.py`, ampliar pruebas de base, sesiones, destinos e integración
GUI y añadir `tests/test_artist_migration.py`. Las comprobaciones automáticas usan bases
temporales. Antes de actualizar el catálogo de trabajo, probar la consolidación en una
copia de éste y verificar los resultados de la tabla inicial de este plan.

## 6. Orden de implementación y entrega

| Fase | Archivos y trabajo | Salida verificable |
| --- | --- | --- |
| 1. Esquema vigente | Nuevo `infrastructure/schema.py`, validación compartida y separación del snapshot `001`. | Esquemas conocidos reconocidos y exportación histórica estable. |
| 2. Migración | Nueva `versions/002_unique_artists.py`, respaldo y actualización atómica. | Copia poblada consolidada, IDs/créditos preservados y rollback probado. |
| 3. Importador | `infrastructure/catalog.py` y pruebas de reutilización global. | Importar varios discos genera una fila por nombre; prueba Abbath → Accept correcta. |
| 4. Puntos de entrada | `database.py`, `session.py`, `import_target.py`, `migrations/env.py` y comando de actualización. | Lectura compatible; toda escritura utiliza `002`; actualización sin música disponible. |
| 5. Entrega | SQL vigente, workflow, documentación, paquete instalado y validación. | Pruebas, Ruff, formato, mypy y diagnóstico pasan; resultados registrados. |

Actualizar `.github/workflows/checks.yml`: empaquetar esquema vigente y revisión `002` y
reemplazar la expectativa literal de `001_initial` en la creación del wheel por la revisión
vigente. Mantener la matriz y el entorno bloqueado actuales, sin dependencias nuevas.

Al implementar, actualizar `docs/database.md` para describir la unicidad y la actualización
de catálogos; `docs/architecture.md` para separar snapshot y esquema vigente; README con
el comando de migración; `docs/import-plan.md` y `VALIDATION.md` con el estado real.

La entrega termina cuando una importación nueva cumple la unicidad y un catálogo existente
se puede consolidar conservando sus datos relacionados. Registrar por separado las
comprobaciones locales, la ejecución de CI y cualquier revisión visual pendiente.

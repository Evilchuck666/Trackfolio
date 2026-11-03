# Escritura de etiquetas y recuperación

**Guardar** edita el catálogo. **Escribir etiquetas…** publica todas las diferencias
entre sus diez campos editables guardados y los FLAC/MP3 seleccionados. Primero se
resuelven los cambios sin guardar mediante Guardar/Descartar/Cancelar.

**Escribir etiquetas de todo el catálogo…**, sobre el listado principal, abre el mismo
flujo para todas las canciones del catálogo. No requiere selección y consulta la base
de nuevo en segundo plano, incluyendo entradas añadidas desde que se abrió. Permanece
deshabilitado sin catálogo, con un catálogo vacío o mientras otra operación está activa.
La acción de escribir la selección sigue disponible junto al detalle de la canción.

El diálogo muestra todas las canciones desde que se abre, la salida del progreso y
únicamente **Cerrar** y **Escribir etiquetas**. Pulsar escribir prepara y verifica los
cambios internamente, sin selección de campos ni revisión manual de diferencias.
Cada canción conserva sus propios valores; los archivos sin diferencias se omiten.
También se comprueba y actualiza `album.nfo` si existe junto al audio, incluso cuando
las etiquetas musicales ya están actualizadas. Su ausencia es normal y no lo crea.
Los errores abren un pop-up que ofrece guardar el informe JSON; una operación correcta
no muestra ese pop-up.

Tras completar la escritura correctamente, **Escribir etiquetas** queda deshabilitado
y **Cerrar** sigue disponible. También se deshabilita si todos los archivos y NFO estaban
ya actualizados, o los NFO no existen. Si hay errores o pendientes, permite reintentar
en el mismo diálogo, incluido actualizar sólo el NFO después de escribir el audio.

## Actualización opcional de album.nfo

Se admite XML con raíz `<album>` sin namespace, compatible con metadatos de álbum Kodi.
Se busca `album.nfo` únicamente en la misma carpeta que los FLAC/MP3 destinatarios,
una vez por carpeta. No se busca en carpetas superiores: un NFO común situado sobre
subcarpetas de discos no se actualiza automáticamente.

La selección determina las carpetas. Los datos NFO se obtienen de todas las pistas
catalogadas de cada carpeta, sin escribir audio fuera de la selección:

| Dato NFO | Regla |
| --- | --- |
| `title` | Nombre de álbum guardado, coincidente en todas las pistas. |
| `year` | Año guardado, coincidente en todas las pistas. |
| `releasedate` existente | Actualiza el año conservando mes/día válidos; una fecha inválida se reduce al año. No cambia `originalreleasedate`. |
| `genre` | Unión de géneros sin duplicados exactos, según ruta relativa y orden de cada lista. |
| `artist` o `albumArtistCredits/artist` existentes | Créditos de álbum coincidentes; si todos carecen de ellos, artistas de pista cuando coincidan en todas las canciones. Se conserva la representación existente, sin añadir bloques de créditos donde no existen. |
| `artistdesc` existente | Descripción de los artistas resueltos, separados por ` / `. No se divide ningún nombre. |
| `track/title` en una lista de pistas existente | Título guardado de cada canción destinataria; se asocia por `position` y `discnumber` si existe en la pista o el álbum. |

Los valores vacíos coherentes eliminan sus elementos gestionados. Si faltan créditos
de álbum y difieren los artistas de pista, conserva los créditos NFO existentes,
como en una recopilación. Se conservan los identificadores asociados a los mismos
artistas; sustituir un crédito enriquecido por otro artista produce un conflicto.
Si hay un `artist` directo, se usa esa representación y se retiran los bloques simples
`albumArtistCredits` redundantes; se conservan los bloques con identificadores, atributos o
anotaciones. Esto permite limpiar los bloques redundantes añadidos por versiones anteriores.

Álbumes, años o créditos contradictorios, audio sin catalogar y pistas catalogadas
ausentes dejan el NFO intacto con una incidencia. Un XML no compatible o malformado
tampoco se convierte ni se sobrescribe. Se rechazan DTD, entidades y documentos de
más de 16 MiB; no se consultan recursos externos.

Si el NFO contiene una lista `<track>`, se actualizan los títulos de las canciones
destinatarias, también cuando el audio ya tiene el título correcto. El título general
del álbum se gestiona por separado; los títulos fuera de la selección se conservan. La numeración
debe identificar una única canción y una única entrada XML: una asociación ausente
o ambigua produce un conflicto. Se aceptan ceros iniciales en posición/disco. No se
crea una lista de pistas donde no existe ni se cambia su orden, posición o duración.

Se conservan reseñas, sellos, imágenes, identificadores, puntuaciones, campos
desconocidos y el resto de los datos de las listas de pistas, además de los atributos y comentarios
de los elementos conservados y las instrucciones de procesamiento. Al escribir
puede normalizarse la representación XML; se mantiene la codificación admitida,
el BOM UTF-8 y el uso de CRLF cuando existen. Se conserva la declaración XML original,
su separación respecto al contenido y los saltos finales. Si la declaración y `<album>`
estaban pegados por una escritura anterior, se separan con un salto de línea, incluso
sin diferencias musicales. Sin cambios de datos ni reparación de cabecera, no cambia
el contenido, la fecha ni el archivo físico.

Cada NFO se publica después de que sus audios destinatarios hayan terminado
confirmados o sin cambios. Si falla el audio, queda pendiente el NFO de esa carpeta.
Si falla el NFO, los audios ya escritos conservan su resultado y se mantienen los
respaldos del lote. Otros álbumes pueden continuar salvo un fallo esencial de
almacenamiento, catálogo o registro. La cancelación conserva lo ya publicado.

La salida y el informe JSON incluyen los NFO por separado: actualizado, sin cambios,
ausente, pendiente, conflicto o fallido. El contador de audio escrito no los incluye.
Los errores NFO ofrecen el mismo pop-up de informe y permiten reintentar. Una
publicación seguida de un fallo se identifica expresamente como NFO reemplazado.

El [plan de la entrega](album-nfo-plan.md) detalla contratos y criterios de aceptación.

## Formatos y valores admitidos

| Caso | Comportamiento |
| --- | --- |
| FLAC | Modifica los comentarios Vorbis que difieren del catálogo; conserva imágenes, otros bloques y audio. |
| MP3 con ID3v2.4 | Conserva v2.4 y las listas de artistas/géneros con orden y Unicode. |
| MP3 con ID3v2.3 | Conserva v2.3; bloquea listas que se unirían al guardar. No convierte a v2.4. |
| MP3 sin ID3 | Crea ID3v2.4. |
| ID3v2.2 o ID3v1 coexistente | Bloqueado; esta entrega no convierte ni descarta etiquetas legadas. |
| Pista/disco y totales | Escribe los números y totales guardados. Un total sin número vuelve a leerse como número ausente. |
| Fechas completas | Cambia el año conservando la precisión válida y representable. Si la fecha resultante es inválida o no representable, guarda solo el año; vaciarlo elimina la fecha. |
| Varias líricas USLT | Actualiza la primera versión de líricas que expone el lector y conserva las demás. El importador puede mostrar otra versión restante, porque solo expone un texto de líricas. |
| Alias y TXXX | Retira o actualiza la familia del campo modificado para que un alias antiguo no prevalezca. |
| Metadatos ajenos | Verifica comentarios, frames conocidos/desconocidos, imágenes y etiquetas APEv2 finales; si no puede preservarlos, no publica. |

Los números se serializan sin inventar valores; los años utilizan cuatro dígitos en
el intervalo 1–9999. La escritura no divide nombres por comas, punto y coma ni `/`.
Un campo guardado vacío elimina su etiqueta. Las listas vacías eliminan su familia de etiquetas.
Con ID3v2.3 se admiten fechas con precisión de año, día o minuto; otras precisiones
se reducen al año cuando este cambia. El progreso indica cada archivo incompatible.

Los hashes del audio comparan los bytes situados después de los bloques de metadatos
FLAC o entre las etiquetas iniciales/finales de MP3. No se recodifica ni se verifica
mediante duración o el MD5 declarado solamente. La verificación de etiquetas se realiza
reabriendo la copia modificada antes de reemplazar el original.

## Archivos, permisos y espacio

Cada archivo, incluido el NFO, necesita espacio para un respaldo completo y una copia temporal. Se
procesan secuencialmente: reserva espacio para todos los respaldos y el mayor temporal.
Antes de escribir se comprueba ese espacio por volumen, con un margen adicional de 1 MiB.
No se siguen enlaces simbólicos/junctions, no se reemplazan enlaces duros ni destinos
fuera de su raíz importada. Un original ausente o de solo lectura queda bloqueado;
esto no impide editar sus datos en SQLite.
La propia raíz importada puede ser un alias, como `/var` en macOS: se normaliza para
operar sobre el NFO y se conserva su representación guardada para consultar el catálogo.
Los enlaces dentro de la biblioteca y los cambios de destino durante la operación
siguen bloqueados.

En Linux se copian y comprueban modo, propietario/grupo y atributos extendidos,
incluidas las ACL que se representen mediante esos atributos. En macOS se utiliza
`copyfile` de libSystem para conservar permisos, ACL y atributos, incluido el resource
fork, y se comprueban mediante las API nativas.
En macOS, un atributo distinto del resource fork que supere 16 MiB se bloquea para
mantener acotada la memoria de verificación; el resource fork se compara por streaming.
En Windows se copian propietario, grupo, DACL y streams con nombre mediante API nativa;
no se copian reglas de auditoría SACL que requieren privilegios. Los archivos NTFS
comprimidos o cifrados se rechazan. No se promete conservar metadatos que el sistema
no exponga, ni identidad de inode o fecha de creación tras el reemplazo. Si falla la
preservación requerida, el original permanece intacto.

Se sincronizan copias y registros a disco; en POSIX también se sincronizan directorios
cuando el sistema lo permite. Windows no ofrece esa sincronización de directorio
mediante esta implementación. La publicación utiliza `os.replace` en el mismo volumen.
Su durabilidad final depende del sistema de archivos y del almacenamiento; las
comprobaciones no impiden todas las carreras con otros programas que editen música.

## Resultados y cancelación

Cada archivo puede quedar confirmado, escrito con catálogo pendiente, sin cambios,
excluido, en conflicto, fallido o pendiente. La salida muestra errores y respaldos. Si hay errores, el pop-up permite exportar el
informe JSON. La escritura no cambia los valores musicales guardados en el catálogo.

**Cerrar** durante un trabajo solicita la cancelación, espera un punto seguro y
cierra el diálogo conservando lo ya publicado. El bucle de eventos sigue respondiendo.
Un fallo aislado permite continuar con otros archivos; la pérdida del catálogo o del
registro y fallos esenciales de almacenamiento detienen los pendientes. No hay una
transacción global entre los archivos y SQLite, ni un deshacer automático del lote.

## Recuperación

Antes de editar una copia se crea un respaldo completo junto a cada original:

```text
<carpeta de música>/.trackfolio-backups/<operación>/<id>-<nombre>.tfo-bak
```

Los temporales propios están en la carpeta del original:
`.trackfolio-<operación>-<id>.tmp`. Estos sufijos evitan reimportarlos como música.
El respaldo NFO se llama `nfo-album.nfo.tfo-bak` dentro del mismo directorio de operación;
su temporal es `.trackfolio-<operación>-album-nfo.tmp` junto al original.
Después de escribir y confirmar todo el lote, incluidos sus NFO, sin errores ni cancelación, se elimina
el directorio `.trackfolio-backups` completo en cada carpeta donde se crearon copias,
incluidos los UUID y respaldos anteriores que contenga. La limpieza espera al final
del lote y al registro de su confirmación; no se realiza por canción. Los resultados
sin cambios no crean copias ni borran respaldos antiguos por sí solos.

Si hay un fallo, conflicto, catálogo pendiente o cancelación, se conservan las copias
del lote. Si falla la propia limpieza, el informe indica el error y mantiene las rutas
de las copias que sigan presentes; otras carpetas pueden haberse eliminado ya.

El registro persistente está en la carpeta de datos del usuario, en
`Trackfolio/tag-writes/<operación>/journal.json`. En Linux normalmente es
`~/.local/share/Trackfolio/tag-writes/`; se respeta `XDG_DATA_HOME` y en macOS/Windows
se utiliza el equivalente de `platformdirs`. El registro guarda rutas, valores
confirmados, hashes y estados, sin incluir las portadas binarias. Su versión `2`
incluye trabajos y resultados NFO separados de las canciones; la revisión técnica
sigue admitiendo los registros antiguos de versión `1`.

Los registros se conservan como historial. Los respaldos que permanecen después de un
lote incompleto permiten recuperación manual.
La GUI no presenta un gestor de operaciones pendientes ni reanuda escrituras al arrancar.
El caso de uso técnico `ReviewTagWrites` sigue disponible para inspeccionar hashes y
reconciliar observaciones del catálogo e inspeccionar los hashes de los NFO mediante
sus contratos Python, sin reescribir
ni restaurar audio. Una confirmación requiere que el catálogo y su instantánea sigan
siendo válidos; las ediciones posteriores se conservan como conflictos.

Para restaurar manualmente, cierra los programas que usen el archivo, conserva una
copia de su versión actual y comprueba la ruta de respaldo en el informe. Copia el
contenido del `.tfo-bak` sobre la ruta original, recuperando su extensión original;
el respaldo es el archivo completo, no un formato propio. Conserva el respaldo y el
registro hasta comprobar la restauración. SQLite mantiene sus correcciones: reimportar
volverá a sustituirlas por las etiquetas restauradas.

Un temporal parcial que no llegó a verificarse se conserva para revisión manual tras
una interrupción brusca; el informe indica su ruta. No borres respaldos o registros de
operaciones pendientes antes de resolverlos. Los registros cerrados quedan como historial.

Las comprobaciones locales y por plataforma se registran en [VALIDATION.md](../VALIDATION.md).

Referencias de plataforma: [permisos y herencia en Windows](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information),
[representación del descriptor de seguridad](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertsecuritydescriptortostringsecuritydescriptorw)
y [enumeración de streams](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw).
Para macOS: [copyfile y metadatos](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/copyfile.3.html)
y [ACL](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/acl_get_file.3.html).

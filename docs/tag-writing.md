# Escritura de etiquetas y recuperación

**Guardar** edita el catálogo. **Escribir etiquetas…** publica todas las diferencias
entre sus diez campos editables guardados y los FLAC/MP3 seleccionados. Primero se
resuelven los cambios sin guardar mediante Guardar/Descartar/Cancelar.

El diálogo muestra todas las canciones desde que se abre, la salida del progreso y
únicamente **Cerrar** y **Escribir etiquetas**. Pulsar escribir prepara y verifica los
cambios internamente, sin selección de campos ni revisión manual de diferencias.
Cada canción conserva sus propios valores; los archivos sin diferencias se omiten.
Los errores abren un pop-up que ofrece guardar el informe JSON; una operación correcta
no muestra ese pop-up.

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

Cada archivo necesita espacio para un respaldo completo y una copia temporal. Se
procesan secuencialmente: reserva espacio para todos los respaldos y el mayor temporal.
No se siguen enlaces simbólicos/junctions, no se reemplazan enlaces duros ni destinos
fuera de su raíz importada. Un original ausente o de solo lectura queda bloqueado;
esto no impide editar sus datos en SQLite.

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
Después de escribir y confirmar todo el lote sin errores ni cancelación, se elimina
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
confirmados, hashes y estados, sin incluir las portadas binarias.

Los registros se conservan como historial. Los respaldos que permanecen después de un
lote incompleto permiten recuperación manual.
La GUI no presenta un gestor de operaciones pendientes ni reanuda escrituras al arrancar.
El caso de uso técnico `ReviewTagWrites` sigue disponible para inspeccionar hashes y
reconciliar observaciones del catálogo mediante sus contratos Python, sin reescribir
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

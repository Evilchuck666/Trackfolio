# Escritura de etiquetas y recuperación

**Guardar** edita el catálogo. **Escribir etiquetas…** publica los campos elegidos
desde ese catálogo en los FLAC/MP3 seleccionados. Primero se resuelven los cambios sin
guardar, se revisan las diferencias y se confirma el subconjunto escribible.

## Formatos y valores admitidos

| Caso | Comportamiento |
| --- | --- |
| FLAC | Modifica comentarios Vorbis elegidos; conserva imágenes, otros bloques y audio. |
| MP3 con ID3v2.4 | Conserva v2.4 y las listas de artistas/géneros con orden y Unicode. |
| MP3 con ID3v2.3 | Conserva v2.3; bloquea listas que se unirían al guardar. No convierte a v2.4. |
| MP3 sin ID3 | Crea ID3v2.4. |
| ID3v2.2 o ID3v1 coexistente | Bloqueado; esta entrega no convierte ni descarta etiquetas legadas. |
| Pista/disco y totales | Permite editar cada mitad conservando la otra desde el archivo. Un total sin número vuelve a leerse como número ausente. |
| Fechas completas | Cambia el año conservando la precisión válida y representable. Vaciar o reducir una fecha requiere permiso explícito en el diálogo. |
| Varias líricas USLT | Exige elegir idioma/descripción; conserva las otras versiones. El importador puede mostrar otra versión restante, porque solo expone un texto de líricas. |
| Alias y TXXX | Retira o actualiza la familia del campo elegido para que un alias antiguo no prevalezca. La vista previa muestra las etiquetas afectadas. |
| Metadatos ajenos | Verifica comentarios, frames conocidos/desconocidos, imágenes y etiquetas APEv2 finales; si no puede preservarlos, no publica. |

Los números se serializan sin inventar valores; los años utilizan cuatro dígitos en
el intervalo 1–9999. La escritura no divide nombres por comas, punto y coma ni `/`.
Un campo vacío marcado se elimina. Las listas vacías eliminan la familia elegida.
Con ID3v2.3 se admiten fechas con precisión de año, día o minuto; otras precisiones
requieren reducir explícitamente al año. La vista previa explica cada caso bloqueado.

Los hashes del audio comparan los bytes situados después de los bloques de metadatos
FLAC o entre las etiquetas iniciales/finales de MP3. No se recodifica ni se verifica
mediante duración o el MD5 declarado solamente. La verificación de etiquetas se realiza
reabriendo la copia modificada antes de reemplazar el original.

## Archivos, permisos y espacio

Cada archivo necesita espacio para un respaldo completo y una copia temporal. Se
procesan secuencialmente: la estimación suma todos los respaldos y el mayor temporal.
No se siguen enlaces simbólicos/junctions, no se reemplazan enlaces duros ni destinos
fuera de su raíz importada. Un original ausente o de solo lectura queda bloqueado;
esto no impide editar sus datos en SQLite.

En POSIX se copian y comprueban modo, propietario/grupo y atributos extendidos
expuestos por el sistema, incluidas las ACL que se representen mediante esos atributos.
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
excluido, en conflicto, fallido o pendiente. El informe muestra errores y respaldos,
y permite copiar texto o exportar JSON. Se conserva cualquier corrección del catálogo
que no se haya elegido para escribir.

Cancelar espera un punto seguro y conserva lo ya publicado. Cerrar durante un trabajo
solicita la cancelación y mantiene el bucle de eventos hasta recibir el resultado.
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
Los respaldos no se eliminan automáticamente, incluso cuando todo termina bien.

El registro persistente está en la carpeta de datos del usuario, en
`Trackfolio/tag-writes/<operación>/journal.json`. En Linux normalmente es
`~/.local/share/Trackfolio/tag-writes/`; se respeta `XDG_DATA_HOME` y en macOS/Windows
se utiliza el equivalente de `platformdirs`. El registro guarda rutas, valores
confirmados, hashes y estados, sin incluir las portadas binarias.

Al iniciar se avisa de los registros incompletos. Desde **Operaciones pendientes…**:

1. Pulsa **Revisar** para comparar los archivos con los hashes anterior y posterior.
   Esta revisión no modifica la música ni SQLite.
2. Si el archivo coincide con el resultado verificado, puedes confirmar su observación
   en SQLite. Solo se hace si el catálogo y su instantánea siguen siendo válidos; una
   confirmación ya aplicada se reconoce sin duplicarla.
3. Si coincide con el original, no se reanuda la escritura. La confirmación explícita
   puede retirar un temporal propio cuya identidad y hash estén verificados. Para
   escribir ese archivo prepara una vista previa nueva.
4. Si no coincide con ninguna versión, falta el archivo o el catálogo cambió, conserva
   el informe y revisa el conflicto manualmente. No se restaura ni sobrescribe música
   automáticamente. Un registro dañado se muestra sin ocultar otras operaciones.

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

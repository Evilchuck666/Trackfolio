# Vista de álbum

La pestaña **Álbumes** muestra las ediciones del catálogo en una lista con buscador.
Al seleccionar una, presenta su portada guardada en SQLite, artistas del álbum,
año, géneros, carpeta, número de pistas y discos y duración disponible. Las pistas
se ordenan por disco y número; el doble clic abre la canción en **Canciones**.
La consulta y la edición funcionan aunque la música esté desconectada.

## Agrupación

La vista utiliza la biblioteca y carpeta de la edición, el título, año, fecha,
artistas del álbum y total de discos. Conserva separados los álbumes del mismo
nombre situados en otras carpetas o bibliotecas y los metadatos contradictorios.
No modifica ni fusiona los registros originales al consultar.

Los subdirectorios `CD 1`, `CD2`, `Disc 01`, `Disk 2` o `Disco 2` se consideran parte
de la carpeta superior únicamente si el número coincide con el disco guardado de
la pista. Los demás directorios permanecen separados. No se combinan carpetas
arbitrarias sólo porque compartan título.

Los artistas de pista no determinan la agrupación: una recopilación puede contener
intérpretes distintos. Si no hay artistas del álbum, se muestra esa ausencia sin
inventar créditos a partir de los intérpretes.

## Editar un álbum

1. Pulsa **Editar álbum** o `Ctrl+E` desde la pestaña.
2. Marca los campos que quieras aplicar a todas las pistas: álbum, año, artistas del
   álbum o géneros. Los campos desmarcados se conservan; un campo marcado vacío se borra.
3. Añade los nombres completos y ordénalos con los controles de lista. No se dividen
   por comas, barras o punto y coma. Si las pistas tienen géneros diferentes, el editor
   indica **Valores distintos** y exige marcar el campo antes de reemplazarlo.
4. Pulsa **Guardar álbum** o `Ctrl+S`. Se guarda en una sola transacción para las pistas
   del álbum que se cargaron al iniciar la edición. Los cambios concurrentes producen
   un conflicto y conservan el borrador, sin guardar una parte del álbum.

Guardar conserva los artistas de cada canción, los títulos, la numeración y las
líricas. Las ediciones de otras carpetas se mantienen. La vista se actualiza tras
el guardado y conserva el álbum seleccionado aunque cambie su nombre.

Cambiar de álbum o pestaña, actualizar, abrir otro catálogo, importar, escribir
etiquetas o cerrar la ventana resuelve los cambios pendientes mediante
**Guardar / Descartar / Cancelar**. Los atajos actúan sobre el editor visible.

## Escribir en la música

**Escribir etiquetas del álbum…** prepara el diálogo existente para todas sus pistas,
incluidos sus discos. Pulsar **Escribir etiquetas** publica los datos guardados del
catálogo, con las mismas comprobaciones, temporales, respaldos e informes que la
vista de canciones. Los artistas del álbum se escriben como `ALBUMARTIST` en FLAC o
`TPE2` en MP3; los artistas de pista siguen utilizando `ARTIST` / `TPE1`.

La portada se elige por carpeta física según las [reglas de portadas](tag-writing.md#incrustación-de-portadas).
Se actualizan los `album.nfo` de las carpetas de las canciones, si existen, según
las [reglas NFO](tag-writing.md#actualización-opcional-de-albumnfo). Agrupar los discos
en esta vista no amplía la búsqueda NFO a carpetas superiores.
**Guardar álbum** por sí solo no modifica los archivos musicales.

# Vista de artistas

La pestaña **Artistas** muestra un listado con búsqueda por nombre y, a su derecha,
los álbumes del artista seleccionado, ordenados por año y título. Cada edición
conserva su carpeta y sus pistas. Se abre el detalle con **Ver álbum**, doble clic
o Intro; allí están disponibles la edición y la escritura de etiquetas habituales.
**Artistas** es la pestaña inicial.

La cabecera muestra una imagen JPG/JPEG de la carpeta superior a la de sus álbumes,
sin buscar en subcarpetas. Se prioriza `artist.jpg`, después `folder.jpg` y después
el nombre alfabético (sin distinguir mayúsculas en la extensión). Si hay varias
carpetas, se recorren por ruta. Sin imagen disponible, la cabecera queda sin foto.
La lectura se realiza en segundo plano al seleccionar el artista o recargar la vista;
no se incrusta esta imagen en las canciones ni se guarda en el catálogo.

La agrupación usa los artistas del álbum. Un álbum con varios artistas acreditados
aparece bajo cada uno. Cuando faltan esos créditos, se usan los artistas de pista
solo si coinciden en todas las canciones. Los demás álbumes se incluyen en
**Sin artista de álbum**, sin atribuir una recopilación a cada invitado.
Los nombres no se dividen por comas ni otros separadores y no se unifican variantes.

La vista usa los datos guardados en el catálogo y funciona sin los archivos de audio.
Al entrar en la pestaña o actualizar el catálogo, se recarga el listado conservando
la búsqueda y el artista seleccionado cuando sigue disponible. La agrupación no
modifica los metadatos ni crea registros adicionales.

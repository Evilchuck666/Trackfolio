# Plan de la primera GUI de Trackfolio

Estado: GUI implementada y validada localmente el 7 de octubre de 2026. La base y su muestra
están preparadas. La ventana permite abrir un catálogo SQLite y
mostrar sus canciones mediante Qt 6, con la GUI como interfaz prioritaria.

## Resultado esperado

Una ventana permite abrir un catálogo, consultar su lista de canciones y seleccionar
un registro para ver sus metadatos y portada. Los datos proceden de SQLite. El visor
funciona aunque la música original no esté disponible en ese equipo: la portada ya
está almacenada en la base de datos.

Este incremento ofrece apertura de catálogo, actualización de la lista, selección
y consulta de todos los campos solicitados. Los campos son de lectura y permiten
copiar texto. La edición y la importación desde la GUI se abordarán después sobre
los mismos casos de uso; TUI y API siguen siendo posibilidades futuras.

## 1. Contratos y arranque

- [x] Mantener `GetTrack` para recuperar el detalle del archivo seleccionado.
- [x] Añadir el DTO inmutable `CatalogSummary`, la operación de repositorio
  `list_summaries()` y el caso de uso `ListTrackSummaries`. Conservar el contrato
  existente de `ListTracks`.
- [x] Devolver en el resumen identificadores, título, artistas, álbum, año y ruta.
  Consultar columnas concretas sin cargar BLOBs, líricas ni etiquetas originales
  para todas las canciones. Este cambio no requiere una migración.
- [x] Construir motor, repositorio y casos de uso en un punto de composición. Los
  widgets, modelo de tabla y presentador reciben casos de uso; no importan
  SQLAlchemy, Alembic o Mutagen ni ejecutan SQL.
- [x] Encapsular en infraestructura la apertura y validación del catálogo existente
  y el cierre de sus recursos. Una ruta inexistente, una BD ajena o una revisión
  incompatible generan un mensaje recuperable. Abrir un archivo no crea
  silenciosamente otro catálogo ni modifica su esquema.
- [x] Añadir el punto de entrada del paquete GUI y un lanzador `trackfolio` mediante
  `project.gui-scripts`, para iniciar sin consola adicional en Windows.
  La carga de Qt se limita al arranque gráfico; el núcleo conserva
  su instalación y sus pruebas sin PySide6.
- [x] Admitir `--database` y la acción **Abrir catálogo…**. Sin argumento, abrir el
  último catálogo válido o mostrar la ventana sin catálogo. Guardar configuración
  local mediante `platformdirs`, fuera del repositorio.

Comando para abrir la muestra desde la raíz:

```sh
uv run --locked --extra gui python -m trackfolio.interfaces.gui --database data/trackfolio.sqlite3
```

Las rutas se pasan como argumentos, con comillas cuando contienen espacios. El
paquete instalado debe funcionar desde cualquier directorio de trabajo y con una
base ubicada fuera del proyecto.

## 2. Ventana y distribución de datos

- [x] Ventana redimensionable con un splitter: lista de canciones y detalle.
- [x] Tabla con columnas **Canción**, **Artista(s)**, **Álbum**, **Año** y **Archivo**.
  Archivo distingue registros sin título sin inventar un metadato musical.
- [x] Seleccionar el primer registro al abrir una BD con datos. Al actualizar,
  conservar la selección por `file_id` cuando siga disponible.
- [x] Acciones **Abrir catálogo…**, **Actualizar** y **Salir**, atajos de teclado,
  foco visible y navegación entre lista y campos.
- [x] Barra de estado con catálogo abierto, número de registros y estado de carga.
  Detalle vacío cuando no hay selección.

| Grupo del detalle | Campos |
| --- | --- |
| Identificación | Miniatura de portada, canción y artista(s). |
| Álbum | Nombre y año. |
| Numeración | Número de pista, total de pistas, número de disco y total de discos. |
| Clasificación | Género(s), conservando nombres y orden. |
| Líricas | Texto plano seleccionable, con saltos de línea y scroll. |

La numeración tendrá campos separados y próximos entre sí. Si sólo existe el
número de pista, su total queda vacío. Los valores `None` y las colecciones vacías
se presentan como texto vacío, sin ceros ni valores supuestos. Las líricas se
cargan como texto plano para conservar su contenido sin interpretarlo como HTML.

La miniatura usa los bytes de `GetTrack` y mantiene la proporción. La decisión
entre portada incrustada y `album.jpg` ya se resuelve durante la importación. Si no
hay imagen o Qt no decodifica sus bytes, el área queda vacía y el resto del detalle
sigue disponible. La GUI no vuelve a leer el archivo musical.

## 3. Apariencia compartida y recursos

- [x] Qt Widgets con **Fusion** explícito, una paleta y estilos de Trackfolio, con
  espaciado, bordes y tamaños compartidos.
- [x] Fuente, variantes necesarias, licencia, estilos e iconos propios en
  `trackfolio.resources`. Cargar la fuente con `QFontDatabase` y los archivos con
  `importlib.resources`, independientemente del directorio de ejecución y del
  tema de iconos del escritorio.
- [x] Diálogos Qt con modo nativo desactivado y menús dentro de la ventana.
- [x] Barra de título y controles de ventana dibujados por Qt para cubrir también
  la apariencia del marco. Validar movimiento, redimensionado, minimizar,
  maximizar/restaurar, cierre, foco y accesibilidad. Utilizar las operaciones del
  sistema expuestas por Qt para mover y redimensionar, especialmente en Wayland.
  Comprobar sus resultados y manejar las capacidades del backend elegido.
- [x] Layouts y tamaños lógicos que admitan el escalado de pantalla. Revisar al
  100 %, 150 % y 200 %, incluida la miniatura y la legibilidad del texto.

Se compartirán diseño, recursos, controles y distribución. El rasterizado y los
píxeles físicos pueden variar con el sistema y la pantalla. Fusion por sí solo
no controla el marco del sistema; por eso su implementación propia forma parte
del plan. Referencias: [Fusion](https://doc.qt.io/qt-6.11/qstylefactory.html),
[fuentes](https://doc.qt.io/qt-6.11/qfontdatabase.html#addApplicationFontFromData),
[DPI](https://doc.qt.io/qt-6.11/highdpi.html) y
[movimiento de ventana](https://doc.qt.io/qt-6.11/qwindow.html#startSystemMove).

## 4. Carga y estados de la interfaz

- [x] Consultas de lista y detalle en tareas de trabajo para mantener receptiva
  la ventana. Cada operación obtiene y cierra su conexión; no se comparte una
  conexión SQLite entre hilos.
- [x] Widgets e imágenes de presentación se crean y modifican en el hilo gráfico.
  Los trabajadores devuelven dataclasses o errores de aplicación.
- [x] Identificar solicitudes para descartar respuestas antiguas al cambiar
  rápidamente de canción o de catálogo.
- [x] Limpiar todos los campos al cambiar de selección, sin conservar portada,
  líricas o numeración del registro anterior.
- [x] Resolver ausencia de catálogo, BD vacía, selección eliminada, catálogo
  inaccesible/bloqueado y errores de consulta. Un metadato ausente es válido y no
  genera un aviso de error.
- [x] Cerrar la ventana y cambiar de catálogo sin dejar trabajadores/conexiones
  abiertos ni enviar resultados a una ventana destruida.

## 5. Comprobaciones funcionales

- [x] Verificar que listar resúmenes no recupera BLOBs, líricas ni `raw_tags`.
- [x] Probar widgets y selección con QtTest, incluido en PySide6, y pytest.
  Mantener datos sintéticos y bases temporales.
- [x] Comprobar registros completos, parciales y sin metadatos; varias canciones
  y géneros; Unicode; líricas con saltos de línea; portada válida, ausente y no
  decodificable; BD vacía y errores de lectura recuperables.
- [x] Comprobar selección rápida y respuestas fuera de orden.
- [x] Probar GUI → casos de uso → SQLite cuando el archivo musical ya no existe.
- [x] Validar manualmente la muestra real: **Run If You Can**, **Accept**,
  **Breaker**, **1981**, **3/10**, **1/1**, **Heavy Metal**, JPEG de **500 × 500**
  y líricas vacías. Comparar con `track_details` en SQLiteBrowser.
- [x] Mantener Ruff, formato, mypy y la suite del núcleo.

## 6. Entrega reproducible y validación multiplataforma

- [x] Mantener CPython 3.13.15 administrado por uv, uv 0.12.10 y PySide6 6.11.2.
  Versionar en `pyproject.toml` y `uv.lock` las dependencias nuevas necesarias.
  Esta GUI utiliza inicialmente los módulos ya instalados.
- [x] Ampliar `doctor.py` para verificar recursos reales y arranque de la ventana
  del producto, conservando el diagnóstico aislado en un subproceso.
- [x] Añadir tareas y depuración de VS Code para iniciar la GUI con la muestra,
  usando rutas de workspace y argumentos separados.
- [x] Construir wheel y distribución de fuentes con todos los recursos. Instalar
  el wheel y sus dependencias desde el lock en un entorno limpio y verificar
  la GUI desde otra carpeta, sin el checkout ni la música de ejemplo.
- [x] Ampliar GitHub Actions a la GUI del producto en Windows x86-64, GNU/Linux
  x86-64 y macOS Intel/Apple Silicon. Mantener núcleo sin Qt, GUI `offscreen` y
  comprobaciones disponibles de escritorio nativo/X11.
- [ ] Registrar revisión visual e interacción en escritorios reales, incluido
  Wayland local. Separar resultados medidos y pendientes: `offscreen` no acredita
  apariencia ni comportamiento del marco en un escritorio.
  Completado el arranque real local Wayland/X11 y las capturas a 100/150/200 %;
  pendiente la comparación visual manual en Windows y macOS. La matriz automática
  de las cuatro plataformas pasa en la ejecución 37659500266 de GitHub Actions.
- [x] Actualizar README, entorno y VALIDATION con comandos de arranque,
  preparación de otro PC y resultados observados.

La entrega de esta fase es el proyecto instalable y reproducible con Python/uv,
con Qt, recursos y dependencias Python resueltos para cada plataforma. Los
ejecutables autónomos con intérprete incluido se diseñarán en una entrega posterior.

La matriz inicial se mantiene: Windows 10 1809+/11 x86-64, macOS 13+ Intel/Apple
Silicon y GNU/Linux x86-64 con glibc 2.34+ y backend gráfico compatible. uv
reconstruye el entorno; no se traslada `.venv` entre PCs. Las bibliotecas gráficas
nativas y la sesión de escritorio siguen siendo requisitos del sistema, con
diagnóstico e instrucciones en [environment.md](environment.md). La compatibilidad
se verifica contra esta matriz y sus requisitos.

## Orden y cierre de la fase

Implementar las etapas 1 y 2 para obtener una ventana que consulte la muestra;
completar apariencia y carga en las etapas 3 y 4; cerrar con pruebas, empaquetado
y comprobaciones multiplataforma en las etapas 5 y 6.

La fase termina cuando muestra todos los campos de la muestra, conserva en blanco
los ausentes, funciona desde el paquete instalado y tiene comprobaciones funcionales
en la matriz de CI. Los resultados visuales y de interacción real se registran
por separado, sin dar por confirmada una plataforma antes de comprobarla.

Tarea 3.5: Galería de Indicadores Técnicos

> **ABSORBIDA en la Tarea 3.5 — Data Explorer mejorado
> (`TASK_3_5_DATA_EXPLORER.md`).**
>
> Este documento se conserva y no se borra: el razonamiento de por que hacia
> falta una galeria sigue siendo valido, y la regla de la seccion 8 de
> `PROJECT_GUIDELINES.md` es precisamente no perderlo.
>
> Motivo de la absorcion: un explorador que dibuja las velas con cualquier
> indicador superpuesto **es** la galeria de indicadores, con dos diferencias que
> la hacen mejor. Funciona sobre datos vivos en lugar de sobre un job
> precalculado, y no obliga a crear un job para poder ver un grafico. Mantener
> las dos pantallas seria mantener dos formas de hacer lo mismo.
>
> De este documento, estos criterios de aceptacion pasan al explorador:
> - Grid de tarjetas de los indicadores disponibles.
> - Vista de detalle con descripcion, parametros y grafico de ejemplo.
> - Crear un job de calculo desde la galeria ("Usar este indicador").
>
> Y estos se descartan, con motivo:
> - El "playground" de parametros sobre el grafico de ejemplo. Se solapa con el
>   hecho de que los parametros de un job se pueden cambiar y volver a ejecutar;
>   mantener dos caminos para cambiar un parametro es una decision, no una
>   comodidad.
> - Fórmulas matematicas y senales tipicas de trading. Son documentacion de un
>   manual de indicadores, no del sistema, y este sistema solo calcula cuatro
>   indicadores. Se documenta en el README de Features cuando toque.

Objetivo
Crear una página de galería que muestre los indicadores técnicos disponibles en el sistema, con descripciones claras, fórmulas matemáticas, señales de trading típicas y gráficos de ejemplo generados con datos reales importados. Esta galería servirá como referencia educativa para el usuario y como catálogo visual de las capacidades del módulo de Features.
Criterios de Aceptación
2.1. Funcionalidad
El usuario puede acceder a la galería desde el menú lateral (item "Galería" junto a "Indicadores")
La galería muestra una vista en tarjetas de todos los indicadores disponibles
Cada tarjeta muestra: nombre, descripción breve, icono representativo
Al hacer clic en una tarjeta, se abre una vista de detalle con: descripción completa, fórmula matemática, parámetros configurables con rangos recomendados, señales de trading típicas y gráfico de ejemplo con datos reales.
El usuario puede probar diferentes configuraciones de parámetros en el gráfico de ejemplo (modo "playground")
El usuario puede crear un job de cálculo directamente desde la galería (botón "Usar este indicador")
2.2. Técnico
Los datos de ejemplo se obtienen de velas reales importadas (no datos hardcodeados)
Los gráficos se renderizan con lightweight-charts (ya instalado)
La descripción de cada indicador se almacena en un archivo JSON o diccionario Python de configuración (fácil de extender)
El cálculo de los gráficos de ejemplo se hace bajo demanda (no se precalcula)
La galería es responsive y funciona bien en móvil y escritorio
2.3. Calidad
Al menos 7 indicadores documentados en V1 (los mismos que soporta el sistema)
Cada indicador tiene al menos un gráfico de ejemplo con datos reales
Las descripciones son claras y precisas, validadas contra fuentes financieras reconocidas
Arquitectura
3.1. Backend
Archivo de configuración: backend/app/modules/features/indicator_catalog.py
Define un diccionario con la metadata de cada indicador (nombre, descripción corta, descripción larga, fórmula, parámetros con tipo/valor por defecto/min/max, señales de trading, y datos de ejemplo como símbolo, timeframe y días).
Nuevos endpoints en router.py:
GET /api/v1/features/gallery : Lista todos los indicadores con su metadata
GET /api/v1/features/gallery/{indicator_name} : Detalle de un indicador
GET /api/v1/features/gallery/{indicator_name}/example : Gráfico de ejemplo con datos reales. Acepta parámetros opcionales para sobreescribir los valores por defecto. Devuelve un FeaturePreviewOut con los datos OHLCV + indicador calculado.
Servicio de galería en service.py (extensión):
get_gallery() : Lee el catálogo y devuelve la lista
get_indicator_detail(name) : Devuelve la metadata de un indicador
get_indicator_example(name, params_override) : Obtiene datos de velas, calcula el indicador y devuelve el resultado en formato FeaturePreviewOut.
3.2. Frontend
Nuevas rutas:
/features/gallery : Lista de tarjetas de indicadores
/features/gallery/:indicatorName : Detalle de un indicador con gráfico
Nuevos componentes:
IndicatorCard.tsx : Tarjeta compacta para la lista
IndicatorDetail.tsx : Vista detallada con descripción, fórmula, señales
IndicatorPlayground.tsx : Gráfico interactivo con controles de parámetros
SignalBadge.tsx : Badge visual para las señales de trading
Nuevas páginas:
IndicatorGallery.tsx : Grid de tarjetas con búsqueda/filtro
IndicatorDetailPage.tsx : Página de detalle completa
Nuevos servicios API en featuresApi.ts:
getGallery()
getIndicatorDetail(name)
getIndicatorExample(name, params)
Flujo del Usuario
Exploración inicial: Usuario hace clic en "Galería", ve un grid de tarjetas con los 7 indicadores.
Profundización: Usuario hace clic en una tarjeta (ej: RSI), ve la página de detalle con descripción, fórmula, parámetros, señales y gráfico de ejemplo.
Experimentación (modo playground): Usuario ajusta los parámetros del indicador, el gráfico se actualiza en tiempo real (con debounce de 500ms).
Acción: Usuario hace clic en "Usar este indicador", es redirigido a /features/new con el indicador preconfigurado, completa el wizard y lanza el cálculo.
Indicadores a Documentar en V1
Los 7 indicadores ya soportados por el sistema:
SMA (Media Móvil Simple)
EMA (Media Móvil Exponencial)
RSI (Índice de Fuerza Relativa)
MACD (Convergencia/Divergencia de Medias Móviles)
BBANDS (Bandas de Bollinger)
ATR (Rango Verdadero Promedio)
VOLUME_SMA (Media Móvil Simple del Volumen)
Para cada uno se documentará: Nombre, Descripción, Fórmula, Parámetros con rangos, Señales de trading típicas e Interpretación.
Consideraciones Técnicas
6.1. Datos para los gráficos: Se usarán datos reales de velas importadas. Si no hay datos, se mostrará un mensaje indicando que se necesitan importar datos primero. Se cachearán los resultados en memoria (TTL 5 minutos) para evitar recalcular constantemente.
6.2. Rendimiento: El cálculo se hace bajo demanda. Se limitará el rango de datos del ejemplo a 90 días por defecto. El debounce en el playground evitará cálculos excesivos.
6.3. Extensibilidad: Añadir un nuevo indicador a la galería solo requiere añadir la lógica en service.py y la entrada en indicator_catalog.py. No se requieren migraciones de BD.
Dependencias
Backend: Ninguna nueva (reutiliza pandas).
Frontend: lightweight-charts (ya instalado).
Criterios de Finalización
Backend: indicator_catalog.py con los 7 indicadores documentados.
Backend: endpoints /gallery, /gallery/{name}, /gallery/{name}/example.
Frontend: página de lista con grid de tarjetas.
Frontend: página de detalle con descripción, fórmula, señales y gráfico interactivo.
Frontend: botón "Usar este indicador" que redirige al wizard.
Verificación end-to-end completa.
Estimación
Backend (catálogo + endpoints): 0.5 días
Frontend (lista + detalle + playground): 2 días
Contenido (descripciones, fórmulas, señales): 1 día
Pruebas y ajustes: 0.5 días
Total: 4 días
Notas Adicionales
Esta tarea es independiente de la Tarea 4 (Detección de Patrones).
La galería puede ampliarse gradualmente añadiendo más indicadores conforme se implementen.
Los gráficos de ejemplo son una excelente oportunidad para validar visualmente que los cálculos de indicadores son correctos.

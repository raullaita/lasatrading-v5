Tarea 4.5: Galería de Patrones de Trading
Objetivo
Crear una página de galería dedicada a los patrones de trading soportados por el motor de escaneo. Su propósito es educativo y práctico: mostrar al usuario qué busca el sistema, bajo qué condiciones se dispara una señal y cómo se ve visualmente en un gráfico real con marcadores.
Criterios de Aceptación
2.1. Funcionalidad
Acceso desde el menú lateral (item "Galería de Patrones").
Vista en grid de tarjetas con los patrones disponibles (ej: Cruce MACD, RSI Extremo, Vela Envolvente).
Vista de detalle por patrón que incluye: nombre, descripción, lógica (alcista/bajista), indicadores requeridos y un gráfico de ejemplo con datos reales.
El gráfico de ejemplo debe usar la API de marcadores (markers) de lightweight-charts para mostrar flechas (▲ verde, ▼ rojo) en las velas donde se cumplió el patrón.
Botón "Escanear este patrón" que redirige al wizard de creación de Scan Job (/patterns/new) con el patrón pre-seleccionado.
2.2. Técnico
Reutilización de componentes de la Tarea 3.5 (IndicatorCard, layout de galería) adaptados a patrones.
Los datos de ejemplo se obtienen de un escaneo precalculado o de un conjunto de datos históricos de referencia (ej: BTCUSDT 1h, últimos 6 meses).
El backend provee un endpoint que devuelve la metadata del patrón y un array de "occurrences" de ejemplo para alimentar el gráfico.
Arquitectura
3.1. Backend
Archivo: backend/app/modules/patterns/pattern_catalog.py
Diccionario con la metadata de cada patrón:
name: Nombre legible (ej: "Cruce Alcista de MACD")
code: Identificador único (ej: "MACD_CROSS_BULLISH")
description: Explicación de la lógica.
required_features: Lista de features necesarias (ej: ["MACD_12_26_9", "MACDs_12_26_9"]).
example_data: Símbolo, timeframe y un array de timestamps de ejemplo donde ocurrió el patrón, para que el frontend pueda dibujar los marcadores.
Endpoints en router.py:
GET /api/v1/patterns/gallery : Lista todos los patrones con su metadata.
GET /api/v1/patterns/gallery/{pattern_code}/example : Devuelve un FeaturePreviewOut (velas + indicadores) + un array de markers para ese patrón específico.
3.2. Frontend
Rutas:
/patterns/gallery : Grid de tarjetas de patrones.
/patterns/gallery/:patternCode : Detalle del patrón.
Componentes nuevos o adaptados:
PatternCard.tsx : Tarjeta con nombre, descripción breve y badge de "Alcista" o "Bajista".
PatternDetail.tsx : Descripción completa, requisitos y gráfico.
PatternChart.tsx : Similar a FeatureChart, pero en lugar de añadir LineSeries, utiliza candlestickSeries.setMarkers(markers) para dibujar las señales.
Flujo del Usuario
El usuario navega a la Galería de Patrones.
Ve tarjetas como "Vela Envolvente Alcista", "RSI Sobrecompra", etc.
Hace clic en "Vela Envolvente Alcista".
Lee la explicación: "Ocurre cuando una vela alcista envuelve completamente el cuerpo de la vela bajista anterior".
Ve el gráfico de ejemplo con velas y una flecha verde ▲ señalando el momento exacto del patrón.
Hace clic en "Escanear este patrón" y es llevado al wizard con ese patrón ya seleccionado.
Patrones a Documentar en V1
Los 5 patrones base del motor de escaneo:
Cruce de MACD (Alcista y Bajista)
RSI Extremo (Salida de Sobrecompra / Sobreventa)
Ruptura de Bandas de Bollinger
Cruce de Medias Móviles (EMA rápida vs lenta)
Vela Envolvente (Engulfing)
Consideraciones Técnicas
Rendimiento: Los datos de ejemplo son estáticos o se cachearán fuertemente, ya que no necesitan ser en tiempo real, solo ilustrativos.
Gráficos: Es crucial que el gráfico de la galería muestre también las líneas de los indicadores requeridos (ej: si es Cruce de MACD, el gráfico de ejemplo debe mostrar las líneas de MACD y Señal, además de los marcadores en las velas).
Consistencia: Usar los mismos colores y estilos de la Galería de Indicadores.
Dependencias
Backend: Ninguna nueva.
Frontend: lightweight-charts (ya instalado, usando la función setMarkers).
Criterios de Finalización
Catálogo de patrones definido en el backend.
Endpoints de galería funcionando.
Frontend con grid de tarjetas y vista de detalle.
Gráfico de ejemplo renderizando velas, indicadores de fondo y marcadores de señal correctamente.
Botón de redirección al escáner funcional.
Estimación
Backend (Catálogo + endpoint de ejemplo): 0.5 días
Frontend (Adaptación de componentes + lógica de markers): 1.5 días
Recopilación de ejemplos reales para los gráficos: 0.5 días
Total: 2.5 días
Notas Adicionales
Esta tarea complementa perfectamente la Tarea 4 y puede desarrollarse en paralelo o justo después del motor de escaneo.
Los marcadores (markers) en lightweight-charts son la clave visual que diferencia esta galería de la de indicadores.
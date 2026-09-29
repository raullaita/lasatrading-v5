#!/bin/bash
# `set -e` no es aqui una manía de script: sin él, un `alembic upgrade` que falla
# deja el despliegue "completado con éxito" y arranca la aplicación contra un
# esquema viejo. Es exactamente lo que pasó en el primer despliegue en el
# servidor: las migraciones de walk-forward y de alertas no se aplicaron, el
# script imprimió un ✅ y las tablas no existían. El fallo no se ve en el
# resultado, se ve tres días después en un error de columna.
set -euo pipefail
echo "🔄 Iniciando actualización de LaSaTrading v5..."

# 1. Traer los últimos cambios de Git
echo "📥 Descargando cambios de Git..."
git pull

# 2. Actualizar dependencias del backend (por si cambiaron)
echo "📦 Actualizando dependencias del backend..."
cd backend
.venv/bin/pip install -q -r requirements.txt

# 3. Aplicar nuevas migraciones de base de datos (si las hay)
echo "🗄️ Aplicando migraciones de base de datos..."
.venv/bin/alembic upgrade head
# Comprobar que la base quedó donde dice el código. `upgrade head` puede terminar
# bien y dejar la revisión a medias si la cadena de migraciones está partida, y
# eso es justo el fallo que no se ve hasta que algo escribe en una tabla que no
# existe. La revisión aplicada se imprime siempre: es la unica linea de este script
# que dice en que version de esquema quedo la base.
echo "   revision aplicada: $(.venv/bin/alembic current 2>/dev/null | tail -1)"

# 4. Actualizar dependencias del frontend (por si cambiaron)
echo "📦 Actualizando dependencias del frontend..."
cd ../frontend
npm install --silent

# 5. Reiniciar todos los servicios para aplicar los cambios
echo "🔄 Reiniciando servicios..."
cd ..
python3 manage.py restart

echo "✅ ¡Actualización completada con éxito!"
echo ""
python3 manage.py status
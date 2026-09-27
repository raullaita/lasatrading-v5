#!/bin/bash
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

# 4. Actualizar dependencias del frontend (por si cambiaron)
echo "📦 Actualizando dependencias del frontend..."
cd ../frontend
npm install --silent

# 5. Reiniciar todos los servicios para aplicar los cambios
echo "🔄 Reiniciando servicios..."
cd ..
python manage.py restart

echo "✅ ¡Actualización completada con éxito!"
echo ""
python manage.py status
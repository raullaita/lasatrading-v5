# LaSaTrading v5 — Frontend

Interfaz web de LaSaTrading construida con React 18, TypeScript, Vite 5 y Tailwind CSS 3.

## Stack

- React 18 + TypeScript
- Vite 5 (proxy de `/api` y `/ws` al backend local)
- Tailwind CSS 3 + PostCSS
- react-router-dom (navegación)
- axios (HTTP), lucide-react (iconos)
- Calidad: ESLint, Prettier, Vitest

## Estructura

```
frontend/
├── public/                # Recursos estáticos
├── src/
│   ├── main.tsx           # Punto de entrada
│   ├── App.tsx            # Layout base, rutas y navegación
│   ├── index.css          # Directivas de Tailwind
│   ├── pages/             # Páginas del módulo (bienvenida, placeholders futuros)
│   ├── components/        # Componentes reutilizables
│   ├── services/          # Clientes HTTP/API
│   └── types/             # Tipos TypeScript compartidos
├── vite.config.ts         # Puerto 5173 + proxy /api y /ws
└── tailwind.config.js     # Escaneo de clases en src/**
```

## Desarrollo

Normalmente se gestiona desde el `manage.py` de la raíz. En desarrollo manual:

```bash
npm install
npm run dev
```

El servidor de desarrollo escucha en http://localhost:5173 y redirige `/api` y `/ws` al backend en http://localhost:8000.

## Comandos

| Comando | Descripción |
| --- | --- |
| `npm run dev` | Servidor de desarrollo con recarga en caliente. |
| `npm run build` | Compilación de producción (comprueba tipos con `tsc -b`). |
| `npm run preview` | Sirve la compilación de producción localmente. |
| `npm run lint` | ESLint sobre `src/**`. |
| `npm run format` | Formatea el código con Prettier. |
| `npm run test` | Ejecuta la suite de pruebas con Vitest. |
#!/usr/bin/env python3
"""LaSaTrading v5 - script unificado de gestion del ciclo de vida local."""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")
FRONTEND = ROOT / "frontend"
PID_DIR = ROOT / ".pids"
LOG_DIR = ROOT / ".logs"
VENV = BACKEND / ".venv"

SERVICES = {
    "backend": {
        "name": "backend",
        "cwd": BACKEND,
        "url": "http://localhost:8000",
        "log": LOG_DIR / "backend.log",
    },
    "celery": {
        "name": "celery",
        "cwd": BACKEND,
        "url": None,
        "log": LOG_DIR / "celery.log",
    },
    "frontend": {
        "name": "frontend",
        "cwd": FRONTEND,
        "url": "http://localhost:5173",
        "log": LOG_DIR / "frontend.log",
    },
}

SERVICE_ORDER = ["backend", "celery", "frontend"]
SERVICE_PORTS = {"backend": 8000, "frontend": 5173}

ANSI = {
    "reset": "\033[0m",
    "green": "\033[92m",
    "red": "\033[91m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
}


def _enable_ansi_windows() -> None:
    if os.name != "nt":
        return
    import ctypes
    import ctypes.wintypes

    kernel32 = ctypes.windll.kernel32
    out = ctypes.wintypes.HANDLE(kernel32.GetStdHandle(-11))
    mode = ctypes.wintypes.DWORD()
    kernel32.GetConsoleMode(out, ctypes.byref(mode))
    kernel32.SetConsoleMode(out, mode.value | 0x0004)


def color(text: str, key: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{ANSI[key]}{text}{ANSI['reset']}"


def banner(text: str) -> None:
    print()
    print(color(f"== {text} ==", "cyan"))


def ok(text: str) -> None:
    print(color(f"[OK] {text}", "green"))


def warn(text: str) -> None:
    print(color(f"[WARN] {text}", "yellow"))


def err(text: str) -> None:
    print(color(f"[ERROR] {text}", "red"))


def fail(text: str, code: int = 1) -> None:
    err(text)
    raise SystemExit(code)


def _run(
    cmd, cwd=None, capture: bool = True, check: bool = True
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() if capture else ""
        fail(f"Fallo al ejecutar: {' '.join(cmd)}\n{detail}")
    return result


def _run_visible(cmd, cwd=None) -> subprocess.CompletedProcess:
    print(color(f"> {' '.join(cmd)}", "cyan"))
    return _run(cmd, cwd=cwd, capture=False, check=False)


def compose_cmd() -> list:
    for candidate in (["docker", "compose"], ["docker-compose"]):
        probe = _run(candidate + ["version"], capture=True, check=False)
        if probe.returncode == 0:
            return candidate
    fail(
        "Docker Compose no está disponible. Instala docker-compose o usa el plugin de Docker Compose."
    )
    return []


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def check_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        fail(f"{name} no está instalado o no está en el PATH.")
    return path


def check_python() -> str:
    for candidate in ("python", "python3"):
        path = shutil.which(candidate)
        if not path:
            continue
        version = _run([path, "--version"], check=False)
        datum = version.stdout.strip()
        try:
            major, minor = (int(p) for p in datum.replace("Python ", "").split(".")[:2])
        except (ValueError, IndexError):
            continue
        if (major, minor) >= (3, 9):
            return path
    fail("Se requiere Python >= 3.9.")
    return ""


def check_node() -> str:
    path = check_tool("node")
    version = _run([path, "--version"], check=False).stdout.strip().lstrip("v")
    try:
        major = int(version.split(".")[0])
    except ValueError:
        fail("No se pudo determinar la versión de Node.")
    if major < 18:
        fail(f"Se requiere Node >= 18 (encontrado v{version}).")
    return path


def check_docker() -> None:
    if shutil.which("docker") is None and shutil.which("docker-compose") is None:
        fail("Docker no está instalado o no está en el PATH.")
    probe = _run(["docker", "version", "--format", "{{.Server.Version}}"], check=False)
    if probe.returncode != 0:
        fail(
            "Docker está instalado pero el demonio no está corriendo. Inicia Docker y reintenta."
        )
    compose_cmd()


def verify_environment() -> None:
    banner("Comprobando entorno")
    check_python()
    check_node()
    check_docker()
    ok("Python >= 3.9, Node >= 18 y Docker disponibles")


def ensure_dirs() -> None:
    PID_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


def install_backend_deps(python_cmd: str) -> None:
    banner("Instalando dependencias del backend")
    if not (VENV / "pyvenv.cfg").exists():
        _run_visible([python_cmd, "-m", "venv", str(VENV)])
    _run_visible([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    _run_visible(
        [
            str(venv_python()),
            "-m",
            "pip",
            "install",
            "-r",
            str(BACKEND / "requirements.txt"),
        ]
    )
    ok("Dependencias del backend instaladas")


def install_frontend_deps() -> None:
    banner("Instalando dependencias del frontend")
    npm = shutil.which("npm")
    if not npm:
        fail("npm no está instalado o no está en el PATH.")
    _run_visible([npm, "install"], cwd=FRONTEND)
    ok("Dependencias del frontend instaladas")


def provision_env() -> None:
    banner("Configurando variables de entorno")
    backend_env = BACKEND / ".env"
    if not backend_env.exists():
        shutil.copy2(BACKEND / ".env.example", backend_env)
        root_env = ROOT / ".env"
        docker_keys = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        values = []
        with backend_env.open() as handle:
            for line in handle:
                key, sep, _ = line.partition("=")
                if sep and key.strip() in docker_keys:
                    values.append(line.strip())
        if not root_env.exists() and values:
            root_env.write_text("\n".join(values) + "\n")
    ok("Archivos .env configurados")


def git_init() -> None:
    banner("Inicializando repositorio Git")
    is_repo = (
        _run(["git", "rev-parse", "--is-inside-work-tree"], check=False).returncode == 0
    )
    if not is_repo:
        init = _run(["git", "init", "-b", "main"], check=False)
        if init.returncode != 0:
            _run(["git", "init"], check=False)
            _run(["git", "checkout", "-b", "main"], check=False)
    if _run(["git", "config", "--get", "user.email"], check=False).returncode != 0:
        _run(["git", "config", "user.email", "dev@lasatrading.local"], check=False)
    if _run(["git", "config", "--get", "user.name"], check=False).returncode != 0:
        _run(["git", "config", "user.name", "LaSaTrading"], check=False)
    _run(["git", "add", "-A"], check=False)
    commit = _run(
        [
            "git",
            "commit",
            "-m",
            "Initial commit - Tarea 1: inicializacion del proyecto",
        ],
        check=False,
    )
    if commit.returncode == 0:
        ok("Commit inicial creado")
    else:
        warn("Ya existía un commit anterior; no se creó un commit nuevo")


def docker_up() -> None:
    banner("Levantando infraestructura Docker")
    probe = _run(compose_cmd() + ["up", "-d"], cwd=ROOT, capture=True, check=False)
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()[-1200:]
        fail(f"docker compose up -d falló:\n{detail}")
    ok("Infraestructura Docker levantada")


def docker_down() -> None:
    print(color("Deteniendo infraestructura Docker", "cyan"))
    _run(compose_cmd() + ["down"], cwd=ROOT, capture=False, check=False)


def command_setup() -> None:
    _enable_ansi_windows()
    banner("SETUP LaSaTrading v5")
    ensure_dirs()
    python_cmd = check_python()
    check_node()
    check_docker()
    verify_environment()
    install_backend_deps(python_cmd)
    install_frontend_deps()
    provision_env()
    git_init()
    docker_up()
    banner("Setup completado")
    print("Ejecuta 'python manage.py start' para levantar todos los servicios.")
    command_status()


def pid_file(name: str) -> Path:
    return PID_DIR / f"{name}.pid"


def read_pid(name: str) -> int | None:
    path = pid_file(name)
    if not path.exists():
        return None
    try:
        raw = path.read_text().strip()
        return int(raw) if raw else None
    except ValueError:
        return None


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    if os.name == "nt":
        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in probe.stdout
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    except PermissionError:
        return True
    return True


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        result = sock.connect_ex(("127.0.0.1", port))
    return result == 0


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def service_cmd(name: str) -> list:
    python = str(venv_python())
    if name == "backend":
        return [
            python,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            os.environ.get("API_HOST", "127.0.0.1"),
            "--port",
            "8000",
        ]
    if name == "celery":
        return [
            python,
            "-m",
            "celery",
            "-A",
            "app.core.celery_app",
            "worker",
            "-l",
            "INFO",
        ]
    if name == "frontend":
        npm = shutil.which("npm")
        if not npm:
            fail("npm no está instalado o no está en el PATH.")
        return [npm, "run", "dev"]
    fail(f"Servicio desconocido: {name}")
    return []


def start_one(name: str) -> None:
    existing = read_pid(name)
    if existing and pid_alive(existing):
        warn(f"{name} ya está en marcha (PID {existing})")
        return
    port = SERVICE_PORTS.get(name)
    if port and port_in_use(port):
        fail(
            f"El puerto {port} ya está en uso por otro proceso. "
            "Cierra los procesos que lo ocupen e intenta de nuevo."
        )
    if name in ("backend", "celery") and not venv_python().exists():
        fail("No existe backend/.venv. Ejecuta primero 'python manage.py setup'.")
    if name == "frontend" and not (FRONTEND / "node_modules").exists():
        fail(
            "No existe frontend/node_modules. Ejecuta primero 'python manage.py setup'."
        )

    info = SERVICES[name]
    log_file = info["log"].open("a", buffering=1)
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    print(color(f"Arrancando {name}: {' '.join(service_cmd(name))}", "cyan"))
    process = subprocess.Popen(
        service_cmd(name),
        cwd=str(info["cwd"]),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )
    pid_file(name).write_text(str(process.pid))

    deadline = time.time() + 20
    ready = False
    if info["url"]:
        while time.time() < deadline:
            if not pid_alive(process.pid):
                break
            if http_ok(info["url"]):
                ready = True
                break
            time.sleep(0.5)
    else:
        time.sleep(4)
        ready = pid_alive(process.pid)

    if not ready:
        pid_file(name).unlink(missing_ok=True)
        log_file.close()
        tail = ""
        if info["log"].exists():
            tail = "\n".join(info["log"].read_text().splitlines()[-12:])
        fail(
            f"{name} terminó inesperadamente al arrancar.\nÚltimas líneas del log:\n{tail}"
        )
    ok(f"{name} iniciado (PID {process.pid})")


def terminate_process(pid: int, force: bool = False) -> None:
    if os.name == "nt":
        cmd = ["taskkill"]
        if force:
            cmd.append("/F")
        cmd += ["/T", "/PID", str(pid)]
        subprocess.run(cmd, check=False)
        return
    try:
        if force:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass


def command_start() -> None:
    _enable_ansi_windows()
    ensure_dirs()
    banner("START LaSaTrading v5")
    if not venv_python().exists():
        fail("No existe backend/.venv. Ejecuta primero 'python manage.py setup'.")
    docker_up()
    for name in SERVICE_ORDER:
        start_one(name)
    banner("Estado tras arrancar")
    command_status()


def command_stop() -> None:
    _enable_ansi_windows()
    banner("STOP LaSaTrading v5")
    for name in SERVICE_ORDER:
        pid = read_pid(name)
        if pid and pid_alive(pid):
            print(color(f"Deteniendo {name} (PID {pid})...", "cyan"))
            terminate_process(pid)
            deadline = time.time() + 5
            while time.time() < deadline and pid_alive(pid):
                time.sleep(0.25)
            if pid_alive(pid):
                print(color(f"{name} no terminó; forzando cierre...", "yellow"))
                terminate_process(pid, force=True)
            else:
                ok(f"{name} detenido")
        else:
            warn(f"{name} no estaba en marcha")
    docker_down()
    for path in PID_DIR.glob("*.pid"):
        path.unlink(missing_ok=True)
    ok("Entorno detenido y limpio")


def command_restart() -> None:
    command_stop()
    command_start()


def docker_status_lines() -> list:
    probe = _run(
        compose_cmd() + ["ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"],
        cwd=ROOT,
        check=False,
    )
    lines = probe.stdout.strip().splitlines() if probe.returncode == 0 else []
    if len(lines) <= 1:
        return []
    return lines


def command_status() -> None:
    _enable_ansi_windows()
    banner("STATUS LaSaTrading v5")

    docker_ok = (
        _run(
            ["docker", "version", "--format", "{{.Server.Version}}"], check=False
        ).returncode
        == 0
    )
    label = color(
        "Docker disponible" if docker_ok else "Docker NO disponible",
        "green" if docker_ok else "red",
    )
    print(f"  Infraestructura: {label}")

    containers = docker_status_lines()
    if containers:
        for line in containers:
            print(f"    {line.strip()}")
    else:
        print(f"    {color('Sin contenedores Docker en marcha', 'yellow')}")

    print()
    for name in SERVICE_ORDER:
        pid = read_pid(name)
        info = SERVICES[name]
        alive = pid_alive(pid)
        url = info["url"]
        if alive:
            reachable = http_ok(url) if url else False
            state = color(f"ACTIVO (PID {pid})", "green")
            linked = ""
            if url:
                linked = f"  ->  {color(url, 'cyan')} {color('respondiendo' if reachable else 'no responde', 'green' if reachable else 'red')}"
        else:
            state = color("DETENIDO", "red")
            linked = ""
        print(f"  {name:<10} {state}{linked}")

    print()
    print("  URLs de acceso:")
    print(f"    Frontend: {color('http://localhost:5173', 'cyan')}")
    print(f"    Backend:  {color('http://localhost:8000', 'cyan')}")
    print(f"    Docs API: {color('http://localhost:8000/docs', 'cyan')}")
    print()


def follow_log(path: Path) -> None:
    with path.open("r") as handle:
        handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
            else:
                time.sleep(0.25)


def command_logs(name: str) -> None:
    _enable_ansi_windows()
    if name == "docker":
        try:
            subprocess.run(compose_cmd() + ["logs", "-f"], cwd=str(ROOT), check=False)
        except KeyboardInterrupt:
            print()
        return
    info = SERVICES.get(name)
    if not info:
        fail(
            f"Servicio inválido: '{name}'. Usa 'docker', 'backend', 'celery' o 'frontend'."
        )
    path = info["log"]
    if not path.exists():
        fail(f"No existe el archivo de log {path}. Inicia el servicio primero.")
    print(color(f"Mostrando logs de {name} (Ctrl+C para salir)...", "cyan"))
    try:
        follow_log(path)
    except KeyboardInterrupt:
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gestión del ciclo de vida de LaSaTrading v5"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Instalación inicial completa del proyecto")
    subparsers.add_parser("start", help="Arranca Docker, backend, celery y frontend")
    subparsers.add_parser(
        "stop", help="Detiene todos los servicios y la infraestructura"
    )
    subparsers.add_parser(
        "restart", help="Detiene y vuelve a arrancar todos los servicios"
    )

    parser_status = subparsers.add_parser(
        "status", help="Muestra el estado de todos los servicios"
    )
    parser_status.add_argument(
        "--watch", action="store_true", help="Actualizar el estado periódicamente"
    )

    parser_logs = subparsers.add_parser(
        "logs", help="Muestra logs de un servicio en tiempo real"
    )
    parser_logs.add_argument(
        "service",
        nargs="?",
        default="backend",
        choices=["docker", "backend", "celery", "frontend"],
        help="Servicio del que ver logs (por defecto: backend)",
    )

    args = parser.parse_args()

    if args.command == "setup":
        command_setup()
    elif args.command == "start":
        command_start()
    elif args.command == "stop":
        command_stop()
    elif args.command == "restart":
        command_restart()
    elif args.command == "status":
        if args.watch:
            while True:
                command_status()
                time.sleep(5)
        else:
            command_status()
    elif args.command == "logs":
        command_logs(args.service)


if __name__ == "__main__":
    main()

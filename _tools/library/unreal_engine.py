"""Unreal Engine на этом компьютере: где движок, какие проекты, и импорт прямо в проект без открытия
редактора (коммандлет pythonscript запускает import_to_unreal.py). Без Qt.

- движки - из реестра Epic Games Launcher, папок Epic Games и «D:\\Unreal Engine\\UE_*»;
- проекты - «Документы\\Unreal Projects» и запомненные в настройках;
- импорту нужен Python Editor Script Plugin в проекте (python_enabled), а редактор с этим проектом
  должен быть закрыт: иначе пусть импортирует сам редактор (Output Log, команда py)."""

import glob
import json
import os
import re
import subprocess
import threading
import time

from library import unreal_import


def _registry_engines():
    out = {}
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\EpicGames\Unreal Engine") as k:
                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(k, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(k, ver) as v:
                                out[ver] = winreg.QueryValueEx(v, "InstalledDirectory")[0]
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    return out


def engines():
    """{версия: папка движка}: «5.8» -> D:\\Unreal Engine\\UE_5.8."""
    out = dict(_registry_engines())
    for pat in (
        r"C:\Program Files\Epic Games\UE_*",
        r"D:\Program Files\Epic Games\UE_*",
        r"D:\Unreal Engine\UE_*",
        r"C:\Unreal Engine\UE_*",
        r"D:\Epic Games\UE_*",
    ):
        for d in glob.glob(pat):
            m = re.search(r"UE_(\d+\.\d+)", d)
            if m and m.group(1) not in out:
                out[m.group(1)] = d
    return {v: d for v, d in out.items() if os.path.exists(cmd_exe(d))}


def cmd_exe(engine_dir):
    return os.path.join(engine_dir, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")


def projects(extra=()):
    """Проекты: [путь .uproject], свежие первыми."""
    roots = [os.path.join(os.path.expanduser("~"), "Documents", "Unreal Projects")]
    found = set()
    for r in roots:
        found |= set(glob.glob(os.path.join(r, "*", "*.uproject")))
    found |= {p for p in extra if os.path.exists(p)}
    return sorted(found, key=lambda p: -os.path.getmtime(p))


def read_project(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def engine_for(project, known=None):
    """Папка движка для проекта: по EngineAssociation («5.8»); нет такого - самый новый."""
    known = engines() if known is None else known
    if not known:
        return None
    try:
        ver = str(read_project(project).get("EngineAssociation", ""))
    except (OSError, ValueError):
        ver = ""
    if ver in known:
        return known[ver]
    return known[max(known, key=lambda v: tuple(int(x) for x in v.split(".") if x.isdigit()))]


def python_enabled(project):
    """Включён ли в проекте Python Editor Script Plugin (без него скрипт импорта не запустится)."""
    try:
        plugins = read_project(project).get("Plugins", [])
    except (OSError, ValueError):
        return False
    return any(p.get("Name") == "PythonScriptPlugin" and p.get("Enabled") for p in plugins)


def enable_python(project):
    """Включить Python Editor Script Plugin в .uproject (старый - копией .bak рядом)."""
    data = read_project(project)
    plugins = data.setdefault("Plugins", [])
    for name in ("PythonScriptPlugin", "EditorScriptingUtilities"):
        p = next((x for x in plugins if x.get("Name") == name), None)
        if p is None:
            plugins.append({"Name": name, "Enabled": True})
        else:
            p["Enabled"] = True
    import shutil

    shutil.copy2(project, project + ".bak")
    with open(project, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent="\t")


def editor_running(project=None):
    """Открыт ли редактор Unreal (с этим проектом, если удаётся узнать)."""
    try:  # wmic в новых Windows 11 убран - командные строки процессов даёт PowerShell
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "  # путь «Документы» - не кракозябрами
                "Get-CimInstance Win32_Process -Filter \"Name='UnrealEditor.exe'\" | "
                "ForEach-Object { 'UnrealEditor ' + $_.CommandLine }",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            raise OSError(r.stderr)
        out = r.stdout
    except Exception:
        try:
            out = subprocess.run(
                ["tasklist", "/fi", "imagename eq UnrealEditor.exe"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except Exception:
            return False
    if "UnrealEditor" not in out:
        return False
    if project is None:
        return True
    name = os.path.basename(project).lower()
    return name in out.lower() or "uproject" not in out.lower()  # не видно, какой проект - считаем, что этот


def import_folder(project):
    """Куда копировать файлы перед импортом: Saved проекта (не Content - туда Unreal кладёт свои .uasset)."""
    return os.path.join(os.path.dirname(project), "Saved", "LibraryImport", time.strftime("%Y-%m-%d_%H%M%S"))


def import_into(assets, project, engine_dir=None, log=None, timeout=1800):
    """Скопировать ассеты и импортировать их в проект без открытия редактора.
    -> {ok, imported: [имена], errors: [строки], log: путь журнала Unreal}."""
    project = os.path.realpath(project)  # короткое имя 8.3 (MOONLI~1) Unreal не сопоставит с Content - падает
    engine_dir = engine_dir or engine_for(project)
    if not engine_dir:
        raise FileNotFoundError("Unreal Engine не найден")
    folder = import_folder(project)
    script = os.path.realpath(unreal_import.export(assets, folder))
    ue_log = os.path.join(folder, "unreal.log")
    args = [
        cmd_exe(engine_dir),
        project,
        "-run=pythonscript",
        f"-script={script}",
        "-unattended",
        "-nopause",
        "-nosplash",
        "-stdout",
        "-FullStdOutLogOutput",
    ]
    with open(ue_log, "w", encoding="utf-8", errors="replace") as fh:
        p = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        imported, errors = [], []
        # чтение вывода ждёт конца Unreal: завис молча - сторож снимает его по времени
        hung = []
        watchdog = threading.Timer(timeout, lambda: (hung.append(True), p.kill()))
        watchdog.daemon = True
        watchdog.start()
        t0 = time.time()
        for line in p.stdout:
            fh.write(line)
            if "Библиотека: импортировано" in line:
                m = re.search(r"импортировано (.+?) \(", line)
                imported.append(m.group(1) if m else line.strip())
                if log:
                    log(f"{len(imported)} из {len(assets)}: {imported[-1]}")
            elif re.search(r"LogPython: Error|Error: .*Python|Traceback", line):
                errors.append(line.strip()[-300:])
            elif log and time.time() - t0 > 2 and "LogInit" in line:
                log("Unreal запускается...")
                t0 = time.time()
        p.wait()
        watchdog.cancel()
        if hung:
            errors.append(f"Unreal не ответил за {timeout // 60} мин - остановлен")
    return {
        "ok": p.returncode == 0 and not errors and len(imported) == len(assets),
        "imported": imported,
        "errors": errors,
        "log": ue_log,
        "code": p.returncode,
        "folder": folder,
    }

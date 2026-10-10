#!/usr/bin/env python3
"""Сервер MCP: ИИ-помощники (Claude Code, Claude Desktop, Cursor, VS Code и др.) ищут, смотрят и правят
картинки библиотеки. Протокол - JSON-RPC по stdin/stdout, без сторонних пакетов. Операции - library/api.py.

Подключение (путь - к этому файлу):
  claude mcp add image-library -- py -3.14 "D:/.../_tools/mcp_server.py"
  или в .mcp.json / claude_desktop_config.json:
  {"mcpServers": {"image-library": {"command": "py", "args": ["-3.14", "D:/.../_tools/mcp_server.py"]}}}
В корне библиотеки уже лежит .mcp.json - Claude Code, открытый в этой папке, найдёт сервер сам.
Окно не обязательно: база общая, и всё сделанное помощником окно показывает и отменяет (Ctrl+Z)."""

import base64
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = """Библиотека картинок пользователя (иконки, наклейки, маскоты, фоны...). Начните с overview -
там разделы, метки и правила раскладки. Искать: search (слова или описание по смыслу), similar.
Смотреть: view (вернёт изображение с номерами). Менять: tag, note, favorite, rename, move, trash, edit,
remove_background, upscale, convert, cut_sheet. Перед правкой - edit(mode="preview"). Всё отменяется
undo, а пользователь видит ваши действия в окне и может отменить их сам. Показать найденное пользователю
прямо в окне - show(paths) и ue_show(ids). Ассеты для Unreal Engine (модели, текстуры, HDRI) - ue_overview,
ue_search (группы и разделы, стиль real/low-poly), ue_plan_room, ue_collection, ue_download, ue_import."""


_out = None  # настоящий stdout - только для ответов протокола (см. guard_stdout)


def guard_stdout():
    """Канал протокола - только для JSON. Всё остальное (print в модулях, предупреждения onnxruntime,
    вывод Blender и других дочерних программ) уходит в stderr, иначе клиент получит мусор и оборвёт связь."""
    global _out
    _out = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())  # и для дочерних процессов: они наследуют дескриптор 1
    sys.stdout = sys.stderr


def send(msg):
    data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    if _out is None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        _out.write(data)


def tool_list(api):
    out = []
    for name, t in api.TOOLS.items():
        out.append(
            dict(
                name=name,
                description=t["desc"],
                inputSchema=t["schema"],
                annotations=dict(readOnlyHint=not t["write"], destructiveHint=t["destructive"], openWorldHint=False),
            )
        )
    return out


def content(api, res):
    """Ответ операции -> содержимое MCP: картинка - изображением, остальное - JSON текстом."""
    if isinstance(res, api.Picture):
        out = [dict(type="image", data=base64.b64encode(res.png()).decode("ascii"), mimeType="image/png")]
        if res.text:
            out.append(dict(type="text", text=res.text))
        return out
    return [dict(type="text", text=json.dumps(res, ensure_ascii=False, indent=1, default=str))]


def handle(api, msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        info = params.get("clientInfo") or {}
        if info.get("name"):
            api.AGENT["who"] = "ИИ (%s)" % info["name"]
        want = params.get("protocolVersion")
        return dict(
            protocolVersion=want if want in PROTOCOLS else PROTOCOLS[0],
            capabilities=dict(tools=dict(listChanged=False)),
            serverInfo=dict(name="image-library", title="Библиотека картинок", version=api.C.VERSION),
            instructions=INSTRUCTIONS,
        )
    if method == "ping":
        return {}
    if method == "tools/list":
        return dict(tools=tool_list(api))
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        token = (params.get("_meta") or {}).get("progressToken")
        progress = None
        if token is not None:  # помощник просил ход работы - шлём notifications/progress

            def progress(done, total=None, message=""):
                note = {"progressToken": token, "progress": done}
                if total:
                    note["total"] = total
                if message:
                    note["message"] = message
                send(dict(jsonrpc="2.0", method="notifications/progress", params=note))

        try:
            return dict(content=content(api, api.call(name, args, progress)))
        except api.ApiError as e:
            return dict(content=[dict(type="text", text=str(e))], isError=True)
        except Exception as e:
            api.C.log_error(f"mcp {name}: " + traceback.format_exc())
            return dict(content=[dict(type="text", text=f"Ошибка: {e}")], isError=True)
    if mid is not None:
        raise LookupError(method)
    return None


def main():
    guard_stdout()
    from library import api  # после sys.path; дочерние процессы (сжатие по ядрам) сюда не заходят

    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            send(dict(jsonrpc="2.0", id=None, error=dict(code=-32700, message="parse error")))
            continue
        for m in msg if isinstance(msg, list) else [msg]:
            mid = m.get("id")
            try:
                res = handle(api, m)
            except LookupError:
                send(dict(jsonrpc="2.0", id=mid, error=dict(code=-32601, message=f"нет метода {m.get('method')}")))
                continue
            except Exception as e:
                send(dict(jsonrpc="2.0", id=mid, error=dict(code=-32603, message=str(e))))
                continue
            if mid is not None and res is not None:
                send(dict(jsonrpc="2.0", id=mid, result=res))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""打包产物精简：删掉 WebEngine 的调试资源、多余语言包，以及没被依赖的 Qt DLL。

用 PE 导入表分析依赖关系，只删除确实没人引用的 DLL，避免误删导致启动失败。
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = os.path.join(ROOT, "dist", "CampusNetAutoConnect", "_internal")
PYSIDE = os.path.join(INTERNAL, "PySide6")

# 明确用不到的数据文件
DROP_SUFFIX = (".debug.pak", ".debug.bin")
DROP_EXACT = {"qtwebengine_devtools_resources.pak"}

KEEP_LOCALES = {"en-US.pak", "zh-CN.pak"}
KEEP_QM = {"qtbase_zh_CN.qm", "qtbase_en.qm"}

# 被 Qt 动态加载的插件目录，不动
KEEP_DIRS = {"plugins", "Qt"}


def human(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


def drop(path: str) -> int:
    """删文件并返回大小。用 shell 的 rm 绕过回收站策略。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    subprocess.run(["rm", "-f", path], check=False)
    return 0 if os.path.exists(path) else size


def collect_imports(paths) -> set:
    """收集所有二进制文件的导入 DLL 名（小写）。"""
    import pefile
    needed = set()
    for p in paths:
        try:
            pe = pefile.PE(p, fast_load=True)
            pe.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
            for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
                for entry in getattr(pe, attr, []) or []:
                    if entry.dll:
                        needed.add(entry.dll.decode("ascii", "ignore").lower())
            pe.close()
        except Exception:
            continue
    return needed


def main():
    if not os.path.isdir(INTERNAL):
        print("找不到打包目录：", INTERNAL)
        return 1
    freed = 0

    # 1) 数据文件
    res = os.path.join(PYSIDE, "resources")
    if os.path.isdir(res):
        for name in os.listdir(res):
            path = os.path.join(res, name)
            if not os.path.isfile(path):
                continue
            if name.endswith(DROP_SUFFIX) or name in DROP_EXACT:
                freed += drop(path)

    # 2) 语言包
    tr = os.path.join(PYSIDE, "translations")
    if os.path.isdir(tr):
        loc = os.path.join(tr, "qtwebengine_locales")
        if os.path.isdir(loc):
            for name in os.listdir(loc):
                path = os.path.join(loc, name)
                if not os.path.isfile(path):
                    continue
                if name not in KEEP_LOCALES:
                    freed += drop(path)
        for name in os.listdir(tr):
            path = os.path.join(tr, name)
            if not os.path.isfile(path):
                continue
            if name.endswith(".qm") and name not in KEEP_QM:
                freed += drop(path)

    # 3) 依赖分析后删除无用 DLL
    binaries = []
    for base, dirs, files in os.walk(INTERNAL):
        dirs[:] = [d for d in dirs if d not in KEEP_DIRS]
        for f in files:
            if f.lower().endswith((".exe", ".dll", ".pyd")):
                binaries.append(os.path.join(base, f))
    needed = collect_imports(binaries)
    print(f"导入表共引用 {len(needed)} 个 DLL")

    removed = []
    for base, dirs, files in os.walk(PYSIDE):
        dirs[:] = [d for d in dirs if d not in KEEP_DIRS]
        for f in files:
            if not f.lower().endswith(".dll"):
                continue
            if f.startswith("Qt6") and f.lower() not in needed:
                path = os.path.join(base, f)
                size = drop(path)
                if size:
                    removed.append(f)
                    freed += size
    # 顶部独立 dll
    for f in ("opengl32sw.dll", "d3dcompiler_47.dll"):
        path = os.path.join(PYSIDE, f)
        if os.path.isfile(path) and f.lower() not in needed:
            size = drop(path)
            if size:
                freed += size
                removed.append(f)

    if removed:
        print("已删除 DLL：" + "、".join(sorted(removed)))
    total = 0
    for base, _d, files in os.walk(os.path.join(ROOT, "dist")):
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    print(f"释放约 {human(freed)}，当前总体积 {human(total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

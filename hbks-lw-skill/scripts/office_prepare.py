#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_office_env.py —— Office 自动化共用的环境准备与安全收尾

为什么需要它
------------
Word / Visio 的 COM 接口在启动和重排（Repaginate）时，会用**当前默认打印机**的驱动
去取纸张尺寸和可打印区域，这是 Word 计算分页的前提，无法关闭。如果默认打印机是一台
网络打印机（WSD/IPP 端口），每次自动化都会去探测那台设备：

  - 打印机关机或不在同一网段时，Word 会卡在设备探测上数十秒甚至几分钟；
  - 打印机在线时也会让面板异响、亮屏，看起来像"自动连了打印机"。

本模块在调用 Office 前把默认打印机临时切成虚拟 PDF 打印机（不产生任何真实打印），
结束后再恢复用户原来的默认打印机。无论脚本正常结束还是抛异常都会恢复。

用法
----
    from office_prepare import prepare_office

    with prepare_office() as env:
        word = win32com.client.Dispatch("Word.Application")
        ...                     # 这里的 Word/Visio 自动化都不会碰网络打印机
    # 退出 with 时自动恢复原默认打印机

也可以用 `python office_prepare.py --status` 查看当前状态。
"""
import argparse
import ctypes
import sys

# 虚拟打印机候选（按优先级）：都是本地打印机，不需要任何外部设备
VIRTUAL_PRINTER_CANDIDATES = [
    "Microsoft Print to PDF",
    "Microsoft XPS Document Writer",
    "OneNote (Desktop)",
]

# 这些端口说明队列指向外部设备，自动化时不应作为默认打印机
NETWORK_PORT_PREFIXES = ("WSD-", "IPP-", "TCP", "USB")


def _list_printers():
    """返回 [(name, port)]，失败时返回空列表。"""
    try:
        import win32print
    except ImportError:
        return []
    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        result = []
        for p in win32print.EnumPrinters(flags, None, 2):
            result.append((p["pPrinterName"], p.get("pPortName", "")))
        return result
    except Exception:
        return []


def get_default_printer():
    """返回当前默认打印机名；取不到返回 None。"""
    try:
        import win32print
        return win32print.GetDefaultPrinter()
    except Exception:
        pass
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = ctypes.c_ulong(len(buf))
        if ctypes.windll.winspool.GetDefaultPrinterW(buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    return None


def set_default_printer(name):
    """设置默认打印机；成功返回 True。"""
    try:
        import win32print
        win32print.SetDefaultPrinter(name)
        return True
    except Exception:
        pass
    try:
        return bool(ctypes.windll.winspool.SetDefaultPrinterW(name))
    except Exception:
        return False


def is_network_printer(port):
    """端口名是否指向外部/网络设备。"""
    if not port:
        return False
    return port.upper().startswith(NETWORK_PORT_PREFIXES)


def pick_virtual_printer(printers=None):
    """在已安装打印机里挑一台可用的本地虚拟打印机，返回名字或 None。"""
    printers = printers if printers is not None else _list_printers()
    by_name = {name: port for name, port in printers}
    for candidate in VIRTUAL_PRINTER_CANDIDATES:
        if candidate in by_name:
            return candidate
    # 退一步：任何非网络端口的本地打印机都比网络打印机安全
    for name, port in printers:
        if not is_network_printer(port):
            return name
    return None


class OfficeEnv:
    """记录被临时替换的默认打印机，负责恢复。"""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.original = None
        self.temporary = None
        self.switched = False

    def _say(self, msg):
        if self.verbose:
            print(msg)

    def __enter__(self):
        self.original = get_default_printer()
        printers = _list_printers()
        if not printers:
            self._say("[office_env] 无法枚举打印机，跳过默认打印机隔离")
            return self

        port_map = {name: port for name, port in printers}
        if not is_network_printer(port_map.get(self.original, "")):
            return self                     # 已经是本地打印机，无需处理

        target = pick_virtual_printer(printers)
        if not target or target == self.original:
            self._say("[office_env] 未找到可用的本地虚拟打印机，"
                      "Word 自动化可能触发默认网络打印机探测")
            return self

        if set_default_printer(target):
            self.temporary = target
            self.switched = True
            self._say(f"[office_env] 自动化期间默认打印机临时切换："
                      f"{self.original} -> {target}")
        else:
            self._say("[office_env] 切换默认打印机失败，继续执行")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.switched and self.original:
            if set_default_printer(self.original):
                self._say(f"[office_env] 已恢复默认打印机：{self.original}")
            else:
                self._say(f"[office_env] 恢复默认打印机失败，请手动设回：{self.original}")
        return False                        # 不吞异常


def prepare_office(verbose=True):
    """上下文管理器入口，用法：with prepare_office() as env: ..."""
    return OfficeEnv(verbose=verbose)


def _status():
    default = get_default_printer()
    printers = _list_printers()
    port_map = {name: port for name, port in printers}
    print(f"默认打印机：{default}")
    if default:
        port = port_map.get(default, "")
        kind = "网络/外部设备" if is_network_printer(port) else "本地队列"
        print(f"  端口：{port or '(未知)'}  ->  {kind}")
    print("\n已安装打印机：")
    for name, port in printers:
        mark = " *" if name == default else "  "
        kind = "[网络]" if is_network_printer(port) else "[本地]"
        print(f"{mark} {kind} {name}  ({port})")
    target = pick_virtual_printer(printers)
    print(f"\nOffice 自动化建议使用：{target or '(无可用本地虚拟打印机)'}")


def main():
    ap = argparse.ArgumentParser(description="Office 自动化环境准备")
    ap.add_argument("--status", action="store_true", help="显示打印机状态")
    args = ap.parse_args()
    if args.status:
        _status()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

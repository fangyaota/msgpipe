# -*- coding: utf-8 -*-
"""从 Weixin.exe 进程内存里找图片 AES 密钥（V2 .dat 用），提权版。

V2 结构：[6B 070856320807][4B aes_size LE][4B xor_size LE][1B 填充]
          [aes_size 字节 AES-128-ECB 密文][中间明文][xor_size 字节单字节 XOR]

AES 密钥是账户级 16 字节 ASCII，只在微信里看过图片时驻留内存。
候选过滤：16 字节全是 [0-9A-Za-z+/=] 的窗口，AES 解首块看是否 FF D8 FF。
"""
import ctypes
import ctypes.wintypes as wt
import glob
import os
import struct
import subprocess
import sys
import time

import numpy as np
from Crypto.Cipher import AES

MAGIC = b"\x07\x08V2\x08\x07"
PAGE = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
READABLE = (0x02, 0x04, 0x20, 0x40)


def find_dat():
    root = os.path.join(os.environ["USERPROFILE"], "xwechat_files")
    cands = glob.glob(os.path.join(root, "*", "msg", "attach", "*", "*", "Img", "*.dat"))
    cands = [c for c in cands if not c.endswith("_t.dat")]
    if not cands:
        sys.exit("没找到 .dat")
    return sorted(cands, key=os.path.getmtime)[-1]


def cipher_block(path):
    d = open(path, "rb").read(64)
    if d[:6] != MAGIC:
        sys.exit("不是 V2：" + path)
    return d[15:31]


def pids_of(names):
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace").stdout
    got = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() in names:
            try:
                got.append(int(parts[1]))
            except ValueError:
                pass
    return got


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


def scan(pid, block, want_all=False):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print("  OpenProcess 失败（需要管理员）")
        return None
    buf = ctypes.create_string_buffer(PAGE * 32)
    read = ctypes.c_size_t(0)
    mbi = MBI()
    addr = 0
    hits = []
    scanned = 0
    t0 = time.time()
    allowed = np.frombuffer(b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/=", dtype=np.uint8)
    try:
        while addr < 0x7FFFFFFF0000:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                addr += PAGE
                continue
            size = int(mbi.RegionSize)
            if mbi.State == 0x1000 and int(mbi.Protect) in READABLE and 0 < size <= 64 * 1024 * 1024:
                off = 0
                while off < size:
                    chunk = min(len(buf), size - off)
                    if k32.ReadProcessMemory(h, ctypes.c_void_p(addr + off), buf, chunk, ctypes.byref(read)) and read.value >= 16:
                        data = np.frombuffer(buf.raw[:read.value], dtype=np.uint8)
                        win = np.lib.stride_tricks.sliding_window_view(data, 16)
                        mask = np.isin(win, allowed).all(axis=1)
                        idx = np.flatnonzero(mask)
                        for p in idx:
                            key = win[p].tobytes()
                            try:
                                if AES.new(key, AES.MODE_ECB).decrypt(block)[:3] == b"\xff\xd8\xff":
                                    hits.append((addr + off + int(p), key))
                                    print("  命中 @0x%x" % (addr + off + int(p)))
                                    if not want_all:
                                        return key
                            except Exception:
                                pass
                        scanned += len(idx)
                    off += chunk
            addr += size
            if time.time() - t0 > 600:
                print("  超时，已测候选", scanned)
                break
    finally:
        k32.CloseHandle(h)
    print("  候选", scanned, "用时 %.1fs" % (time.time() - t0))
    return hits[0][1] if hits else None


def main():
    dat = sys.argv[1] if len(sys.argv) > 1 else find_dat()
    block = cipher_block(dat)
    print("样本:", dat)
    print("校验块:", block.hex())
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "state", "wechat", "image_key.txt")
    out = os.path.abspath(out)
    pids = pids_of({"weixin.exe", "wechat.exe"})
    print("微信进程:", pids)
    if not pids:
        sys.exit("微信没在运行")
    for pid in pids:
        print("扫 pid", pid)
        key = scan(pid, block)
        if key:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(key.decode("ascii", "replace"))
            print("KEY =", key.decode("ascii", "replace"))
            print("已写入", out)
            return 0
    print("没扫到：先在微信里打开看几张图片，再重跑")
    return 1


if __name__ == "__main__":
    sys.exit(main())

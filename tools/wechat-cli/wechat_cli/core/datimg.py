# -*- coding: utf-8 -*-
"""微信 4.x 图片 .dat 解密（V2 格式）

文件结构（均为小端）：
    [6B 签名 070856320807] [4B aes_size] [4B xor_size] [1B 填充]
    [aes_size 字节 AES-128-ECB 密文] [中间明文] [xor_size 字节单字节 XOR]

- AES 密钥：账户级 16 字节 ASCII，只在微信里打开过图片时驻留进程内存
- XOR 密钥：单字节，可由同一张图缩略图结尾的 JPEG 结束符 FF D9 反推

算法参考 ZedeX/weixin-decrypte-script（MIT），本文件是给 wechat-cli 用的精简实现。
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import struct
import subprocess
import sys

V2_MAGIC = b"\x07\x08V2\x08\x07"
V2_MAGIC_FULL = b"\x07\x08\x56\x32\x08\x07"
V1_MAGIC = b"\x07\x08\x56\x31\x08\x07"
HEADER_SIZE = 15          # 6 + 4 + 4 + 1
DEFAULT_AES_SIZE = 1024

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
READABLE = (0x02, 0x04, 0x20, 0x40, 0x80)
MAX_REGION = 64 * 1024 * 1024


def is_dat(path):
    try:
        with open(path, "rb") as f:
            return f.read(6) in (V2_MAGIC, V1_MAGIC)
    except OSError:
        return False


def read_header(path):
    """返回 (aes_size, xor_size)，不是 V2 返回 None。"""
    with open(path, "rb") as f:
        head = f.read(HEADER_SIZE)
    if head[:6] != V2_MAGIC or len(head) < HEADER_SIZE:
        return None
    aes_size, xor_size = struct.unpack("<II", head[6:14])
    return aes_size, xor_size


def xor_key_from_thumb(thumb_path):
    """从缩略图末尾两字节反推 XOR 密钥：应当解出 JPEG 的 FF D9。"""
    with open(thumb_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size < 2:
            return None
        f.seek(size - 2)
        x, y = f.read(2)
    key = x ^ 0xFF
    return key if (y ^ 0xD9) == key else key


def decrypt_v2(path, aes_key, xor_key, out_path):
    """解密一个 V2 .dat，写出并返回输出路径；失败抛 ValueError。"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:6] != V2_MAGIC:
        raise ValueError("不是 V2 格式：%s" % path)
    aes_size, xor_size = struct.unpack("<II", data[6:14])
    aes_size = aes_size or DEFAULT_AES_SIZE
    body = data[HEADER_SIZE:]
    aes_part = body[:aes_size]
    rest = body[aes_size:]
    xor_part = rest[len(rest) - xor_size:] if xor_size else b""
    middle = rest[:len(rest) - len(xor_part)]

    from Crypto.Cipher import AES
    plain_aes = AES.new(aes_key.encode("ascii"), AES.MODE_ECB).decrypt(
        aes_part[: len(aes_part) // 16 * 16]
    )
    if xor_key is None:
        xor_key = 0x00
    plain_xor = bytes(b ^ xor_key for b in xor_part)
    out = plain_aes + middle + plain_xor

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(out)
    return out_path


def guess_ext(blob):
    if blob[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if blob[:4] == b"\x89PNG":
        return ".png"
    if blob[:4] == b"GIF8":
        return ".gif"
    if blob[:4] == b"RIFF":
        return ".webp"
    if blob[:4] == b"wxgf":
        return ".wxgf"
    return ".dat"


# ---------------- 进程内存里找 AES 密钥 ----------------

class _MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


def _pids(names=("weixin.exe", "wechat.exe")):
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, errors="replace", timeout=20,
        ).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() in names:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def cipher_block(sample_dat):
    with open(sample_dat, "rb") as f:
        head = f.read(HEADER_SIZE + 16)
    return head[HEADER_SIZE:HEADER_SIZE + 16]


def scan_memory_for_aes_key(block, max_seconds=120):
    """在微信进程内存里找能把这个密文块解成 JPEG 的 16 字节 ASCII 密钥。"""
    import time
    try:
        from Crypto.Cipher import AES
    except ImportError:
        raise RuntimeError("需要 pycryptodome：pip install pycryptodome")

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    mbi = _MBI()
    t0 = time.time()
    for pid in _pids():
        h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            continue
        buf = ctypes.create_string_buffer(1 << 16)
        read = ctypes.c_size_t(0)
        addr = 0
        try:
            while addr < 0x7FFFFFFF0000:
                if time.time() - t0 > max_seconds:
                    return None
                if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi),
                                          ctypes.sizeof(mbi)):
                    addr += 0x1000
                    continue
                size = int(mbi.RegionSize)
                if (mbi.State == MEM_COMMIT and int(mbi.Protect) in READABLE
                        and 0 < size <= MAX_REGION):
                    off = 0
                    while off < size:
                        chunk = min(len(buf), size - off)
                        if k32.ReadProcessMemory(h, ctypes.c_void_p(addr + off), buf,
                                                 chunk, ctypes.byref(read)) and read.value >= 16:
                            data = buf.raw[:read.value]
                            i = 0
                            while True:
                                i = data.find(b"\x07\x08V2", i)
                                if i < 0:
                                    break
                                i += 1
                            for p in range(0, len(data) - 16):
                                w = data[p:p + 16]
                                if any(b < 0x21 or b > 0x7E for b in w):
                                    continue
                                try:
                                    if AES.new(w, AES.MODE_ECB).decrypt(block)[:3] == b"\xff\xd8\xff":
                                        return w.decode("ascii")
                                except Exception:
                                    pass
                        off += chunk
                addr += size
        finally:
            k32.CloseHandle(h)
    return None


# ---------------- 会话附件目录 ----------------

def attach_dir_for(wechat_base, username, month=None):
    """msg/attach/<md5(username)>[/YYYY-MM]/Img"""
    root = os.path.join(wechat_base, "msg", "attach", hashlib.md5(username.encode()).hexdigest())
    if month:
        return os.path.join(root, month, "Img")
    return root


def list_dat(attach_root, month=None, thumbs=True):
    """列出某会话的 .dat（可限定月份）。返回 [(path, size, mtime)]"""
    base = os.path.join(attach_root, month, "Img") if month else None
    dirs = [base] if base and os.path.isdir(base) else []
    if not dirs:
        for cur, _, files in os.walk(attach_root):
            if os.path.basename(cur) == "Img" and any(f.endswith(".dat") for f in files):
                dirs.append(cur)
    out = []
    for d in dirs:
        for name in os.listdir(d):
            if not name.endswith(".dat"):
                continue
            is_thumb = name.endswith("_t.dat") or name.endswith("_h.dat")
            if is_thumb and not thumbs:
                continue
            p = os.path.join(d, name)
            st = os.stat(p)
            out.append((p, st.st_size, st.st_mtime))
    out.sort(key=lambda x: x[2])
    return out


def key_file_pick(cfg):
    return os.path.join(os.path.dirname(os.path.abspath(cfg.get("keys_file", "keys.json"))), "image_key.txt")


def load_image_key(cfg):
    p = key_file_pick(cfg)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        v = f.read().strip()
    return v or None


def save_image_key(cfg, key):
    p = key_file_pick(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(key.strip())
    return p

#!/usr/bin/env python3
"""从 Edge/Chrome 的 Cookies 库里把 cookie 读出来（含解密），用于灌进 Playwright。

为什么需要：门户（my.muc.edu.cn）的 JSESSIONID 是**会话 cookie**（expires=0），
浏览器一关就没了。但 Chromium 会把它写进 Cookies 库，值用 DPAPI+AES-GCM 加密；
这里解开就能复用，不用每次重新登录。

只用本机 DPAPI（同一 Windows 用户下），不联网、不落明文。
"""
import binascii
import ctypes
import json
import sqlite3
import sys
from ctypes import wintypes
from pathlib import Path

CHROME_EPOCH = 11644473600  # 1601-01-01 → 1970-01-01 的秒数


def _dpapi_unwrap(blob: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(blob, len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _master_key(profile_dir: Path) -> bytes:
    state = json.loads((profile_dir / "Local State").read_text(encoding="utf-8"))
    enc = binascii.a2b_base64(state["os_crypt"]["encrypted_key"])
    if enc[:5] != b"DPAPI":
        raise OSError("不是 DPAPI 保护的 key")
    return _dpapi_unwrap(enc[5:])


def _decrypt(value: bytes, key: bytes) -> str:
    if value[:3] in (b"v10", b"v11"):
        nonce, ct = value[3:15], value[15:]
        try:
            from Crypto.Cipher import AES
            pt = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct[:-16], ct[-16:])
        except Exception:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            pt = AESGCM(key).decrypt(nonce, ct, None)
        # 新版 Edge 解出来的明文尾部才是 cookie 值，前面带一段非 ASCII 头部（app-bound 元数据），
        # 取末尾这段可打印 ASCII 作为真值。
        end = len(pt)
        start = end
        while start > 0 and 0x20 <= pt[start - 1] <= 0x7E:
            start -= 1
        return pt[start:end].decode("ascii", "ignore")
    return value.decode("utf-8", "ignore")  # 老版本明文


def read_cookies(profile_dir: str | Path, hosts=None):
    """返回 playwright 可直接 add_cookies 的列表。hosts 为域名后缀列表。"""
    profile_dir = Path(profile_dir)
    db = profile_dir / "Default" / "Network" / "Cookies"
    if not db.exists():
        db = profile_dir / "Default" / "Cookies"
    key = _master_key(profile_dir)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = "select host_key,name,encrypted_value,path,expires_utc,is_secure,is_httponly,samesite from cookies"
    out = []
    for host, name, enc, path, exp, sec, http_only, samesite in con.execute(q):
        if hosts and not any(host.endswith(h) for h in hosts):
            continue
        try:
            val = _decrypt(enc, key) if enc else ""
        except Exception:
            continue
        if not val:
            continue
        ss = {0: "None", 1: "Lax", 2: "Strict"}.get(samesite, "Lax")
        if ss == "None" and not sec:
            ss = "Lax"  # SameSite=None 必须配 Secure，否则 Chromium 直接拒
        # 统一用 domain 形式：门户走 http，若用 url 形式带 secure 会被 Chromium 拒
        item = {"domain": host, "path": path or "/"}
        item.update({"name": name, "value": val, "httpOnly": bool(http_only), "secure": bool(sec), "sameSite": ss})
        if exp:  # 会话 cookie 给个远期时间，免得 Playwright 丢掉
            item["expires"] = int(exp / 1e6 - CHROME_EPOCH)
        else:
            item["expires"] = 4102444800  # 2100-01-01
        out.append(item)
    con.close()
    return out


if __name__ == "__main__":
    prof = sys.argv[1] if len(sys.argv) > 1 else None
    if not prof:
        raise SystemExit("用法: edge_cookies.py <profile 目录> [域名后缀...]")
    hosts = sys.argv[2:] or None
    got = read_cookies(prof, hosts)
    print(json.dumps([{k: v for k, v in c.items() if k != "value"} | {"value_len": len(c["value"])} for c in got],
                     ensure_ascii=False, indent=1))
    print(f"共 {len(got)} 条")

"""扫 WXWork.exe 内存找 16 字节 wxSQLite3 key（需管理员）。numpy 预筛 + quick_verify。"""
import argparse, ctypes, os, sys, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import wxwork_crypto as wc

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
PROCESS_VM_READ, PROCESS_QUERY_INFORMATION = 0x0010, 0x0400
MEM_COMMIT, MEM_PRIVATE, PAGE_GUARD, PAGE_NOACCESS = 0x1000, 0x20000, 0x100, 0x01


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.c_uint32), ("__a1", ctypes.c_uint32),
                ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("__a2", ctypes.c_uint32)]


class TP(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_uint32), ("Luid", ctypes.c_int64), ("Attr", ctypes.c_uint32)]


def enable_debug():
    tok = ctypes.c_void_p()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0028, ctypes.byref(tok)):
        return False
    luid = ctypes.c_int64()
    if not adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
        return False
    tp = TP(1, luid.value, 0x2)
    return bool(adv.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None))


def find_pid(name="WXWork.exe"):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + name, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="gbk", errors="ignore").stdout
    res = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == name.lower():
            try:
                res.append(int(parts[1]))
            except ValueError:
                pass
    return res


def scan(h, page1, base, size, hits):
    buf = ctypes.create_string_buffer(size)
    rd = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, ctypes.c_size_t(size), ctypes.byref(rd)):
        return 0, 0
    data = buf.raw[: rd.value]
    if len(data) < 4096:
        return 0, 0
    arr = np.frombuffer(data, dtype=np.uint8)
    win = np.lib.stride_tricks.sliding_window_view(arr, 16)[::8]
    bad = ((win < 0x20) | (win > 0x7e)).sum(axis=1)
    has_zero = (win == 0).any(axis=1)
    idx = np.flatnonzero((bad >= 6) & (~has_zero))
    tested = 0
    qv = wc.quick_verify
    for i in idx:
        o = int(i) * 8
        cand = data[o:o + 16]
        tested += 1
        if qv(cand, page1):
            if wc.verify_key(cand, page1):
                hits.append(cand.hex())
                print(f"HIT {cand.hex()} @0x{base + o:x}", flush=True)
                if len(hits) >= 8:
                    return tested, len(data)
    return tested, len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--db", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not args.db:
        root = os.path.join(os.path.expanduser("~"), "Documents", "WXWork")
        cands = []
        if os.path.isdir(root):
            for acct in sorted(os.listdir(root)):
                q = os.path.join(root, acct, "Data", "message.db")
                if os.path.isfile(q):
                    cands.append(q)
        if not cands:
            print("!! find no message.db")
            return 2
        args.db = max(cands, key=os.path.getsize)

    page1 = open(args.db, "rb").read(4096)
    if not wc.has_plain_header_fragment(page1):
        print("!! page1 无明文头片段，中止")
        return 2
    pids = [args.pid] if args.pid else find_pid()
    if not pids:
        print("!! 找不到 WXWork.exe")
        return 2
    print(f"pids={pids} debug={enable_debug()}", flush=True)

    hits, t0 = [], time.time()
    for pid in pids:
        h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            print(f"!! OpenProcess({pid}) 失败 err={ctypes.get_last_error()}", flush=True)
            continue
        mbi, addr, tested_all, mb = MBI(), 0, 0, 0.0
        regions = 0
        while addr < 4 * 1024 ** 3:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base, size = mbi.BaseAddress or 0, mbi.RegionSize or 0
            if size == 0:
                break
            prot = mbi.Protect & 0xFF
            if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE and not (mbi.Protect & PAGE_GUARD)
                    and prot != PAGE_NOACCESS and size <= 256 * 1024 * 1024):
                t, n = scan(h, page1, base, size, hits)
                tested_all += t
                mb += n / 1048576
                regions += 1
                if regions % 40 == 0:
                    print(f".. pid={pid} {mb:.0f}MB tested={tested_all} {time.time()-t0:.0f}s", flush=True)
            addr = base + size
            if len(hits) >= 8:
                break
        k32.CloseHandle(h)
        print(f"pid={pid} 扫完 {mb:.0f}MB tested={tested_all} hits={len(hits)}", flush=True)
        if hits:
            break

    print(f"完成 hits={len(hits)} {time.time()-t0:.0f}s", flush=True)
    if hits:
        target = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys_found.txt")
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("\n".join(hits) + "\n")
        print("写入 " + target, flush=True)
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())

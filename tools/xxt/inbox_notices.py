import sys, json, argparse, os, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
STATE = HERE.parents[1] / "state" / "xxt"
_tmp = STATE / "tmp"; _tmp.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(_tmp); os.environ["TMP"] = str(_tmp)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(HERE / "browsers"))
sys.path.insert(0, str(HERE / "chaoxing-agent-cli-main" / "src"))
from xxt_cli.session import Session
from playwright.sync_api import sync_playwright

BASE = "https://i.chaoxing.com/base"
SCHOOL_FID = 383
SCHOOL_NAME = "中央民族大学"


def switch_to_school(page):
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    info = page.evaluate("""async (args) => {
        const r = await fetch('/base/cacheUserOrg', {method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded'},
            body:'searchName=&_t=' + Date.now()});
        const j = await r.json();
        const cur = (j.site || []).find(s => String(s.schoolname).includes('图书馆')) || (j.site || [])[0];
        const tgt = (j.site || []).find(s => String(s.schoolname) === args.name) || (j.site || []).find(s => !String(s.schoolname).includes('图书馆'));
        if (!tgt) return {ok:false, sites:(j.site||[]).map(s=>s.schoolname)};
        const body = 'spaceFidBefore=' + (cur ? cur.fid : '') +
                     '&siteFid=' + tgt.fid + '&siteName=' + encodeURIComponent(tgt.schoolname) +
                     '&siteTid=' + (tgt.tid || 0) + '&siteRoleId=' + (tgt.roleId || '');
        const r2 = await fetch('/base/switchSite', {method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        return {ok:true, switched:tgt.schoolname, resp: await r2.text()};
    }""", {"name": SCHOOL_NAME})
    page.goto("%s?fid=%d&wfworg=true&tid=0" % (BASE, SCHOOL_FID), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    return info


def parse_rows(text):
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    rows, cur = [], None
    for ln in lines:
        m = re.match(r"^(\d{1,2}-\d{1,2})\((?:星期|周)([一二三四五六日])\)\s*(\d{2}:\d{2})", ln)
        if m:
            if cur: rows.append(cur)
            cur = {"date": m.group(1), "time": m.group(3), "text": []}
        elif cur is not None:
            if ln in ("全部", "清除红点", "设置", "写站内信函", "新建文件夹"):
                continue
            cur["text"].append(ln)
    if cur: rows.append(cur)
    for r in rows:
        r["text"] = " ".join(r["text"])[:220]
    return rows


def main():
    ap = argparse.ArgumentParser(description="读学习通站内信 Inbox")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    st = Session(STATE).load()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=st, viewport={"width": 1500, "height": 1100})
        page = ctx.new_page()
        try:
            info = switch_to_school(page)
            page.get_by_text("Inbox", exact=True).first.click(timeout=10000)
            page.wait_for_timeout(4000)
            fr = [f for f in page.frames if "notice.chaoxing.com" in f.url]
            if not fr:
                raise SystemExit("切到「中央民族大学」门户后没找到 Inbox 列表（%s）" % json.dumps(info, ensure_ascii=False))
            txt = fr[0].inner_text("body")
            rows = parse_rows(txt)[: a.limit]
        finally:
            b.close()
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            print("%s %s | %s" % (r["date"], r["time"], r["text"]))
        print("[inbox] 共 %d 条" % len(rows), file=sys.stderr)


if __name__ == "__main__":
    main()

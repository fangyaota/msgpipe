import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "chaoxing-agent-cli-main" / "src"))
from xxt_cli.session import Session
from playwright.sync_api import sync_playwright

COURSE = "https://mooc1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=266570726&clazzid=153294202&vc=1&cpi=566848015&ismooc2=1&v=2"
TARGETS = ["2.5 作业", "3.7 作业", "4.5 作业", "5.7 作业", "6.6 作业", "8.7 作业", "9.6 作业-扳手的图形绘制"]
st = Session(Path(r"D:\Workspace\msgpipe\state\xxt")).load()
out = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(storage_state=st, viewport={"width":1500,"height":1200})
    for t in TARGETS:
        pg = ctx.new_page()
        try:
            pg.goto(COURSE, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(2500)
            pg.get_by_text("章节", exact=True).first.click(timeout=8000)
            pg.wait_for_timeout(3500)
            f = [x for x in pg.frames if "mycourse/studentcourse" in x.url][0]
            f.get_by_text(t, exact=True).first.click(timeout=8000)
            pg.wait_for_timeout(5000)
            txt = ""
            for fr in pg.frames:
                if "knowledge/cards" in fr.url:
                    try: txt = fr.inner_text("body")
                    except Exception: pass
            lines = [x.strip() for x in txt.split("\n") if x.strip()]
            out.append({"chapter": t, "lines": lines[:18]})
            print("=" * 55); print(t)
            for ln in lines[:12]: print("   ", ln[:110])
        except Exception as e:
            out.append({"chapter": t, "error": str(e)[:100]}); print("!!", t, str(e)[:80])
        finally:
            pg.close()
    b.close()
Path(r"D:\Workspace\msgpipe\tools\xxt\gongtu_hw.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

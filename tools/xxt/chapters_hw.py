import sys, json, argparse, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "chaoxing-agent-cli-main" / "src"))
from xxt_cli.session import Session
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
STATE = HERE.parents[1] / "state" / "xxt"
_state_tmp = STATE / "tmp"
_state_tmp.mkdir(parents=True, exist_ok=True)
import os
os.environ["TEMP"] = str(_state_tmp)
os.environ["TMP"] = str(_state_tmp)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(HERE / "browsers"))


def find_course(keyword):
    import os
    exe = Path(sys.executable).parent / "xxt.exe"
    env = {**os.environ,
           "XXT_STATE_DIR": str(STATE),
           "TEMP": str(STATE / "tmp"), "TMP": str(STATE / "tmp"),
           "PLAYWRIGHT_BROWSERS_PATH": str(HERE / "browsers"),
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([str(exe), "courses"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    items = (json.loads(r.stdout).get("data") or {}).get("items") or []
    hits = [c for c in items if keyword in (c.get("title") or "")]
    if not hits:
        raise SystemExit("没找到课程：%s；可选：%s" % (keyword, "、".join(c.get("title", "") for c in items)))
    return hits[0]["title"], hits[0]["url"]


def open_chapters(ctx, course):
    pg = ctx.new_page()
    pg.goto(course, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2500)
    pg.get_by_text("章节", exact=True).first.click(timeout=8000)
    pg.wait_for_timeout(3500)
    return pg, [f for f in pg.frames if "mycourse/studentcourse" in f.url][0]


def main():
    ap = argparse.ArgumentParser(description="读学习通某门课「章节」里的作业任务点")
    ap.add_argument("--course", default="工程图学", help="课程名关键词")
    ap.add_argument("--all", action="store_true", help="读全部章节（默认只读标题含「作业」的）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    name, course = find_course(a.course)
    print("[章节] 课程：%s" % name, file=sys.stderr)
    st = Session(STATE).load()
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=st, viewport={"width": 1500, "height": 1200})
        pg, fr = open_chapters(ctx, course)
        names = fr.eval_on_selector_all(".catalog_name", "els => els.map(e => (e.innerText||'').trim())")
        targets = names if a.all else [n for n in names if n.endswith("作业") or "作业-" in n]
        pg.close()
        for t in targets:
            page = ctx.new_page()
            try:
                page.goto(course, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2200)
                page.get_by_text("章节", exact=True).first.click(timeout=8000)
                page.wait_for_timeout(3200)
                f = [x for x in page.frames if "mycourse/studentcourse" in x.url][0]
                f.get_by_text(t, exact=True).first.click(timeout=8000)
                page.wait_for_timeout(4500)
                txt = ""
                for fr2 in page.frames:
                    if "knowledge/cards" in fr2.url:
                        try:
                            txt = fr2.inner_text("body")
                        except Exception:
                            pass
                lines = [x.strip() for x in txt.split("\n") if x.strip()]
                out.append({"chapter": t, "lines": lines[:18]})
                if not a.json:
                    print("=" * 55)
                    print(t)
                    for ln in lines[:12]:
                        print("   ", ln[:110])
            except Exception as e:
                out.append({"chapter": t, "error": str(e)[:100]})
                if not a.json:
                    print("!!", t, str(e)[:80])
            finally:
                page.close()
        b.close()
    if a.json:
        print(json.dumps({"course": name, "chapters": out}, ensure_ascii=False))
    else:
        print("\n共 %d 个作业章节；-json 可输出结构化结果" % len(out), file=sys.stderr)


if __name__ == "__main__":
    main()

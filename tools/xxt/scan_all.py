"""遍历所有课程，统计每门课有多少作业与状态。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
sys.path.insert(0, str(HERE / "chaoxing-agent-cli-main" / "src"))

from xxt_cli.session import Session
from xxt_cli.browser import Browser
from xxt_cli import parsers

OUT = HERE
s = Session(PROJ / "state" / "xxt")
report = []
with Browser(s, headed=False, timeout=30000) as b:
    b.goto("https://mooc1.chaoxing.com/visit/interaction")
    b.page.wait_for_timeout(1500)
    courses = parsers.courses(b.page.content(), b.page.url)
for c in courses:
    row = {"title": c["title"], "id": c["id"], "count": None, "status": {}, "error": None}
    try:
        s2 = Session(OUT / "state")
        with Browser(s2, headed=False, timeout=25000) as b2:
            data = b2.homework_list(c["url"], 5)
        items = data["items"]
        row["count"] = len(items)
        st = {}
        for it in items:
            st[it.get("status", "?")] = st.get(it.get("status", "?"), 0) + 1
        row["status"] = st
        row["detail"] = [
            {"name": it.get("title"), "status": it.get("status"), "time": it.get("time_text")}
            for it in items
        ]
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    report.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

(OUT / "courses_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("done ->", OUT / "courses_report.json")

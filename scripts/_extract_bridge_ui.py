import subprocess
from pathlib import Path

html = subprocess.check_output(["git", "show", "e330800:index.html"], text=True, encoding="utf-8", errors="replace")
start_token = '<div class="mt-4 p-4 rounded-xl border border-sky-200 bg-sky-50/70 space-y-3">'
start = html.find(start_token)
box_end = html.find('<div class="mt-6 pt-5 border-t border-indigo-200/50">', start)
if start < 0 or box_end < 0:
    raise SystemExit(f"ui block markers missing start={start} end={box_end}")
block = html[start:box_end]
Path(r"C:\Users\yu\Desktop\opaiRe\scripts\_bridge_ui_block.html").write_text(block, encoding="utf-8")
print("ui block", len(block))

js = subprocess.check_output(["git", "show", "e330800:static/js/app.js"], text=True, encoding="utf-8", errors="replace")
# extract defaulting snippet around openai_cpa
i = js.find("if (this.config.openai_cpa")
# find a broader region
i2 = js.find("openai_cpa.bridge_base_url")
print("bridge_base idx", i2)
print(js[i2-300:i2+900])
Path(r"C:\Users\yu\Desktop\opaiRe\scripts\_bridge_js_snippet.txt").write_text(js[i2-400:i2+1200], encoding="utf-8")

i3 = js.find("syncOpenaiCpaReceiveMode()")
# find full method
# search "syncOpenaiCpaReceiveMode() {" 
i3 = js.find("syncOpenaiCpaReceiveMode() {")
i4 = js.find("\n        },", i3)
snippet = js[i3:i4+10]
Path(r"C:\Users\yu\Desktop\opaiRe\scripts\_bridge_js_method.txt").write_text(snippet, encoding="utf-8")
print("method:\n", snippet)

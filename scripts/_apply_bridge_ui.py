from pathlib import Path

# index.html: insert bridge UI before 内存池专属流水线 section inside openai_cpa tip box
html_path = Path(r"C:\Users\yu\Desktop\opaiRe\index.html")
html = html_path.read_text(encoding="utf-8")
block = Path(r"C:\Users\yu\Desktop\opaiRe\scripts\_bridge_ui_block.html").read_text(encoding="utf-8")
if "收码路径 receive_mode" not in html:
    marker = '<div class="mt-6 pt-5 border-t border-indigo-200/50">'
    # only the one inside openai_cpa tip - find near webhook secret tip
    # search after openai_cpa.use_original_password_flow block
    anchor_region = html.find("config.openai_cpa.use_original_password_flow")
    if anchor_region < 0:
        raise SystemExit("openai_cpa password flow missing")
    pos = html.find(marker, anchor_region)
    if pos < 0:
        raise SystemExit("mt-6 marker missing after openai_cpa")
    html = html[:pos] + block + "\n                                        " + html[pos:]
    html_path.write_text(html, encoding="utf-8")
    print("index.html UI inserted")
else:
    print("index.html UI already present")

# app.js defaults
js_path = Path(r"C:\Users\yu\Desktop\opaiRe\static\js\app.js")
js = js_path.read_text(encoding="utf-8")

defaults = '''
                if (!this.config.openai_cpa || typeof this.config.openai_cpa !== 'object') this.config.openai_cpa = {};
                if (this.config.openai_cpa.bridge_enabled === undefined) this.config.openai_cpa.bridge_enabled = false;
                if (this.config.openai_cpa.bridge_base_url === undefined) this.config.openai_cpa.bridge_base_url = '';
                if (this.config.openai_cpa.bridge_token === undefined) this.config.openai_cpa.bridge_token = '';
                if (this.config.openai_cpa.receive_mode === undefined || this.config.openai_cpa.receive_mode === '') {
                    this.config.openai_cpa.receive_mode = this.config.openai_cpa.bridge_enabled ? 'remote_bridge' : 'local_webhook';
                }
                const cpaModeMap = {
                    remote: 'remote_bridge',
                    remote_bridge: 'remote_bridge',
                    bridge: 'remote_bridge',
                    server: 'remote_bridge',
                    local: 'local_webhook',
                    local_webhook: 'local_webhook',
                    tunnel: 'local_webhook',
                    dual: 'dual',
                    both: 'dual',
                    all: 'dual'
                };
                const rawCpaMode = String(this.config.openai_cpa.receive_mode || '').trim().toLowerCase().replace(/-/g, '_');
                this.config.openai_cpa.receive_mode = cpaModeMap[rawCpaMode]
                    || (this.config.openai_cpa.bridge_enabled ? 'remote_bridge' : 'local_webhook');
                this.config.openai_cpa.bridge_enabled = ['remote_bridge', 'dual'].includes(this.config.openai_cpa.receive_mode);
'''

if "bridge_base_url === undefined" not in js:
    # insert near other openai_cpa / enable_codex defaults if any, or after config load blacklist handling
    # Look for use_original_password_flow defaulting or openai_cpa object init
    needles = [
        "if (!this.config.openai_cpa",
        "this.config.openai_cpa",
        "use_original_password_flow",
    ]
    inserted = False
    # Prefer after clash_proxy_pool cluster_count load block ends - actually after config fetched
    marker = "if (this.config.clash_proxy_pool.sub_url !== undefined) {"
    m = js.find(marker)
    if m >= 0:
        # find end of that if block
        end = js.find("\n                }", m)
        end = js.find("\n", end + 1)
        js = js[:end+1] + defaults + js[end+1:]
        inserted = True
        print("defaults inserted after clash sub_url")
    if not inserted:
        raise SystemExit("could not insert js defaults")
else:
    print("js defaults already present")

method = '''
        syncOpenaiCpaReceiveMode() {
            if (!this.config.openai_cpa || typeof this.config.openai_cpa !== 'object') {
                this.config.openai_cpa = {};
            }
            const modeMap = {
                remote: 'remote_bridge',
                remote_bridge: 'remote_bridge',
                bridge: 'remote_bridge',
                server: 'remote_bridge',
                local: 'local_webhook',
                local_webhook: 'local_webhook',
                tunnel: 'local_webhook',
                dual: 'dual',
                both: 'dual',
                all: 'dual'
            };
            const raw = String(this.config.openai_cpa.receive_mode || '').trim().toLowerCase().replace(/-/g, '_');
            const mode = modeMap[raw] || (this.config.openai_cpa.bridge_enabled ? 'remote_bridge' : 'local_webhook');
            this.config.openai_cpa.receive_mode = mode;
            // Keep legacy bridge_enabled in sync for older readers / backend fallback.
            this.config.openai_cpa.bridge_enabled = ['remote_bridge', 'dual'].includes(mode);
        },
'''
if "syncOpenaiCpaReceiveMode()" not in js:
    # insert before fetchClashPool or another method
    anchor = "        async fetchClashPool() {"
    if anchor not in js:
        anchor = "        async testClashGroup(groupName) {"
    if anchor not in js:
        raise SystemExit("method anchor missing")
    js = js.replace(anchor, method + "\n" + anchor, 1)
    print("method inserted")
else:
    print("method already present")

js_path.write_text(js, encoding="utf-8")
print("app.js ok")

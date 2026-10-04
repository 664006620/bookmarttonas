#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保存网址到 NAS —— 零依赖服务端 (纯 Python 标准库)
==================================================
功能:
  - POST /api/save    保存一条网址 (需要 TOKEN)            body: {url,title,group}
  - POST /api/delete  删除一条 (需要 TOKEN)                body: {id}
  - POST /api/update  修改一条 (需要 TOKEN)                body: {id,title,url,group}
  - POST /api/group   分组管理 (需要 TOKEN)                body: {action:'rename'|'delete',name,newName}
  - POST /api/reorder 保存排序 (需要 TOKEN)                body: {groups:[组顺序],items:{组:[id顺序]}}
  - GET  /api/list    返回已保存列表 JSON (需要 TOKEN)     含 id / group, 按 order.json 排序
  - POST /api/upload  上传文件 (需要 TOKEN)                 multipart, 存到 UPLOAD_DIR
  - GET  /api/files   返回已上传文件列表 (需要 VIEW_TOKEN)   name/size/mtime
  - GET  /files/<name> 下载文件 (需要 VIEW_TOKEN)           防目录穿越
  - POST /api/file-del 删除文件 (需要 TOKEN)                body:{name}
  - GET  /            导航页(搜索引擎居中 / 分组折叠 / 增删改 / 上传文件)
  - GET  /export      导出 links.jsonl
  - OPTIONS *         CORS 预检

运行:
  TOKEN=你的密钥 PORT=8000 python3 server.py
"""
import hashlib
import json
import mimetypes
import os
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CONFIG = {
    "HOST": os.environ.get("HOST", "0.0.0.0"),
    "PORT": int(os.environ.get("PORT", "8000")),
    "TOKEN": os.environ.get("TOKEN", "CHANGE_ME"),
    "VIEW_TOKEN": os.environ.get("VIEW_TOKEN", ""),
    "DATA_DIR": os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
    "DATA_FILE": os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "links.jsonl"),
    "ORDER_FILE": os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "order.json"),
    "UPLOAD_DIR": os.environ.get("UPLOAD_DIR", "/mnt/sata6-2/download/"),
    "CORS_ORIGIN": os.environ.get("CORS_ORIGIN", "*"),
}

_lock = threading.Lock()
DEFAULT_GROUP = "默认"


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _ensure_store():
    os.makedirs(CONFIG["DATA_DIR"], exist_ok=True)
    if not os.path.exists(CONFIG["DATA_FILE"]):
        open(CONFIG["DATA_FILE"], "a", encoding="utf-8").close()


def _rec_id(rec):
    """返回记录的稳定 id；旧数据(无 id)按 ts+url 计算, 保证可定位"""
    if rec.get("id"):
        return rec["id"]
    return hashlib.sha1((rec.get("ts", "") + rec.get("url", "")).encode("utf-8")).hexdigest()[:12]


def _load_all():
    _ensure_store()
    out = []
    with _lock:
        with open(CONFIG["DATA_FILE"], "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                r["id"] = _rec_id(r)
                r.setdefault("group", DEFAULT_GROUP)
                out.append(r)
    out.reverse()  # 最新在前
    return out


def _save_all(recs):
    _ensure_store()
    with _lock:
        with open(CONFIG["DATA_FILE"], "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_link(url, title, group):
    _ensure_store()
    rec = {
        "id": uuid.uuid4().hex[:12],
        "ts": _now_iso(),
        "url": url,
        "title": (title or url or "").strip() or url,
        "group": (group or DEFAULT_GROUP).strip() or DEFAULT_GROUP,
    }
    with _lock:
        with open(CONFIG["DATA_FILE"], "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _load_order():
    p = CONFIG["ORDER_FILE"]
    if not os.path.exists(p):
        return {"groups": [], "items": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"groups": [], "items": {}}


def _save_order(order):
    _ensure_store()
    with _lock:
        with open(CONFIG["ORDER_FILE"], "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)


def sort_by_order(recs):
    """按 order.json 排序: 分组顺序 + 组内链接顺序; 未记录的排末尾(组内按时间)"""
    order = _load_order()
    gorder = {g: i for i, g in enumerate(order.get("groups", []))}
    groups = {}
    for r in recs:
        groups.setdefault(r.get("group", DEFAULT_GROUP), []).append(r)

    def gkey(g):
        return gorder.get(g, 1 << 30)

    names = sorted(groups.keys(), key=lambda g: (gkey(g), g))
    out = []
    items_order = order.get("items", {})
    for g in names:
        seq = items_order.get(g, [])
        iorder = {iid: idx for idx, iid in enumerate(seq)}
        lst = sorted(groups[g], key=lambda r: (iorder.get(r["id"], 1 << 30), r.get("ts", "")))
        out.extend(lst)
    return out


def delete_link(id_):
    recs = _load_all()
    before = len(recs)
    recs = [r for r in recs if r["id"] != id_]
    _save_all(recs)
    return before - len(recs)


def update_link(id_, title=None, url=None, group=None):
    recs = _load_all()
    for r in recs:
        if r["id"] == id_:
            if title is not None:
                r["title"] = title
            if url is not None:
                r["url"] = url
            if group is not None:
                r["group"] = (group or DEFAULT_GROUP).strip() or DEFAULT_GROUP
            _save_all(recs)
            return True
    return False


def group_action(action, name, new_name=None):
    recs = _load_all()
    if action == "rename":
        for r in recs:
            if r.get("group") == name:
                r["group"] = (new_name or DEFAULT_GROUP).strip() or DEFAULT_GROUP
        _save_all(recs)
        return True
    if action == "delete":
        recs = [r for r in recs if r.get("group") != name]
        _save_all(recs)
        return True
    return False


def check_auth(headers, qs):
    want = CONFIG["TOKEN"]
    if not want or want == "CHANGE_ME":
        return True
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() == want
    tok = qs.get("token", [None])[0]
    return tok == want


def check_view_auth(headers, qs):
    want = CONFIG["VIEW_TOKEN"] or CONFIG["TOKEN"]
    if not want or want == "CHANGE_ME":
        return True
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() == want
    tok = qs.get("token", [None])[0]
    return tok == want


# ===================== 文件上传 / 管理 =====================
def _safe_name(name):
    """只保留 字母数字 . _ - 及中文, 其余(含路径分隔符)替换为 _, 杜绝目录穿越"""
    name = (name or "file").strip()
    out = []
    for ch in name:
        if ch.isalnum() or ch in "._-" or "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip("._-")
    return name or "file"


def _unique_name(name):
    base, ext = os.path.splitext(name)
    path = os.path.join(CONFIG["UPLOAD_DIR"], name)
    i = 1
    while os.path.exists(path):
        name = f"{base}({i}){ext}"
        path = os.path.join(CONFIG["UPLOAD_DIR"], name)
        i += 1
    return name


def _parse_multipart(body, boundary):
    """极简 multipart 解析, 返回 [(headers_dict, content_bytes), ...]"""
    delim = b"--" + boundary.encode("utf-8")
    parts = []
    for seg in body.split(delim):
        if seg in (b"", b"--", b"\r\n"):
            continue
        if seg.startswith(b"\r\n"):
            seg = seg[2:]
        if seg.endswith(b"\r\n"):
            seg = seg[:-2]
        if not seg:
            continue
        idx = seg.find(b"\r\n\r\n")
        if idx == -1:
            continue
        headers = {}
        for line in seg[:idx].split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.decode().strip().lower()] = v.decode().strip()
        parts.append((headers, seg[idx + 4:]))
    return parts


def save_upload(body, content_type):
    ct = content_type or ""
    boundary = ""
    if "boundary=" in ct:
        boundary = ct.split("boundary=", 1)[1].strip().strip('"')
    if not boundary:
        return None, "missing boundary"
    parts = _parse_multipart(body, boundary)
    saved = []
    os.makedirs(CONFIG["UPLOAD_DIR"], exist_ok=True)
    for h, c in parts:
        cd = h.get("content-disposition", "")
        if 'name="file"' not in cd or "filename=" not in cd:
            continue
        fn = ""
        for piece in cd.split(";"):
            piece = piece.strip()
            if piece.startswith("filename="):
                fn = piece[len("filename="):].strip().strip('"')
        name = _unique_name(_safe_name(fn))
        path = os.path.join(CONFIG["UPLOAD_DIR"], name)
        with open(path, "wb") as f:
            f.write(c)
        saved.append({"name": name, "size": len(c)})
    return saved, None


def list_uploads():
    d = CONFIG["UPLOAD_DIR"]
    if not os.path.isdir(d):
        return []
    out = []
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append({"name": n, "size": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def delete_upload(name):
    safe = _safe_name(name)
    p = os.path.join(CONFIG["UPLOAD_DIR"], safe)
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


VIEW_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的导航 · 收藏</title>
<style>
:root{color-scheme:light dark;
--bg1:#eaf0ff;--bg2:#f7f9fc;--bg3:#ffeef7;
--panel:rgba(255,255,255,.66);--card:rgba(255,255,255,.82);--card-hov:rgba(255,255,255,.97);
--bd:rgba(23,40,80,.10);--tx:#20283a;--mut:#727b8c;--blue:#4f6ef7;--blue2:#7c9bff;--red:#ef4444;
--shadow:0 10px 34px rgba(31,45,80,.10);--radius:18px}
*{box-sizing:border-box}
html,body{min-height:100%}
body{margin:0;font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--tx);
background:linear-gradient(135deg,var(--bg1) 0%,var(--bg2) 46%,var(--bg3) 100%) fixed;
-webkit-font-smoothing:antialiased;transition:background .3s}
body.has-bg{background-image:var(--bgimg);background-size:cover;background-position:center;background-attachment:fixed}
body.has-bg::before{content:"";position:fixed;inset:0;z-index:-1;background:rgba(255,255,255,.34);backdrop-filter:blur(3px)}
body.dark{--bg1:#0e1322;--bg2:#141b2e;--bg3:#241a3a;--panel:rgba(26,32,48,.6);--card:rgba(34,40,58,.74);--card-hov:rgba(46,53,74,.94);--bd:rgba(255,255,255,.10);--tx:#e8ebf2;--mut:#98a1b3;--blue:#6f8bff;--blue2:#9bb0ff;--red:#ff6b6b;--shadow:0 10px 34px rgba(0,0,0,.4)}
body.dark.has-bg::before{background:rgba(10,12,20,.5)}

.topbar{position:sticky;top:0;z-index:30;background:var(--panel);backdrop-filter:blur(18px) saturate(150%);-webkit-backdrop-filter:blur(18px) saturate(150%);border-bottom:1px solid var(--bd);padding:18px 16px 15px}
.hero{display:flex;flex-direction:column;align-items:center;gap:15px;max-width:980px;margin:0 auto}
.brand{font-size:19px;font-weight:800;letter-spacing:.4px;display:flex;align-items:center;gap:9px}
.brand .dot{width:11px;height:11px;border-radius:50%;background:linear-gradient(135deg,var(--blue),var(--blue2));box-shadow:0 0 14px var(--blue)}
.search-wrap{position:relative;width:min(640px,94vw)}
.search{display:flex;align-items:center;gap:8px;width:100%;background:var(--card);border:1px solid var(--bd);border-radius:999px;padding:6px 6px 6px 8px;box-shadow:var(--shadow);transition:.22s}
.search:focus-within{border-color:var(--blue);box-shadow:0 0 0 4px rgba(79,110,247,.18),var(--shadow);transform:translateY(-1px)}
.eng-ico{display:flex;align-items:center;justify-content:center;min-width:42px;height:42px;border:0;border-radius:50%;background:linear-gradient(135deg,var(--blue),var(--blue2));color:#fff;font-size:15px;font-weight:800;cursor:pointer;flex:0 0 auto;padding:0 12px;transition:.15s}
.eng-ico:hover{filter:brightness(1.08)}
.search input{flex:1;border:0;outline:0;background:transparent;color:var(--tx);font-size:16px;padding:8px 6px}
.search input::placeholder{color:var(--mut)}
.go{margin-left:auto;border:0;border-radius:50%;width:42px;height:42px;background:var(--blue);color:#fff;font-size:18px;cursor:pointer;flex:0 0 auto;transition:.15s}
.go:hover{filter:brightness(1.08)}
.eng-menu{position:absolute;top:62px;left:8px;z-index:40;display:none;flex-direction:column;gap:2px;background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:6px;box-shadow:var(--shadow);min-width:150px;backdrop-filter:blur(14px)}
.eng-menu.show{display:flex}
.eng-menu div{padding:9px 13px;border-radius:9px;cursor:pointer;font-size:14px;transition:.12s}
.eng-menu div:hover{background:rgba(127,127,127,.14)}
.eng-menu div.on{color:var(--blue);font-weight:700}
.quick{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
.qbtn{display:inline-flex;align-items:center;gap:6px;padding:8px 15px;border:1px solid var(--bd);border-radius:999px;background:var(--card);color:var(--tx);cursor:pointer;font-size:13px;transition:.15s;backdrop-filter:blur(8px)}
.qbtn:hover{border-color:var(--blue);color:var(--blue);transform:translateY(-1px)}
.qbtn.p{background:linear-gradient(135deg,var(--blue),var(--blue2));color:#fff;border-color:transparent}
.qbtn.p:hover{color:#fff;filter:brightness(1.06)}

main{max-width:1200px;margin:24px auto;padding:0 18px}
.group{margin:22px 0;background:var(--panel);border:1px solid var(--bd);border-radius:var(--radius);padding:16px 18px 20px;backdrop-filter:blur(14px);box-shadow:var(--shadow)}
.group h2{display:flex;align-items:center;gap:8px;margin:0 0 14px;font-size:14px;color:var(--mut);cursor:pointer;user-select:none}
.group h2 .gname{color:var(--tx);font-weight:800;font-size:16px}
.group h2 .cnt{font-size:11px;background:rgba(127,127,127,.18);padding:2px 10px;border-radius:999px;color:var(--mut)}
.group h2 .chev{margin-left:auto;transition:transform .2s;color:var(--mut);font-size:12px}
.group.collapsed .chev{transform:rotate(-90deg)}
.group.collapsed .body{display:none}
.gmv{padding:2px 9px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--mut);cursor:pointer;font-size:12px;transition:.15s}
.gmv:hover{color:var(--tx);border-color:var(--blue)}
.mini{display:flex;gap:6px;margin-left:6px}

.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.tile{position:relative;display:flex;align-items:center;gap:13px;padding:13px 15px;border:1px solid var(--bd);border-radius:14px;background:var(--card);text-decoration:none;color:var(--tx);transition:.16s;min-height:66px;overflow:hidden}
.tile:hover{border-color:var(--blue);background:var(--card-hov);transform:translateY(-2px);box-shadow:0 12px 26px rgba(31,45,80,.14)}
.tile .ico{flex:0 0 auto;width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;color:#fff;box-shadow:0 4px 10px rgba(0,0,0,.14)}
.tile .meta{flex:1;min-width:0}
.tile .t{font-weight:700;word-break:break-word;line-height:1.35;padding-right:42px}
.tile .u{color:var(--mut);font-size:12px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .acts{position:absolute;top:9px;right:9px;display:flex;gap:2px;opacity:0;transition:.15s}
.tile:hover .acts{opacity:1}
.tile .acts span{cursor:pointer;opacity:.6;font-size:13px;padding:2px 6px;border-radius:7px;background:rgba(127,127,127,.12)}
.tile .acts span:hover{opacity:1;background:rgba(127,127,127,.26)}
.tile[draggable=true]{cursor:grab}
.dragging{opacity:.35}
.empty{text-align:center;color:var(--mut);padding:80px 0;font-size:15px}

.modal{position:fixed;inset:0;background:rgba(15,20,35,.45);backdrop-filter:blur(3px);display:none;align-items:center;justify-content:center;z-index:50;padding:16px}
.modal.show{display:flex}
.modal .box{background:var(--card);color:var(--tx);width:min(440px,94vw);border-radius:18px;padding:22px;border:1px solid var(--bd);box-shadow:0 24px 70px rgba(0,0,0,.32);backdrop-filter:blur(16px)}
.modal h3{margin:0 0 14px;font-size:17px}
.modal label{display:block;font-size:12px;color:var(--mut);margin:12px 0 5px}
.modal input{width:100%;padding:10px 13px;border:1px solid var(--bd);border-radius:11px;background:var(--panel);color:var(--tx);font-size:14px;outline:none;transition:.15s}
.modal input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(79,110,247,.16)}
.modal input[type=file]{padding:8px}
.modal .row{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}

.toast{position:fixed;left:50%;top:20px;transform:translateX(-50%);background:rgba(31,35,41,.92);color:#fff;padding:10px 18px;border-radius:12px;z-index:99;opacity:0;transition:.25s;pointer-events:none;font-size:14px;box-shadow:0 10px 30px rgba(0,0,0,.3)}

.file-row{display:flex;align-items:center;gap:12px;padding:11px 6px;border-bottom:1px solid var(--bd)}
.file-name{flex:1;color:var(--blue);text-decoration:none;word-break:break-all;font-size:14px}
.file-name:hover{text-decoration:underline}
.file-meta{flex:0 0 auto;font-size:12px;color:var(--mut);white-space:nowrap}
.file-del{flex:0 0 auto;cursor:pointer;color:var(--mut);padding:3px 8px;border-radius:8px;font-size:14px;transition:.15s}
.file-del:hover{color:var(--red);background:rgba(239,68,68,.12)}

.dropzone{position:fixed;inset:0;z-index:200;display:none;align-items:center;justify-content:center;background:rgba(79,110,247,.16);backdrop-filter:blur(3px);border:3px dashed var(--blue);box-sizing:border-box}
.dropzone.show{display:flex}
.dropzone>div{font-size:19px;font-weight:800;color:var(--blue);background:var(--card);padding:20px 30px;border-radius:16px;box-shadow:0 14px 40px rgba(0,0,0,.18)}
.upfile{margin:12px 0;font-size:13px}
.upfile .nm{display:flex;justify-content:space-between;color:var(--tx);margin-bottom:4px}
.upfile .nm span:last-child{color:var(--mut)}
.prog{height:8px;background:var(--bd);border-radius:6px;overflow:hidden}
.prog>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--blue),var(--blue2));transition:width .12s}

@media(max-width:640px){
  .grid{grid-template-columns:repeat(2,1fr);gap:10px}
  .tile{flex-direction:column;align-items:flex-start;gap:9px;padding:14px;min-height:auto}
  .tile .t{padding-right:0}
  .tile .acts{opacity:1;position:static;margin-top:2px;width:100%;justify-content:flex-end}
  .group{padding:14px 13px 16px}
  .search-wrap{width:96vw}
}
</style></head>
<body>
<div class="topbar"><div class="hero">
  <div class="brand"><span class="dot"></span>我的导航</div>
  <div class="search-wrap">
    <div class="search">
      <button class="eng-ico" id="engIco" onclick="toggleEng()" title="切换搜索引擎">B</button>
      <input id="q" placeholder="搜索网页，或直接输入网址跳转…" onkeydown="if(event.key==='Enter')websearch()">
      <button class="go" onclick="websearch()" title="搜索">↵</button>
    </div>
    <div class="eng-menu" id="engMenu"></div>
  </div>
  <div class="quick">
    <button class="qbtn p" onclick="openAdd()">＋ 添加</button>
    <button class="qbtn" onclick="openUp()">⬆ 上传</button>
    <button class="qbtn" onclick="openFiles()">📁 文件</button>
    <button class="qbtn" onclick="load()">⟳ 刷新</button>
    <button class="qbtn" onclick="location.href='/export'+(location.search)">⤓ 导出</button>
    <button class="qbtn" onclick="toggleTheme()" title="切换深色 / 浅色">🌗</button>
  </div>
</div></div>
<main id="main"></main>

<div class="modal" id="modal"><div class="box">
  <h3 id="mTitle">添加链接</h3>
  <label>网址 URL</label><input id="mUrl" placeholder="https://...">
  <label>标题</label><input id="mTitle2" placeholder="留空则用网址">
  <label>分组</label><input id="mGroup" placeholder="默认">
  <div class="row">
    <button class="qbtn" onclick="closeModal()">取消</button>
    <button class="qbtn p" id="mOk" onclick="submitModal()">保存</button>
  </div>
</div></div>

<div class="modal" id="upModal"><div class="box">
  <h3>⬆ 上传文件</h3>
  <p style="color:var(--mut);font-size:12px;margin:0 0 10px">保存到: <code id="upDir">__UPLOAD_DIR__</code></p>
  <input type="file" id="upFile" multiple style="width:100%;font-size:14px">
  <div id="upList"></div>
  <div id="upMsg" style="color:var(--mut);font-size:12px;margin-top:8px;min-height:16px"></div>
  <div class="row">
    <button class="qbtn" onclick="closeUp()">关闭</button>
    <button class="qbtn p" id="upBtn" onclick="doUpload()">上传</button>
  </div>
</div></div>

<div class="modal" id="fileModal"><div class="box" style="width:min(560px,94vw)">
  <h3>📁 已上传文件</h3>
  <div id="fileList" style="max-height:52vh;overflow:auto"></div>
  <div class="row">
    <button class="qbtn" onclick="closeFiles()">关闭</button>
    <button class="qbtn p" onclick="openUp()">上传新文件</button>
  </div>
</div></div>

<div class="dropzone" id="dropzone"><div>📤 拖拽文件到此处即可上传</div></div>
<div class="toast" id="toast"></div>

<script>
const ENGINES={'Bing':'https://www.bing.com/search?q=','Google':'https://www.google.com/search?q=','Baidu':'https://www.baidu.com/s?wd=','DuckDuckGo':'https://duckduckgo.com/?q=','GitHub':'https://github.com/search?q='};
let CUR_ENG=localStorage.getItem('save_eng')||'Bing';
const IS_MOBILE=/Android|iPhone|iPad|iPod|Mobile|Windows Phone|webOS|BlackBerry|HarmonyOS/i.test(navigator.userAgent);
(function(){const i=new Image();i.onload=()=>{document.body.classList.add('has-bg');document.body.style.setProperty('--bgimg','url("/bg")');};i.src='/bg';})();
let TOKEN=new URLSearchParams(location.search).get('token')||localStorage.getItem('save_token')||'';
let editingId=null;
const UPLOAD_DIR='__UPLOAD_DIR__';
function needToken(){if(!TOKEN){TOKEN=prompt('请输入访问密码(TOKEN)')||'';if(TOKEN)localStorage.setItem('save_token',TOKEN);}return TOKEN;}
function api(u,o){o=o||{};u+=(u.includes('?')?'&':'?')+'token='+encodeURIComponent(needToken());return fetch(u,o).then(r=>{if(r.status===401)throw new Error('密码错误');return r.json();});}
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.opacity='1';clearTimeout(t._t);t._t=setTimeout(()=>t.style.opacity='0',1500);}
function esc(s){return (s==null?'':String(s)).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
const ICO_COLORS=['#4f6ef7','#7c5cff','#f5578e','#ff8f5e','#2bb673','#19b3c9','#f0a020','#e0529c','#5b8def','#27c19a'];
function icoOf(x){let host='';try{host=new URL(x.url).hostname.replace(/^www\./,'');}catch(e){}const ch=(host||x.title||x.url||'?').charAt(0).toUpperCase();let h=0;const s2=host||(x.title||'');for(let i=0;i<s2.length;i++)h=(h*31+s2.charCodeAt(i))>>>0;return{ch:ch||'?',col:ICO_COLORS[h%ICO_COLORS.length]};}
function updateEngIco(){const b=document.getElementById('engIco');if(b)b.textContent=(CUR_ENG||'B').charAt(0);}
function buildEngMenu(){const m=document.getElementById('engMenu');if(!m)return;m.innerHTML=Object.keys(ENGINES).map(k=>'<div class="'+(k===CUR_ENG?'on':'')+'" data-k="'+k+'">'+k+'</div>').join('');m.querySelectorAll('div').forEach(d=>d.onclick=()=>{CUR_ENG=d.dataset.k;localStorage.setItem('save_eng',CUR_ENG);updateEngIco();toggleEng(false);});}
function toggleEng(force){const m=document.getElementById('engMenu');if(!m)return;const show=force===undefined?!m.classList.contains('show'):force;m.classList.toggle('show',show);}
function toggleTheme(){const d=document.body.classList.toggle('dark');localStorage.setItem('save_theme',d?'dark':'light');}
function websearch(){const q=document.getElementById('q').value.trim();if(!q)return;if(/^https?:\/\//i.test(q)){window.open(q,'_blank');return;}if(/^[\w-]+(\.[\w-]+)+/.test(q)){window.open('https://'+q,'_blank');return;}window.open(ENGINES[CUR_ENG]+encodeURIComponent(q),'_blank');}
document.addEventListener('click',e=>{if(!e.target.closest('.search-wrap'))toggleEng(false);});

async function load(){
  let data;
  try{data=await api('/api/list?limit=2000');}catch(e){toast(e.message);data=[];}
  const groups={};const orderNames=[];
  data.forEach(x=>{const g=x.group||'默认';if(!groups[g]){groups[g]=[];orderNames.push(g);}groups[g].push(x);});
  document.getElementById('cnt')&&(document.getElementById('cnt').textContent='共 '+data.length+' 条 / '+orderNames.length+' 个分组');
  const main=document.getElementById('main');
  if(!data.length){main.innerHTML='<div class="empty">还没有收藏，点「＋ 添加」开始 ✨</div>';return;}
  main.innerHTML=orderNames.map(g=>groupHtml(g,groups[g])).join('');
}
function groupHtml(g,items){
  return '<section class="group" data-g="'+esc(g)+'" draggable="true">'
    +'<h2 onclick="toggleGroup(\\''+esc(g)+'\\')">'
    +'<button class="gmv" title="左移" onclick="event.preventDefault();event.stopPropagation();moveGroup(\\''+esc(g)+'\\',-1)">◀</button>'
    +'<span class="gname">'+esc(g)+'</span><span class="cnt">'+items.length+'</span>'
    +'<button class="gmv" title="右移" onclick="event.preventDefault();event.stopPropagation();moveGroup(\\''+esc(g)+'\\',1)">▶</button>'
    +'<span class="chev" title="折叠/展开" onclick="event.stopPropagation();toggleGroup(\\''+esc(g)+'\\')">▾</span>'
    +'<span class="mini"><button class="qbtn" onclick="event.stopPropagation();renameGroup(\\''+esc(g)+'\\')">改名</button>'
    +'<button class="qbtn" onclick="event.stopPropagation();delGroup(\\''+esc(g)+'\\')">删组</button></span>'
    +'</h2>'
    +'<div class="body"><div class="grid">'+items.map(x=>tile(x)).join('')+'</div></div>'
    +'</section>';
}
function tile(x){
  const ic=icoOf(x);
  return '<a class="tile" data-id="'+esc(x.id)+'" href="'+esc(x.url)+'" target="_blank" rel="noopener" draggable="true">'
    +'<div class="ico" style="background:'+ic.col+'">'+esc(ic.ch)+'</div>'
    +'<div class="meta"><div class="t">'+esc(x.title||x.url)+'</div><div class="u">'+esc(x.url)+'</div></div>'
    +'<div class="acts">'
    +'<span title="上移" onclick="event.preventDefault();event.stopPropagation();moveTile(\\''+x.id+'\\',-1)">▲</span>'
    +'<span title="下移" onclick="event.preventDefault();event.stopPropagation();moveTile(\\''+x.id+'\\',1)">▼</span>'
    +'<span title="编辑" onclick="event.preventDefault();event.stopPropagation();editLink(\\''+x.id+'\\')">✎</span>'
    +'<span title="删除" onclick="event.preventDefault();event.stopPropagation();delLink(\\''+x.id+'\\')">✕</span>'
    +'</div></a>';
}
function findTile(id){return [...document.querySelectorAll('.tile')].find(t=>t.dataset.id===id);}
function findGroup(g){return [...document.querySelectorAll('.group')].find(x=>x.dataset.g===g);}
function moveTile(id,dir){
  const t=findTile(id);if(!t)return;
  if(dir<0){const p=t.previousElementSibling;if(p)t.parentNode.insertBefore(t,p);}
  else{const n=t.nextElementSibling;if(n)t.parentNode.insertBefore(n,t);}
  saveOrder();
}
function moveGroup(g,dir){
  const el=findGroup(g);if(!el)return;
  if(dir<0){const p=el.previousElementSibling;if(p)el.parentNode.insertBefore(el,p);}
  else{const n=el.nextElementSibling;if(n)el.parentNode.insertBefore(n,el);}
  saveOrder();
}
function buildOrder(){
  const groups=[];const items={};
  document.querySelectorAll('#main>.group').forEach(g=>{
    groups.push(g.dataset.g);
    const ids=[];g.querySelectorAll('.tile').forEach(t=>ids.push(t.dataset.id));
    items[g.dataset.g]=ids;
  });
  return {groups,items};
}
function saveOrder(){
  const o=buildOrder();
  api('/api/reorder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)})
    .then(()=>toast('顺序已保存')).catch(e=>toast('保存失败:'+e.message));
}
let DND=null;
const mainEl=document.getElementById('main');
mainEl.addEventListener('dragstart',e=>{
  const tileEl=e.target.closest('.tile');
  const grpEl=e.target.closest('.group');
  if(tileEl){DND={type:'tile',id:tileEl.dataset.id};tileEl.classList.add('dragging');}
  else if(grpEl){DND={type:'group',g:grpEl.dataset.g};grpEl.classList.add('dragging');}
});
mainEl.addEventListener('dragover',e=>{if(DND)e.preventDefault();});
mainEl.addEventListener('drop',e=>{
  if(!DND)return;e.preventDefault();
  const tileEl=e.target.closest('.tile');
  const grpEl=e.target.closest('.group');
  if(DND.type==='tile'&&tileEl){
    const src=findTile(DND.id);if(src&&src!==tileEl)tileEl.parentNode.insertBefore(src,tileEl);
  }else if(DND.type==='group'&&grpEl){
    const src=findGroup(DND.g);if(src&&src!==grpEl)grpEl.parentNode.insertBefore(src,grpEl);
  }
  clearDnd();saveOrder();
});
mainEl.addEventListener('dragend',clearDnd);
function clearDnd(){document.querySelectorAll('.dragging').forEach(el=>el.classList.remove('dragging'));DND=null;}

function delLink(id){if(!confirm('确定删除这条？'))return;api('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}).then(()=>{toast('已删除');load();}).catch(e=>toast(e.message));}
function delGroup(g){if(!confirm('删除分组「'+g+'」会同时删除其中的所有链接，确定？'))return;api('/api/group',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',name:g})}).then(()=>{toast('已删除分组');load();}).catch(e=>toast(e.message));}
function renameGroup(g){const n=prompt('分组「'+g+'」改名为：',g);if(!n)return;api('/api/group',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'rename',name:g,newName:n})}).then(()=>{toast('已改名');load();}).catch(e=>toast(e.message));}
function openAdd(){editingId=null;document.getElementById('mTitle').textContent='添加链接';document.getElementById('mUrl').value='';document.getElementById('mTitle2').value='';document.getElementById('mGroup').value='';document.getElementById('modal').classList.add('show');}
function editLink(id){api('/api/list?limit=2000').then(d=>{const x=d.find(r=>r.id===id);if(!x)return;editingId=id;document.getElementById('mTitle').textContent='编辑链接';document.getElementById('mUrl').value=x.url;document.getElementById('mTitle2').value=x.title||'';document.getElementById('mGroup').value=x.group||'';document.getElementById('modal').classList.add('show');});}
function closeModal(){document.getElementById('modal').classList.remove('show');}
function submitModal(){const url=document.getElementById('mUrl').value.trim();if(!url){toast('网址不能为空');return;}const body={url,title:document.getElementById('mTitle2').value.trim(),group:document.getElementById('mGroup').value.trim()};let p;if(editingId){body.id=editingId;p=api('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}else{p=api('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}p.then(()=>{toast('已保存');closeModal();load();}).catch(e=>toast(e.message));}
document.getElementById('modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal();});

function toggleGroup(g){const el=findGroup(g);if(el)el.classList.toggle('collapsed');}

// ===== 文件上传 / 管理 =====
function openUp(){document.getElementById('upDir').textContent=UPLOAD_DIR;document.getElementById('upMsg').textContent='';document.getElementById('upList').innerHTML='';document.getElementById('upFile').value='';document.getElementById('upModal').classList.add('show');}
function closeUp(){document.getElementById('upModal').classList.remove('show');}
function uploadOne(f,barId,tEl){
  return new Promise(resolve=>{
    const fd=new FormData();fd.append('file',f,f.name);
    const xhr=new XMLHttpRequest();
    xhr.open('POST','/api/upload');
    if(TOKEN)xhr.setRequestHeader('Authorization','Bearer '+TOKEN);
    xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);const b=document.getElementById(barId);if(b)b.style.width=p+'%';if(tEl)tEl.textContent=p+'%';}};
    xhr.onload=()=>{const b=document.getElementById(barId);if(b)b.style.width='100%';resolve(xhr.status>=200&&xhr.status<300);};
    xhr.onerror=()=>resolve(false);
    xhr.send(fd);
  });
}
async function runUpload(files){
  const list=document.getElementById('upList');const msg=document.getElementById('upMsg');const btn=document.getElementById('upBtn');btn.disabled=true;
  let ok=0,fail=0;
  for(let i=0;i<files.length;i++){
    const f=files[i];const barId='pb'+i;
    const row=document.createElement('div');row.className='upfile';
    row.innerHTML='<div class="nm"><span>'+esc(f.name)+'</span><span id="'+barId+'_t">0%</span></div><div class="prog"><i id="'+barId+'"></i></div>';
    list.appendChild(row);
    const good=await uploadOne(f,barId,document.getElementById(barId+'_t'));
    good?ok++:fail++;
    msg.textContent='已完成 '+(ok+fail)+'/'+files.length+(fail?('，失败 '+fail):'');
  }
  btn.disabled=false;
  if(ok)toast('上传成功 '+ok+' 个'+(fail?('，失败 '+fail):''));
  else if(fail)toast('上传失败 '+fail+' 个');
}
function doUpload(){const inp=document.getElementById('upFile');if(!inp.files||!inp.files.length){toast('请先选择文件');return;}runUpload(inp.files);}
function openFiles(){loadFiles();document.getElementById('fileModal').classList.add('show');}
function closeFiles(){document.getElementById('fileModal').classList.remove('show');}
function fmtSize(b){if(b<1024)return b+' B';if(b<1048576)return (b/1024).toFixed(1)+' KB';return (b/1048576).toFixed(1)+' MB';}
function enc(s){return encodeURIComponent(s);}
async function loadFiles(){
  const box=document.getElementById('fileList');box.innerHTML='加载中…';
  try{
    const d=await api('/api/files');
    if(!d.length){box.innerHTML='<div class="empty">还没有上传文件</div>';return;}
    box.innerHTML=d.map(x=>'<div class="file-row">'
      +'<a class="file-name" href="/files/'+enc(x.name)+'" target="_blank" rel="noopener" title="'+esc(x.name)+'">'+esc(x.name)+'</a>'
      +'<span class="file-meta">'+fmtSize(x.size)+' · '+esc(x.mtime)+'</span>'
      +'<span class="file-del" title="删除" onclick="event.stopPropagation();delFile(\\''+esc(x.name)+'\\')">✕</span>'
      +'</div>').join('');
  }catch(e){box.innerHTML='加载失败: '+esc(e.message);}
}
async function delFile(n){
  if(!confirm('删除文件「'+n+'」？此操作不可恢复'))return;
  try{await api('/api/file-del',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});toast('已删除');loadFiles();}
  catch(e){toast('删除失败:'+e.message);}
}
const _closeMap={modal:closeModal,upModal:closeUp,fileModal:closeFiles};
['modal','upModal','fileModal'].forEach(id=>{const el=document.getElementById(id);if(el)el.addEventListener('click',e=>{if(e.target.id===id)_closeMap[id]();});});
(function(){
  const dz=document.getElementById('dropzone');let n=0;
  const isFile=e=>e.dataTransfer&&Array.from(e.dataTransfer.types||[]).indexOf('Files')>=0;
  window.addEventListener('dragenter',e=>{if(!isFile(e))return;e.preventDefault();n++;dz.classList.add('show');});
  window.addEventListener('dragover',e=>{if(isFile(e)){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
  window.addEventListener('dragleave',e=>{if(!isFile(e))return;n=Math.max(0,n-1);if(!n)dz.classList.remove('show');});
  window.addEventListener('drop',e=>{
    if(!isFile(e))return;e.preventDefault();n=0;dz.classList.remove('show');
    const files=e.dataTransfer.files;if(!files||!files.length)return;
    openUp();runUpload(files);
  });
})();
// ===== init =====
buildEngMenu();updateEngIco();
(function(){const t=localStorage.getItem('save_theme');if(t==='dark')document.body.classList.add('dark');else if(t==='light'){}else if(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)document.body.classList.add('dark');})();
load();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "NAS-SaveURL/2.0"

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CONFIG["CORS_ORIGIN"])
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        return self.rfile.read(n) if n > 0 else b""

    def do_OPTIONS(self):
        self._send(204)

    def _send_bg(self):
        exts = ["jpg", "jpeg", "png", "webp", "gif", "avif"]
        ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                 "webp": "image/webp", "gif": "image/gif", "avif": "image/avif"}
        for ext in exts:
            p = os.path.join(CONFIG["DATA_DIR"], "bg." + ext)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", ctype[ext])
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
        self._send(404, b'')

    def _serve_file(self, path):
        ctype, _ = mimetypes.guess_type(path)
        ctype = ctype or "application/octet-stream"
        inline = ctype.startswith(("image/", "text/")) or ctype == "application/pdf"
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception:
            self._send(404, b'{"error":"not found"}')
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         ("inline" if inline else "attachment") +
                         '; filename="' + os.path.basename(path) + '"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            body = VIEW_HTML.replace("__UPLOAD_DIR__", CONFIG["UPLOAD_DIR"]).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return
        if u.path == "/api/list":
            if not check_view_auth(self.headers, qs):
                self._send(401, b'{"error":"unauthorized"}')
                return
            self._send(200, json.dumps(sort_by_order(_load_all()), ensure_ascii=False).encode("utf-8"))
            return
        if u.path == "/export":
            if not check_view_auth(self.headers, qs):
                self._send(401, b'{"error":"unauthorized"}')
                return
            _ensure_store()
            with open(CONFIG["DATA_FILE"], "rb") as f:
                data = f.read()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", "attachment; filename=links.jsonl")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/bg":
            self._send_bg()
            return
        if u.path == "/api/files":
            if not check_view_auth(self.headers, qs):
                self._send(401, b'{"error":"unauthorized"}')
                return
            self._send(200, json.dumps(list_uploads(), ensure_ascii=False).encode("utf-8"))
            return
        if u.path.startswith("/files/"):
            if not check_view_auth(self.headers, qs):
                self._send(401, b'{"error":"unauthorized"}')
                return
            name = _safe_name(u.path[len("/files/"):])
            p = os.path.abspath(os.path.join(CONFIG["UPLOAD_DIR"], name))
            root = os.path.abspath(CONFIG["UPLOAD_DIR"])
            if p != root and not p.startswith(root + os.sep):
                self._send(403, b'{"error":"forbidden"}')
                return
            if not os.path.isfile(p):
                self._send(404, b'{"error":"not found"}')
                return
            self._serve_file(p)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/api/save", "/api/delete", "/api/update", "/api/group",
                      "/api/reorder", "/api/upload", "/api/file-del"):
            if not check_auth(self.headers, qs):
                self._send(401, b'{"error":"unauthorized"}')
                return
            if u.path == "/api/upload":
                body = self._body()
                saved, err = save_upload(body, self.headers.get("Content-Type", ""))
                if err:
                    self._send(400, json.dumps({"error": err}, ensure_ascii=False).encode("utf-8"))
                    return
                self._send(200, json.dumps({"ok": True, "saved": saved}, ensure_ascii=False).encode("utf-8"))
                return
            if u.path == "/api/file-del":
                try:
                    data = json.loads(self._body().decode("utf-8") or "{}")
                except Exception:
                    self._send(400, b'{"error":"bad json"}')
                    return
                ok = delete_upload(data.get("name", ""))
                self._send(200, json.dumps({"ok": ok}, ensure_ascii=False).encode("utf-8"))
                return
            try:
                data = json.loads(self._body().decode("utf-8") or "{}")
            except Exception:
                self._send(400, b'{"error":"bad json"}')
                return
            if u.path == "/api/save":
                url = (data.get("url") or "").strip()
                if not url:
                    self._send(400, b'{"error":"url required"}')
                    return
                rec = append_link(url, data.get("title"), data.get("group"))
                self._send(200, json.dumps({"ok": True, "rec": rec}, ensure_ascii=False).encode("utf-8"))
            elif u.path == "/api/delete":
                n = delete_link(data.get("id"))
                self._send(200, json.dumps({"ok": True, "removed": n}, ensure_ascii=False).encode("utf-8"))
            elif u.path == "/api/update":
                ok = update_link(data.get("id"), data.get("title"), data.get("url"), data.get("group"))
                self._send(200, json.dumps({"ok": ok}, ensure_ascii=False).encode("utf-8"))
            elif u.path == "/api/group":
                ok = group_action(data.get("action"), data.get("name"), data.get("newName"))
                self._send(200, json.dumps({"ok": ok}, ensure_ascii=False).encode("utf-8"))
            elif u.path == "/api/reorder":
                groups = data.get("groups")
                items = data.get("items")
                if not isinstance(groups, list) or not isinstance(items, dict):
                    self._send(400, b'{"error":"bad payload"}')
                    return
                _save_order({"groups": groups, "items": items})
                self._send(200, b'{"ok": true}')
            return
        self._send(404, b'{"error":"not found"}')


def main():
    if CONFIG["TOKEN"] in ("", "CHANGE_ME"):
        print("[警告] 未设置 TOKEN, 接口处于无鉴权状态, 请勿暴露到公网!")
    srv = ThreadingHTTPServer((CONFIG["HOST"], CONFIG["PORT"]), Handler)
    print(f"✅ 服务已启动: http://{CONFIG['HOST']}:{CONFIG['PORT']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

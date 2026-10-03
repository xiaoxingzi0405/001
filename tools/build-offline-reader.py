#!/usr/bin/env python3
"""Build a self-contained offline conversation reader with the Python standard library.

Run from any directory: python3 tools/build-offline-reader.py
The default output is START-HERE.html at the repository root. Neither the source
conversation files nor the index are modified. Custom --archive and --output
paths are useful for validating an export before publishing it.
"""

import argparse
import json
from pathlib import Path


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>游戏 · 生图 · 分割 — 离线会话归档</title>
<style>
:root{color-scheme:light;--ink:#172c38;--muted:#546772;--paper:#f5f7f8;--line:#d5dfe4;--accent:#1d6675}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.7 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:26px 32px 20px;border-bottom:1px solid var(--line);background:#fff}h1{font-size:25px;margin:0 0 6px}p{margin:0 0 10px}.subtitle,.muted{color:var(--muted)}
.notice{margin-top:16px;padding:13px 16px;background:#fff4d9;border:1px solid #e1cb93;border-radius:8px;color:#5b471d}.notice p:last-child{margin-bottom:0}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr);max-width:1580px;margin:auto;min-height:65vh}aside{padding:22px;border-right:1px solid var(--line)}
label{display:block;font-weight:650;margin-bottom:8px}input{width:100%;font:inherit;padding:10px;border:1px solid #a7bdc7;border-radius:7px;background:#fff;color:var(--ink)}
input:focus-visible,button:focus-visible{outline:3px solid #76afbb;outline-offset:2px}#search-status{font-size:13px;color:var(--muted);margin:9px 0 18px;min-height:22px}
#thread-list{display:grid;gap:8px}button{font:inherit;cursor:pointer}button.thread{width:100%;text-align:left;padding:11px;border:1px solid var(--line);border-radius:7px;color:var(--ink);background:#fff}
button.thread[aria-current="true"]{background:#e5f1f3;border-color:var(--accent);box-shadow:inset 3px 0 var(--accent)}.thread-title{display:block;font-weight:650}.thread-info{display:block;font-size:12px;color:var(--muted)}
main{min-width:0;padding:24px 28px;background:#fff}h2{font-size:23px;line-height:1.5;margin:0 0 8px}.metadata{font-size:14px;color:var(--muted);overflow-wrap:anywhere;margin-bottom:12px}
.selection-status{font-size:14px;background:#f0f4f5;border-radius:7px;padding:10px 13px;margin-bottom:18px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:15px 0}
#clear-search{border:1px solid var(--line);padding:5px 12px;border-radius:6px;color:var(--ink);background:#fff}#match-count{font-size:14px;color:var(--muted)}
pre{font:14px/1.9 ui-monospace,SFMono-Regular,Consolas,"Microsoft YaHei",monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:18px;background:#fbfcfd;border:1px solid var(--line);border-radius:8px}
mark{background:#ffe79c;color:#24200d}.empty{padding:25px;color:var(--muted);border:1px dashed var(--line);border-radius:8px}footer{max-width:1580px;margin:auto;padding:20px 30px;color:var(--muted);font-size:14px;border-top:1px solid var(--line)}
[hidden]{display:none!important}@media(max-width:750px){header{padding:20px}.layout{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line);padding:18px}#thread-list{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:20px}h1{font-size:22px}}
</style>
</head>
<body>
<header>
<h1>游戏 · 生图 · 分割 / 离线会话归档</h1>
<p class="subtitle">下载仓库 ZIP 并解压后，双击 START-HERE.html 即可阅读。此页面不需要安装软件、启动服务器或联网。</p>
<p id="archive-summary" class="muted"></p>
<div class="notice" role="note">
<p id="material-status"></p>
<p>“成功生图记录”表示会话记录中生成任务完成，不能据此认为图片文件已上传。会话内的旧电脑路径、链接和命令均只作为文字展示。</p>
<p id="completeness-status"></p>
</div>
</header>
<div class="layout">
<aside aria-label="搜索与会话选择">
<label for="search">搜索全部会话</label>
<input id="search" type="search" placeholder="输入关键词，例如：贴纸" autocomplete="off" spellcheck="false">
<p id="search-status" role="status" aria-live="polite"></p>
<nav id="thread-list" aria-label="归档会话"></nav>
</aside>
<main aria-label="会话内容">
<section id="reader">
<h2 id="thread-title"></h2>
<p id="thread-metadata" class="metadata"></p>
<p id="thread-material-status" class="selection-status"></p>
<div class="toolbar"><span id="match-count">原 Markdown 文本</span><button id="clear-search" type="button" hidden>清除搜索</button></div>
<pre id="conversation" tabindex="0" aria-label="会话原 Markdown 文本"></pre>
</section>
<p id="empty-state" class="empty" hidden>没有匹配的会话。请更换关键词或清除搜索。</p>
</main>
</div>
<footer>这里展示的是已导出的归档快照；不会自动恢复 Codex 侧边栏里的历史会话。原始导出与素材清单位于 conversation-archive 文件夹。需要刷新此页面的数据时运行 python3 tools/build-offline-reader.py。</footer>
<noscript><p class="notice">请允许浏览器运行此本地页面的 JavaScript，或直接阅读 conversation-archive/threads 内的 conversation.md 文件。</p></noscript>
<script id="archive-data" type="application/json">__ARCHIVE_PAYLOAD__</script>
<script>
"use strict";
const archive = JSON.parse(document.getElementById("archive-data").textContent);
const threads = archive.threads;
let selectedId = threads.length ? threads[0].thread_id : null;
const byId = id => document.getElementById(id);
const integer = value => Number.isFinite(value) ? value : 0;
const label = thread => String(thread.title || "未命名会话") + (thread.archived ? "（已归档会话）" : "");
const totals = archive.totals || {};
byId("archive-summary").textContent = `${threads.length} 个会话 · ${integer(totals.deduplicated_message_count)} 条可读取消息 · ${integer(totals.completed_image_generation_record_count)} 条成功生图记录 · 快照时间：${archive.captured_at_asia_shanghai || archive.captured_at_utc || "未记录"}`;
byId("material-status").textContent = `实际归档的二进制文件：${integer(totals.binary_files_archived)} 个。` + (archive.complete_material_backup === true ? "索引标记为素材备份完整；本页面只展示会话文字，素材请查看仓库文件。" : "原始图片、视频、游戏工程和分割成果尚未全部取得；当前归档不能当作全部素材备份。");
byId("completeness-status").textContent = archive.all_original_logs_guaranteed === true ? "索引标记历史日志完整。" : "导出接口可能省略或截断部分历史消息、附件与工具输出，无法保证原始日志全文。";

function appendBody(text, query) {
  const target = byId("conversation");
  target.replaceChildren();
  if (!query) {
    target.textContent = text;
    byId("match-count").textContent = "原 Markdown 文本（保留原文，不执行内容）";
    return;
  }
  const folded = text.toLocaleLowerCase();
  const needle = query.toLocaleLowerCase();
  let cursor = 0, count = 0, at;
  const fragment = document.createDocumentFragment();
  while ((at = folded.indexOf(needle, cursor)) !== -1) {
    fragment.append(document.createTextNode(text.slice(cursor, at)));
    const hit = document.createElement("mark");
    hit.textContent = text.slice(at, at + needle.length);
    fragment.append(hit);
    cursor = at + needle.length;
    count += 1;
  }
  fragment.append(document.createTextNode(text.slice(cursor)));
  target.append(fragment);
  byId("match-count").textContent = `本会话正文匹配 ${count} 处；显示完整原文`;
}

function render() {
  const query = byId("search").value.trim();
  const folded = query.toLocaleLowerCase();
  const visible = threads.filter(thread => !query || (label(thread) + "\n" + thread.text).toLocaleLowerCase().includes(folded));
  if (!visible.some(thread => thread.thread_id === selectedId)) selectedId = visible.length ? visible[0].thread_id : null;
  const list = byId("thread-list");
  list.replaceChildren();
  for (const thread of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thread";
    button.dataset.threadId = thread.thread_id;
    button.setAttribute("aria-current", String(thread.thread_id === selectedId));
    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = label(thread);
    const info = document.createElement("span");
    info.className = "thread-info";
    info.textContent = `${integer(thread.deduplicated_message_count)} 条消息 · ${integer(thread.completed_image_generation_record_count)} 条生图记录`;
    button.append(title, info);
    button.addEventListener("click", () => { selectedId = thread.thread_id; render(); });
    list.append(button);
  }
  byId("search-status").textContent = query ? `匹配 ${visible.length} / ${threads.length} 个会话（全文搜索）` : `已加载 ${threads.length} 个会话；点击名称阅读`;
  byId("clear-search").hidden = !query;
  byId("reader").hidden = !selectedId;
  byId("empty-state").hidden = Boolean(selectedId);
  if (!selectedId) {
    byId("conversation").textContent = "";
    return;
  }
  const thread = visible.find(item => item.thread_id === selectedId);
  byId("thread-title").textContent = label(thread);
  byId("thread-metadata").textContent = `会话 ID：${thread.thread_id} · ${integer(thread.deduplicated_message_count)} 条可读取消息 · ${integer(thread.completed_image_generation_record_count)} 条成功生图记录`;
  byId("thread-material-status").textContent = `此会话已归档二进制文件：${integer(thread.binary_files_archived)} 个。` + (thread.source_materials_retrieved === true ? "索引标记源素材已取得；本页面只展示会话文字。" : "源素材尚未取得，原文中的图片或工程路径不代表文件已上传。");
  appendBody(thread.text, query);
}
byId("search").addEventListener("input", render);
byId("clear-search").addEventListener("click", () => { byId("search").value = ""; render(); byId("search").focus(); });
render();
</script>
</body>
</html>
'''


def build_reader(archive_dir, output_path):
    archive_dir = Path(archive_dir).resolve()
    index = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    threads = []
    for source in index["threads"]:
        path = (archive_dir / source["conversation_path"]).resolve()
        if not path.is_relative_to(archive_dir):
            raise ValueError("conversation_path must stay inside the archive directory")
        item = {key: source.get(key) for key in (
            "thread_id", "title", "archived", "deduplicated_message_count",
            "completed_image_generation_record_count", "binary_files_archived",
            "source_materials_retrieved",
        )}
        item["text"] = path.read_text(encoding="utf-8")
        threads.append(item)
    payload = {key: index.get(key) for key in (
        "captured_at_utc", "captured_at_asia_shanghai", "totals",
        "complete_material_backup", "all_original_logs_guaranteed",
    )}
    payload["threads"] = threads
    # JSON is embedded inside a script element, whose HTML parser still treats
    # </script> as a terminator even when it appears inside a JSON string. Escape
    # all HTML-significant characters before embedding; JSON.parse restores them.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for character, escaped in (("&", "\\u0026"), ("<", "\\u003c"),
                               (">", "\\u003e"), ("\u2028", "\\u2028"),
                               ("\u2029", "\\u2029")):
        encoded = encoded.replace(character, escaped)
    output_path = Path(output_path)
    output_path.write_text(TEMPLATE.replace("__ARCHIVE_PAYLOAD__", encoded), encoding="utf-8")
    return len(threads), output_path.stat().st_size


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=root / "conversation-archive")
    parser.add_argument("--output", type=Path, default=root / "START-HERE.html")
    args = parser.parse_args()
    count, size = build_reader(args.archive, args.output)
    print(f"Built {args.output}: {count} conversations, {size} bytes")


if __name__ == "__main__":
    main()

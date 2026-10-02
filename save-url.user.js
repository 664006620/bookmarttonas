// ==UserScript==
// @name         保存当前网址到 NAS
// @namespace    https://github.com/yourname/save-url-nas
// @version      1.3.0
// @description  右键菜单或悬浮按钮, 一键保存/查看/删除/分组同步到 NAS 的网址(导航页); 手机端单悬浮球: 点击保存/长按打开收藏
// @author       you
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-idle
// @license      MIT
// ==/UserScript==

(function () {
  'use strict';

  /* ===================== 配置区 ===================== */
  // 改成你的 NAS 服务地址 (建议 https + 域名, 不能用局域网 IP 除非手机和 NAS 同网段)
  const NAS_API = 'https://your-nas.example.com';
  const TOKEN   = 'CHANGE_ME';          // 与 server.py 的 TOKEN 一致
  const NAS_VIEW = '';                  // 查看页地址, 留空则自动用 NAS_API + '/'
  const USE_FLOATING_BUTTON = true;     // 是否显示右下角悬浮按钮(保存+收藏)
  const USE_CONTEXT_MENU    = true;     // 是否劫持右键菜单加入「保存/查看」项
  const LIST_LIMIT = 200;               // 内嵌面板最多拉取条数
  const FAB_OPACITY   = 0.9;            // 悬浮球透明度 0~1 (1=完全不透明; 鼠标悬停自动变全亮)
  const FAB_POSITION  = 'bottom-right'; // 悬浮球默认位置: bottom-right / bottom-left / top-right / top-left
  // 位置也可直接在页面上拖动悬浮球微调, 松开后会自动记住
  // 提示: 按住 Shift 再右键 = 显示浏览器原生菜单 (临时绕过劫持)
  /* ================================================ */

  const API_SAVE = NAS_API.replace(/\/+$/, '') + '/api/save';
  const API_LIST = NAS_API.replace(/\/+$/, '') + '/api/list';
  const VIEW_URL = (NAS_VIEW || NAS_API).replace(/\/+$/, '') + '/';

  /* ---------- 网络请求 ---------- */
  function sendSave(url, title, group) {
    const payload = JSON.stringify({ url: url, title: title || document.title || url, group: group || undefined });
    const headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN };

    const viaFetch = () => fetch(API_SAVE, { method: 'POST', headers: headers, body: payload })
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(() => toast('已保存 ✓'))
      .catch(e => toast('保存失败: ' + e.message));

    if (typeof GM_xmlhttpRequest !== 'undefined') {
      GM_xmlhttpRequest({
        method: 'POST',
        url: API_SAVE,
        headers: headers,
        data: payload,
        onload: function (res) {
          if (res.status >= 200 && res.status < 300) toast('已保存 ✓');
          else toast('保存失败: ' + res.status);
        },
        onerror: function () { viaFetch(); }
      });
    } else {
      viaFetch();
    }
  }

  function fetchList() {
    const headers = { 'Authorization': 'Bearer ' + TOKEN };
    return new Promise((resolve, reject) => {
      if (typeof GM_xmlhttpRequest !== 'undefined') {
        GM_xmlhttpRequest({
          method: 'GET', url: API_LIST + '?limit=' + LIST_LIMIT, headers: headers,
          onload: r => { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
          onerror: () => reject(new Error('网络错误'))
        });
      } else {
        fetch(API_LIST + '?limit=' + LIST_LIMIT, { headers: headers })
          .then(r => r.json()).then(resolve).catch(reject);
      }
    });
  }

  /* ---------- 轻量提示 ---------- */
  let toastTimer = null;
  function toast(msg) {
    let el = document.getElementById('__nas_save_toast');
    if (!el) {
      el = document.createElement('div');
      el.id = '__nas_save_toast';
      el.style.cssText = 'position:fixed;left:50%;top:20px;transform:translateX(-50%);' +
        'z-index:2147483647;background:rgba(31,35,41,.92);color:#fff;padding:10px 16px;' +
        'border-radius:10px;font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);' +
        'pointer-events:none;transition:opacity .25s;max-width:80vw;text-align:center';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 1600);
  }

  /* ---------- 悬浮按钮 + 内嵌收藏面板 ---------- */
  if (USE_FLOATING_BUTTON) {
    function cornerBase() {
      const m = 18, c = FAB_POSITION;
      let s = 'position:fixed;z-index:2147483646;width:46px;height:46px;border-radius:50%;' +
        'background:#2f6bff;color:#fff;display:flex;align-items:center;justify-content:center;' +
        'font-size:22px;cursor:pointer;box-shadow:0 4px 14px rgba(47,107,255,.45);user-select:none;' +
        'touch-action:none;';
      s += (c.indexOf('right') >= 0 ? 'right:' + m + 'px;' : 'left:' + m + 'px;');
      s += (c.indexOf('bottom') >= 0 ? 'bottom:' + m + 'px;' : 'top:' + m + 'px;');
      return s;
    }

    function makeFab(icon, title, key, onClick, stack) {
      const b = document.createElement('div');
      b.textContent = icon;
      b.title = title;
      b.style.cssText = cornerBase();
      if (stack) {                                   // 第二个按钮错开, 叠在第一个旁边
        const off = 56;
        if (FAB_POSITION.indexOf('bottom') >= 0) b.style.bottom = (18 + off) + 'px';
        else b.style.top = (18 + off) + 'px';
      }
      b.style.opacity = FAB_OPACITY;
      b.onmouseenter = () => { b.style.opacity = '1'; };
      b.onmouseleave = () => { b.style.opacity = FAB_OPACITY; };
      b.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
      // 拖动微调 + 记住位置 (跨页面/重启后保留)
      let drag = false, sx = 0, sy = 0, ox = 0, oy = 0;
      b.addEventListener('pointerdown', (e) => {
        drag = true; sx = e.clientX; sy = e.clientY;
        const r = b.getBoundingClientRect(); ox = r.left; oy = r.top;
        b.style.right = 'auto'; b.style.bottom = 'auto'; b.style.left = ox + 'px'; b.style.top = oy + 'px';
        e.preventDefault();
      });
      window.addEventListener('pointermove', (e) => {
        if (!drag) return;
        b.style.left = (ox + e.clientX - sx) + 'px';
        b.style.top = (oy + e.clientY - sy) + 'px';
      });
      window.addEventListener('pointerup', () => {
        if (!drag) return; drag = false;
        try { GM_setValue('nas_fab_' + key, JSON.stringify({ l: parseInt(b.style.left) || 0, t: parseInt(b.style.top) || 0 })); } catch (e) {}
      });
      try {
        const p = JSON.parse((typeof GM_getValue !== 'undefined' && GM_getValue('nas_fab_' + key, 'null')) || 'null');
        if (p && !isNaN(p.l) && !isNaN(p.t)) {
          b.style.right = 'auto'; b.style.bottom = 'auto'; b.style.left = p.l + 'px'; b.style.top = p.t + 'px';
        }
      } catch (e) {}
      document.body.appendChild(b);
      return b;
    }

    const IS_MOBILE = /Mobi|Android|iPhone|iPad|iPod|Windows Phone|HarmonyOS|webOS|BlackBerry/i.test(navigator.userAgent);
    const saveBall = makeFab('💾', '保存当前网址到 NAS（点击保存 / 长按打开收藏）', 'save',
      IS_MOBILE ? (() => {}) : () => sendSave(location.href, document.title), false);

    // 收藏面板
    const ENGINES = {
      'Bing': 'https://www.bing.com/search?q=',
      'Google': 'https://www.google.com/search?q=',
      'Baidu': 'https://www.baidu.com/s?wd=',
      'DuckDuckGo': 'https://duckduckgo.com/?q='
    };
    const API_BASE = NAS_API.replace(/\/+$/, '');
    let panel = null;
    function closePanel() { if (panel) { panel.remove(); panel = null; } }

    function webSearchPanel() {
      const e = panel.querySelector('#__nas_eng').value;
      const q = panel.querySelector('#__nas_wq').value.trim();
      if (q) window.open(ENGINES[e] + encodeURIComponent(q), '_blank');
    }

    function sendDelete(id) {
      const headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN };
      const body = JSON.stringify({ id: id });
      const go = () => fetch(API_BASE + '/api/delete', { method: 'POST', headers: headers, body: body })
        .then(() => { toast('已删除'); openPanel(); })
        .catch(e => toast('删除失败: ' + e.message));
      if (typeof GM_xmlhttpRequest !== 'undefined') {
        GM_xmlhttpRequest({ method: 'POST', url: API_BASE + '/api/delete', headers: headers, data: body,
          onload: r => { if (r.status >= 200 && r.status < 300) { toast('已删除'); openPanel(); } else toast('删除失败:' + r.status); },
          onerror: go });
      } else { go(); }
    }

    function renderPanel() {
      const list = panel._data || [];
      const q = (panel.querySelector('#__nas_q').value || '').toLowerCase();
      const groups = {};
      list.filter(x => ((x.title || '') + ' ' + (x.url || '')).toLowerCase().includes(q))
          .forEach(x => { const g = x.group || '默认'; (groups[g] = groups[g] || []).push(x); });
      const names = Object.keys(groups).sort();
      panel.querySelector('#__nas_count').textContent = '共 ' + list.length + ' 条 / ' + names.length + ' 组';
      const box = panel.querySelector('#__nas_list');
      if (!list.length) { box.innerHTML = '<div style="padding:24px;text-align:center;color:#9aa0a6">暂无收藏，右键💾保存一条</div>'; return; }
      box.innerHTML = names.map(g => `
        <div style="font-size:12px;color:#8a9099;margin:10px 4px 2px">${esc(g)} · ${groups[g].length}</div>
        ${groups[g].map(x => `
          <div style="display:flex;gap:8px;align-items:flex-start;padding:8px 10px;border:1px solid #eef0f3;border-radius:9px;margin:5px 0;background:#fff">
            <a href="${esc(x.url)}" target="_blank" rel="noopener" style="flex:1;min-width:0;color:#2f6bff;text-decoration:none">
              <div style="font-weight:600;word-break:break-all">${esc(x.title || x.url)}</div>
              <div style="color:#9aa0a6;font-size:12px;word-break:break-all">${esc(x.url)}</div>
            </a>
            <span data-del="${esc(x.id)}" title="删除" style="cursor:pointer;color:#c33;opacity:.55;padding:2px 4px;font-size:15px">✕</span>
          </div>`).join('')}
      `).join('');
      box.querySelectorAll('[data-del]').forEach(s => s.onclick = (e) => {
        e.stopPropagation();
        if (confirm('确定删除这条？')) sendDelete(s.getAttribute('data-del'));
      });
    }

    function openPanel() {
      if (panel) { closePanel(); return; }
      panel = document.createElement('div');
      panel.style.cssText = 'position:fixed;right:18px;bottom:74px;z-index:2147483647;' +
        'width:340px;max-width:92vw;max-height:70vh;display:flex;flex-direction:column;' +
        'background:#fff;color:#1f2329;border:1px solid #e5e7eb;border-radius:14px;' +
        'box-shadow:0 12px 40px rgba(0,0,0,.22);font:14px/1.5 system-ui,sans-serif;overflow:hidden;';
      panel.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #eef0f3">
          <strong style="flex:1">🔖 我的收藏</strong>
          <a href="${esc(VIEW_URL)}" target="_blank" rel="noopener" title="在 NAS 打开完整导航页"
             style="color:#2f6bff;text-decoration:none;font-size:12px">完整页 ↗</a>
          <span id="__nas_close" style="cursor:pointer;color:#9aa0a6;padding:0 4px">✕</span>
        </div>
        <div style="padding:8px 12px;border-bottom:1px solid #eef0f3;display:flex;gap:6px">
          <select id="__nas_eng" style="padding:6px;border:1px solid #d0d5dd;border-radius:8px;font-size:12px">
            ${Object.keys(ENGINES).map(k => '<option>' + k + '</option>').join('')}
          </select>
          <input id="__nas_wq" placeholder="搜网页…" style="flex:1;min-width:0;padding:6px 9px;border:1px solid #d0d5dd;border-radius:8px;font-size:13px">
          <button id="__nas_wb" style="padding:6px 10px;border:0;border-radius:8px;background:#2f6bff;color:#fff;cursor:pointer;font-size:12px">搜</button>
        </div>
        <div style="padding:8px 12px;border-bottom:1px solid #eef0f3">
          <input id="__nas_q" placeholder="筛选我的收藏…" style="width:100%;padding:7px 9px;border:1px solid #d0d5dd;border-radius:8px;box-sizing:border-box;font-size:13px">
          <div id="__nas_count" style="color:#8a9099;font-size:12px;margin-top:5px"></div>
        </div>
        <div id="__nas_list" style="overflow:auto;padding:6px 8px"></div>`;
      document.body.appendChild(panel);
      panel.querySelector('#__nas_close').onclick = closePanel;
      panel.querySelector('#__nas_q').addEventListener('input', renderPanel);
      panel.querySelector('#__nas_wb').onclick = webSearchPanel;
      panel.querySelector('#__nas_wq').addEventListener('keydown', e => { if (e.key === 'Enter') webSearchPanel(); });
      panel._data = [];
      renderPanel();
      panel.querySelector('#__nas_list').innerHTML = '<div style="padding:24px;text-align:center;color:#9aa0a6">加载中…</div>';
      fetchList().then(list => { if (panel) { panel._data = list; renderPanel(); } })
        .catch(e => { if (panel) panel.querySelector('#__nas_list').innerHTML = '<div style="padding:24px;text-align:center;color:#d33">加载失败: ' + esc(e.message) + '</div>'; });
    }

    if (IS_MOBILE) {
      // 手机: 单悬浮球 —— 点击保存, 长按(~500ms)打开收藏面板
      let lpTimer = null, longPressed = false;
      const startLp = () => { longPressed = false; lpTimer = setTimeout(() => {
        longPressed = true; try { navigator.vibrate && navigator.vibrate(30); } catch (_) {}
        openPanel();
      }, 500); };
      const cancelLp = () => { if (lpTimer) { clearTimeout(lpTimer); lpTimer = null; } };
      saveBall.addEventListener('pointerdown', startLp);
      saveBall.addEventListener('pointerup', cancelLp);
      saveBall.addEventListener('pointerleave', cancelLp);
      saveBall.addEventListener('pointercancel', cancelLp);
      saveBall.addEventListener('click', (e) => {
        e.stopPropagation();
        if (longPressed) { longPressed = false; return; }
        sendSave(location.href, document.title);
      });
    } else {
      makeFab('📂', '查看收藏列表', 'list', openPanel, true);
    }

    document.addEventListener('click', (e) => { if (panel && !panel.contains(e.target) && !e.target.closest('[title="查看收藏列表"]')) closePanel(); }, true);
    window.addEventListener('blur', closePanel);
  }

  /* ---------- 自定义右键菜单 ---------- */
  if (USE_CONTEXT_MENU) {
    let menu = null;
    function closeMenu() { if (menu) { menu.remove(); menu = null; } }

    function showMenu(x, y) {
      closeMenu();
      const sel = (window.getSelection && window.getSelection().toString().trim()) || '';
      menu = document.createElement('div');
      menu.style.cssText = 'position:fixed;z-index:2147483647;background:#fff;color:#1f2329;' +
        'min-width:180px;border:1px solid #e5e7eb;border-radius:10px;padding:6px;' +
        'box-shadow:0 8px 28px rgba(0,0,0,.18);font:14px/1.4 system-ui,sans-serif;';
      const items = [
        { label: '💾 保存当前网址', act: () => sendSave(location.href, document.title) },
        { label: '📂 查看收藏列表', act: () => window.open(VIEW_URL, '_blank') },
        { label: '🔗 复制当前网址', act: () => { navigator.clipboard && navigator.clipboard.writeText(location.href); toast('已复制网址'); } },
      ];
      if (sel) items.splice(1, 0, { label: '📝 保存选中文字', act: () => sendSave(location.href, sel.slice(0, 80)) });
      items.forEach(it => {
        const d = document.createElement('div');
        d.textContent = it.label;
        d.style.cssText = 'padding:9px 12px;border-radius:7px;cursor:pointer;white-space:nowrap';
        d.onmouseenter = () => d.style.background = '#f2f4f7';
        d.onmouseleave = () => d.style.background = 'transparent';
        d.onclick = () => { it.act(); closeMenu(); };
        menu.appendChild(d);
      });
      document.body.appendChild(menu);
      const r = menu.getBoundingClientRect();
      menu.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
      menu.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
    }

    document.addEventListener('contextmenu', (e) => {
      if (e.shiftKey) return;
      if (e.target && e.target.closest && e.target.closest('[title="查看收藏列表"]')) return;
      e.preventDefault();
      showMenu(e.clientX, e.clientY);
    }, true);

    document.addEventListener('click', closeMenu, true);
    document.addEventListener('scroll', closeMenu, true);
    window.addEventListener('blur', closeMenu);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); }, true);
  }

  /* ---------- 工具 ---------- */
  function esc(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

})();

# 一键保存网址到 NAS

跨浏览器（桌面 Chrome/Edge/Firefox + 手机 Via 浏览器）保存当前网址的方案：
**用户脚本（UserScript）+ NAS 上的零依赖 Python 服务**。

- 网页**右键菜单**一键保存，或**右下角悬浮按钮**一键保存
- 数据实时同步到你的 **NAS**（落盘为 `data/links.jsonl`）
- 提供网页端查看 / 搜索 / 导出已保存链接

> 为什么是用户脚本而不是扩展（Extension）？因为手机 Via 浏览器不支持 Chrome/Firefox 扩展，
> 但支持导入用户脚本。用户脚本在桌面（Tampermonkey/Violentmonkey）和 Via 上都能跑，是唯一跨平台方案。

---

## 一、在 NAS 上部署服务端

把 `nas-server/` 整个目录放到 NAS 上（群晖/威联通/任何能跑 Python3 的设备都行）。

```bash
cd nas-server
TOKEN=你的强密码 PORT=8000 python3 server.py
```

- `TOKEN`：接口鉴权密钥，**必须改掉默认的 `CHANGE_ME`**
- `PORT`：监听端口，默认 8000
- `CORS_ORIGIN`：默认 `*` 允许任意来源（用户脚本从任意网页发起），如担心可改成你的域名
- 数据保存在 `nas-server/data/links.jsonl`

### 建议用反代加 HTTPS（强烈推荐）

用户脚本要从**任意网页**（含 https 站点）发起请求，NAS 接口必须能被跨域访问且最好走 HTTPS，
否则手机/桌面会遇到混合内容或 CORS 拦截。用 nginx/caddy 反代到 `localhost:8000` 并配证书：

```nginx
server {
    listen 443 ssl;
    server_name save.your-nas.example.com;
    ssl_certificate     /path/fullchain.pem;
    ssl_certificate_key /path/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

然后脚本里的 `NAS_API` 填 `https://save.your-nas.example.com`。

> 仅在内网用？手机必须和 NAS 同一网段才能访问局域网 IP；外网访问务必走域名+HTTPS。

### 开机自启 / 后台常驻

- 群晖：套件中心装「Python3」后用「任务计划」或 Docker 跑
- 通用：用 `systemd` 或 `nohup python3 server.py &` / `screen`

---

## 二、安装用户脚本

### 桌面（Chrome / Edge / Firefox）
1. 装扩展：[Tampermonkey](https://www.tampermonkey.net/) 或 [Violentmonkey](https://violentmonkey.github.io/)
2. 点开 `save-url.user.js` → Tampermonkey 会提示安装
3. 编辑脚本顶部「配置区」：
   - `NAS_API` 改成你的地址（如 `https://save.your-nas.example.com`）
   - `TOKEN` 改成和 NAS 服务端一致的密钥

### 手机 Via 浏览器
1. Via 设置 → 脚本（或「用户脚本」）→ 添加脚本 → 粘贴 `save-url.user.js` 内容保存
2. 同样把脚本顶部的 `NAS_API` 和 `TOKEN` 改成你的
3. 之后在任意网页**长按（等同于右键）→ 选「保存当前网址」**，或点右下角 💾 按钮

> Via 的长按菜单行为取决于版本；若长按未弹出自定义菜单，直接用右下角悬浮 💾 按钮最稳。

---

## 三、使用

| 操作 | 效果 |
|------|------|
| 右键 → 💾 保存当前网址 | 保存当前页 URL + 标题 |
| 右键 → 📝 保存选中文字 | 有选中文字时出现，把选中内容当标题保存 |
| 右键 → 🔗 复制当前网址 | 复制当前地址到剪贴板 |
| 点击右下角 💾 悬浮按钮 | 一键保存当前网址（桌面可拖动；**手机端只显示一个球**：轻点保存，长按约 0.5 秒打开收藏面板） |
| **按住 Shift 再右键** | 临时显示浏览器原生菜单（绕过劫持） |

保存后右上角会弹「已保存 ✓」提示。

## 四、查看 / 管理已保存的链接

浏览器打开 `https://save.your-nas.example.com/`（服务端根路径）即是一个**导航页**：
- **搜索框居中**：顶部居中放置搜索引擎栏（支持 Bing/Google/Baidu/DuckDuckGo/GitHub，本地记忆选择），下方一排操作按钮。
- **分组默认折叠**：每个分组标题左侧有 ▾，默认折叠，点 ▾ 或组名展开；展开后仍可拖拽 / ▲▼/◀▶ 排序。
- 链接按分组展示，支持手动添加、编辑、删除、改名分组，以及拖拽 / ▲▼/◀▶ 调整顺序（顺序存于 `nas-server/data/order.json`）。也支持搜索和导出。
- **布局自适应**：手机走卡片网格、电脑走紧凑列表（按 UA 自动判断）。
- **背景**：默认渐变；把图片命名为 `bg.jpg`（或 png/webp/gif）放到 `nas-server/data/` 即用自定义背景。
- **上传文件**：两种方式——① 点「📤 上传」选文件（可多选）；② **直接把文件拖到页面任意位置**，会弹出蓝色虚线遮罩，松手即上传。每个文件都有**实时进度条**（基于 XHR 上传进度）。文件保存到 `UPLOAD_DIR`（默认 `/mnt/sata-2/download`，可用环境变量 `UPLOAD_DIR` 修改）；点「📁 文件」查看 / 下载 / 删除已上传文件。文件名已做防目录穿越处理。
原始数据在 `nas-server/data/links.jsonl`（每行一条 JSON）。

## 五、安全提示

- **一定要改 `TOKEN`**，否则任何人都能往你的 NAS 写数据
- 不要把无鉴权的服务暴露到公网
- 公开访问建议加一层反代鉴权 / 防火墙白名单

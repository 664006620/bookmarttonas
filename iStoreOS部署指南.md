# iStoreOS（软路由 / OpenWrt）部署「保存网址到 NAS」服务

> 你的环境是 **iStoreOS 软路由**，它基于 OpenWrt。它没有群晖那种"任务计划"图形界面，
> 但用 OpenWrt 原生的 **procd 开机启动脚本** 更稳：服务开机自启、崩溃还能自动重启。
> 数据落盘在你软路由挂的硬盘上（或系统盘 overlay，重启不丢）。
> 对外访问依旧用你已经装好的 **Lucky** 做域名 + HTTPS 反向代理。

---

## 0. 架构图

```
电脑 / 手机(跑用户脚本)
        │  https://save.你的域名.com
        ▼
  [Lucky 反向代理]   ← iStoreOS 上已装，做域名+证书+DDNS
        │  内网转发 127.0.0.1:8000
        ▼
  [Python 服务 server.py]   ← 本机常驻运行(开机自启)
        │
        ▼
  iStoreOS 硬盘: /mnt/sda1/saveurl/data/links.jsonl
```

---

## 1. 安装 Python3

iStoreOS 用 `opkg` 包管理器。

1. 打开 iStoreOS 网页 → **系统 → 终端**（TTYD 网页终端），用 `root` + 你设的密码登录。
2. 贴入执行：
   ```
   opkg update
   opkg install python3
   ```
3. 验证：`python3 --version` 能显示版本号即成功。
   （若提示找不到包，去 **iStore 应用商店** 搜 "Python3" 安装；或确认软路由能联网。）

---

## 2. 把 server.py 放到软路由上

1. iStoreOS 网页 → **系统 → 文件管理**（File Manager）。
2. 进入你挂的硬盘，例如 `/mnt/sda1/`，新建文件夹 `saveurl`。
3. 把 `server.py` 上传进去（路径会变成 `/mnt/sda1/saveurl/server.py`）。
   > 没有额外硬盘也行，用 `/root/saveurl/` 或 `/opt/saveurl/` 也可以，overlay 会保留。
   > 只是数据备份时记得连这个目录一起备。
4. 数据会自动生成在 `saveurl/data/links.jsonl`。

---

## 3. 创建开机自启脚本（核心步骤）

OpenWrt 用 procd 管理开机服务。我们提供一个现成脚本 `saveurl.initd`，改两处就能用。

### 3.1 改脚本
用文本编辑器打开 `saveurl.initd`，改这两行：
- `command ... /mnt/sda1/saveurl/server.py` → 改成你实际的 server.py 路径
- `TOKEN="你的强密码"` → 改成你自己的密码（要和后面用户脚本里的 `TOKEN` 一致）

### 3.2 上传并启用
1. 在**文件管理**里把改好的 `saveurl.initd` 上传到 `/etc/init.d/`，文件名改为 `saveurl`
   （即最终路径 `/etc/init.d/saveurl`）。
2. 回到**终端**，执行：
   ```
   chmod +x /etc/init.d/saveurl
   /etc/init.d/saveurl enable
   /etc/init.d/saveurl start
   ```
3. 看是否跑起来了：
   ```
   ps | grep server.py
   logread | grep saveurl
   ```

> `enable` 会在 `/etc/rc.d/` 生成开机链接，以后重启软路由会自动拉起；
> `respawn` 保证进程意外退出会被自动重启。想重启服务就 `/etc/init.d/saveurl restart`。

---

## 4. 用 Lucky 做域名 + HTTPS + 反向代理

和之前一样，Lucky 在 iStoreOS 上操作一致：

1. **（动态公网 IP 才需要）DDNS**：Lucky → DDNS → 添加，域名填 `save.你的域名.com`，指向你家公网 IP。
2. **证书**：Lucky → 安全 → 证书 → 用 Let's Encrypt 自动申请 `save.你的域名.com`。
3. **反向代理**：Lucky → 反向代理 → 添加：
   | 字段 | 填什么 |
   |---|---|
   | 前端监听类型 | **HTTPS** |
   | 监听端口 | `443` |
   | 域名 | `save.你的域名.com` |
   | 证书 | 选上面申请的 |
   | 后端服务地址 | `http://127.0.0.1:8000` |
4. 保存。

> 外网访问需把路由器（或 iStoreOS 防火墙）的 **80/443** 放行到本机；
> Lucky 一般直接监听 80/443，所以只要防火墙允许 80/443 入站即可。

---

## 5. 验证

1. **内网先测**：浏览器开 `http://iStoreOS的LAN_IP:8000`
   （LAN IP 通常是 `192.168.x.1`，在 iStoreOS 网络状态里能看到）。
   看到**导航页**（带搜索引擎栏 + 分组卡片）= Python 服务正常 ✅
   - 若打不开：终端 `logread | grep saveurl` 看报错；或临时在
     **网络 → 防火墙 → 通信规则** 加一条允许 LAN→本机 8000 端口。
2. **外网/HTTPS 测**：开 `https://save.你的域名.com` → 看到导航页 = Lucky 反代通了 ✅
3. **跨设备**：电脑右键💾存一条 → 手机开域名或点悬浮📂能看到 = 全链路 OK ✅

---

## 5.5 导航页（管理收藏）怎么用

浏览器打开 `https://你的域名`，就是一个**导航页**：既能随手搜网页，又能按分组管理你存的所有网址。

- **顶部搜索栏**：选搜索引擎（Bing / Google / Baidu / DuckDuckGo / GitHub）直接搜网页，引擎本地记住。
- **分组卡片**：每条收藏归到一个分组（默认「默认」），同组一个卡片网格。
- **+ 添加链接**：手动新增（填网址 / 标题 / 分组）。
- **每条卡片**：悬停出现 ✎编辑、✕删除、**▲上移 / ▼下移**。
- **分组标题**：旁有 **◀ ▶** 调整分组顺序，外加「改名」「删组」。
- **排序保存**：拖拽或点 ▲▼/◀▶，顺序自动存到 NAS 的 `saveurl/data/order.json`，全设备共用。

**调整顺序两种方式**：
- 桌面：直接拖动卡片 / 拖动分组标题，松手即存。
- 手机 Via（触屏）：用卡片上的 ▲▼、分组旁的 ◀▶ 按钮，效果一样。

> 首次打开输入一次 TOKEN 密码，浏览器记住；完整管理（拖拽/编辑/分组）建议直接开这个导航页，
> 脚本悬浮 📂 只适合快速查看。

**外观与布局**
- **搜索框居中**：顶部居中的搜索引擎栏（Bing/Google/Baidu/DuckDuckGo/GitHub，选择会被记住），下方一排操作按钮。
- **分组默认折叠**：分组标题左侧有 ▾，默认折叠，点 ▾ 或组名展开；展开后仍可拖拽 / ▲▼/◀▶ 排序。
- **背景图**：默认渐变背景。想用自己的图，命名 `bg.jpg`（支持 png/webp/gif，优先 jpg）放到 `saveurl/data/` 目录，刷新即生效。
- **自动适配**：按浏览器 UA 自动切换——手机卡片网格、电脑紧凑列表，无需手动设置。
- 支持跟随系统的深色模式。

**上传文件**
- 点「📤 上传」选文件（可多选），保存到 `UPLOAD_DIR`，默认 `/mnt/sata-2/download`；改路径给服务加环境变量 `UPLOAD_DIR=/你的/路径`（在 `saveurl.initd` 里加一行 `procd_set_param env UPLOAD_DIR=...`）。
- 点「📁 文件」查看、下载、删除已上传文件；上传已做防目录穿越，文件只会落在上传目录内。
- 上传目录与脚本数据目录（`saveurl/data/`）是两处独立路径，确认 `UPLOAD_DIR` 指向的磁盘已挂载且可写。

---

## 6. 改用户脚本地址

`save-url.user.js` 顶部：
```js
const NAS_API = 'https://save.你的域名.com';
const TOKEN   = '你的强密码';
```
装回浏览器（桌面 Tampermonkey / 手机 Via 导入）。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `opkg: command not found` | 终端环境异常 | 用 iStoreOS 自带终端；或先 `export PATH=/usr/sbin:/usr/bin:/sbin:/bin` |
| 能存但重启后没了 | 没 enable 启动脚本 | 确认执行了 `/etc/init.d/saveurl enable` |
| 内网 :8000 打不开 | 防火墙拦了 | 临时加防火墙规则放行 8000，或直接用 Lucky 域名测 |
| 域名打不开 | Lucky 规则/证书问题 | 检查域名、证书、后端地址 127.0.0.1:8000 |
| 保存失败 | TOKEN/地址不对 | 检查脚本 `NAS_API`、`TOKEN` 与 init 脚本一致 |

## 安全
- 务必改 `TOKEN`，别用默认 `CHANGE_ME`。
- 公网暴露建议 Lucky 加访问控制 / 防火墙白名单。
- 定期备份 `saveurl/data/links.jsonl`（在你挂的硬盘上）。

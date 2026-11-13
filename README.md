## 4K-IPTV-M3U

基于组播源的省级直播列表仓库，按省份自动生成 `m3u/txt` 文件，并在 README 中展示可直接使用的加速下载链接。
### 咪咕源 实时更新 https://gh-proxy.org/https://github.com/jia070310/lemonTV/blob/main/iptv-fe.m3u
### 相关播放器项目

- 纯直播 APP: [lemonTV](https://github.com/jia070310/lemonTV)
- 影视+直播集合版: [lomenTV-VDS](https://github.com/jia070310/lomenTV-VDS)
- Windows 直播播放器: [lemonIPTV-windows](https://github.com/jia070310/lemonIPTV-windows)
- 影视客户端:[MacCMS影视服务前端播放器](https://github.com/jia070310/lemonTV-Film)

![预览图](https://github.com/jia070310/4K-IPTV-M3U/blob/main/tv.png)

### 仓库内容

- `rtp/b.py`: 从 [IPTV神器Pro](https://iptv.cqshushu.com/index.php) 抓取组播源，按省份/运营商生成 `m3u/txt`
- `m3u/`: 自动生成的 M3U 文件
- `txt/`: 自动生成的 TXT 文件
- `.github/workflows/`: 定时任务与自动更新流程

### 更新机制

- 默认只抓取 **浙江**，每个运营商只取 1 条最新可用源，全局节流 + 限流自动降速，避免被源站拦截
- 每次运行覆盖生成仓库根目录的 `zj.m3u` / `zj.txt`（固定聚合订阅文件），并同步更新 `m3u/`、`txt/` 分文件
- 抓取失败时**保留原有文件**，不会清空订阅源
- 同步自动重写 README 的订阅地址与文件列表（含“最近更新时间”）
- 只操作本仓库 `wyhcoool/4K-IPTV-M3U`：`git add / commit / push` 一条龙，**不需要任何 Token、不跨仓库**；电视 App 订阅地址指向本仓库的 `zj.m3u`，文件每次被覆盖，地址固定不变
- 下载链接统一使用 `gh-proxy` 加速前缀
- `.github/workflows/update-iptv.yml`：每两天（北京时间 09:00）云端自动运行并推送，也可在 Actions 页手动触发
- 本机定时：双击 `run_update.bat` 一键更新；双击 `register_task.bat` 注册 Windows 计划任务（每两天 09:00）。**云端 Actions 与本机计划任务二选一即可，避免重复抓取**

### 本地运行

```bash
pip install -r requirements.txt
python rtp/b.py              # 抓取 + 生成 + 自动 git 提交推送（默认）
python rtp/b.py --no-push    # 只生成本地文件
python rtp/b.py --dry-run    # 只抓取统计，不改动任何文件
python rtp/b.py --delay 4    # 被限流时调大请求间隔（秒）
```

<!-- SUBSCRIBE_START -->
## 电视 App 订阅地址

- **主地址（推荐）**：`https://gh-proxy.com/https://github.com/wyhcoool/4K-IPTV-M3U/blob/main/zj.m3u`
- 备用（gh-proxy.org raw 加速）：`https://gh-proxy.org/https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/zj.m3u`
- 备用原始直链：`https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/zj.m3u`
- 备用（jsDelivr CDN）：`https://cdn.jsdelivr.net/gh/wyhcoool/4K-IPTV-M3U@main/zj.m3u`

本仓库的 `zj.m3u` 每次更新会被覆盖，地址固定不变，App 里填一次即可。（最近更新：2026-11-13 15:29:12）
<!-- SUBSCRIBE_END -->

## 加速下载说明

以下下载链接均已添加 `gh-proxy` 加速前缀，可直接使用。  
GitHub README 不支持可执行脚本，`onclick` 复制按钮会失效，因此改为“可复制直链”文本（手动复制即可）。

---

## M3U 文件列表

<table style="width:100%; table-layout:auto;">
<colgroup>
<col style="width: 220px;" />
<col style="width: 120px;" />
<col style="width: 170px;" />
<col />
</colgroup>
<thead>
<tr>
<th style="white-space:nowrap;">文件名</th>
<th style="white-space:nowrap;">加速链接</th>
<th style="white-space:nowrap;">最近更新时间</th>
<th style="white-space:nowrap;">可复制直链</th>
</tr>
</thead>
<tbody>
<tr><td style="white-space:nowrap;">浙江电信.m3u</td><td style="white-space:nowrap;"><a href="https://gh-proxy.org/https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/m3u/%E6%B5%99%E6%B1%9F%E7%94%B5%E4%BF%A1.m3u">下载链接</a></td><td style="white-space:nowrap;">2026-11-13 15:29:12</td><td><code>https://gh-proxy.org/https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/m3u/%E6%B5%99%E6%B1%9F%E7%94%B5%E4%BF%A1.m3u</code></td></tr>
</tbody>
</table>
## TXT 文件列表

<table style="width:100%; table-layout:auto;">
<colgroup>
<col style="width: 220px;" />
<col style="width: 120px;" />
<col style="width: 170px;" />
<col />
</colgroup>
<thead>
<tr>
<th style="white-space:nowrap;">文件名</th>
<th style="white-space:nowrap;">加速链接</th>
<th style="white-space:nowrap;">最近更新时间</th>
<th style="white-space:nowrap;">可复制直链</th>
</tr>
</thead>
<tbody>
<tr><td style="white-space:nowrap;">浙江电信.txt</td><td style="white-space:nowrap;"><a href="https://gh-proxy.org/https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/txt/%E6%B5%99%E6%B1%9F%E7%94%B5%E4%BF%A1.txt">下载链接</a></td><td style="white-space:nowrap;">2026-11-13 15:29:12</td><td><code>https://gh-proxy.org/https://raw.githubusercontent.com/wyhcoool/4K-IPTV-M3U/main/txt/%E6%B5%99%E6%B1%9F%E7%94%B5%E4%BF%A1.txt</code></td></tr>
</tbody>
</table>
---

## 免责声明

- 本仓库中的频道地址来源于网络公开信息抓取与整理，仅供技术学习、测试与研究使用。
- 本仓库不存储、不制作任何视频内容，不提供任何视听节目传播服务。
- 链接可用性与内容合法性由源站提供方负责，可能随时失效或变更。
- 使用者应遵守所在地法律法规及相关版权要求，因使用本仓库内容产生的风险与责任由使用者自行承担。

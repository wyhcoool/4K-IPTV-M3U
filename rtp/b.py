#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浙江 IPTV 组播源抓取 -> 生成 txt/m3u + 固定聚合订阅文件 -> 推送到本仓库。

只操作 wyhcoool/4K-IPTV-M3U 这一个仓库，不需要 Token、不跨仓库：
聚合文件 zj.m3u 每次运行被覆盖，电视 App 订阅地址固定不变。

常用命令：
    python rtp/b.py                 # 抓取浙江 + 生成文件 + git 提交推送（默认）
    python rtp/b.py --no-push       # 只生成本地文件，不推送
    python rtp/b.py --dry-run       # 只抓取并统计，不改动任何文件、不推送
    python rtp/b.py --delay 4       # 调大请求间隔（秒），被拦截时更稳
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import random
import re
import string
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urlencode

import requests

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# ================= 配置区域 =================
# 1. 抓取范围：默认只要浙江
TARGET_PROVINCES = ["浙江"]
PROVINCES = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海",
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
             "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西",
             "甘肃", "青海", "宁夏", "新疆"]
PROVINCE_CODES = {
    "北京": "bj", "天津": "tj", "河北": "he", "山西": "sx", "内蒙古": "nm",
    "辽宁": "ln", "吉林": "jl", "黑龙江": "hl", "上海": "sh",
    "江苏": "js", "浙江": "zj", "安徽": "ah", "福建": "fj", "江西": "jx",
    "山东": "sd", "河南": "ha", "湖北": "hb", "湖南": "hn", "广东": "gd",
    "广西": "gx", "海南": "hi", "重庆": "cq", "四川": "sc", "贵州": "gz",
    "云南": "yn", "陕西": "sn", "甘肃": "gs", "青海": "qh", "宁夏": "nx",
    "新疆": "xj",
}
CARRIERS = ("电信", "移动", "联通")

# 2. 组播源网站配置（IPTV神器Pro）
IPTV_BASE_URL = "https://iptv.cqshushu.com/"
IPTV_INDEX = "index.php"
PAER_HMAC_KEY = "tdSQ4QZEaQPPff7e4wMReKjhnwXecJUxJTdAVDGIql9xR3fIAf"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# 3. 请求节流（防 429 / 封 IP）
REQUEST_MIN_DELAY = 2.5        # 相邻两次请求的最小间隔（秒）
REQUEST_JITTER = 0.8           # 间隔随机抖动，避免固定节奏被识别
REQUEST_MAX_RETRIES = 4        # 单次请求最多尝试次数
REQUEST_TIMEOUT = 25           # 单次请求超时
LIST_PAGE_LIMIT = 20           # 服务器列表每页条数（站点固定值）
CHANNEL_PAGE_LIMIT = 20        # 频道列表每页条数（站点忽略 limit 参数，固定 20 条）
LIST_MAX_PAGES = 4             # 服务器列表最多翻几页
CHANNEL_MAX_PAGES = 20         # 频道列表最多翻几页（20*20=400 条，足够覆盖浙江全部频道）

# 4. 输出与本仓库（4K-IPTV-M3U）推送
AGGREGATE_M3U = "zj.m3u"       # 固定聚合订阅文件：电视 App 只填这一个地址
AGGREGATE_TXT = "zj.txt"       # 同名 txt 版，便于其他播放器使用
README_FILE = "README.md"
EPG_URL = "http://epg.51zmt.top:8000/e.xml.gz"
TVG_LOGO_BASE_URL = "https://gcore.jsdelivr.net/gh/taksssss/tv/icon/"
PROXY_PREFIX = "https://gh-proxy.org/"      # README 表格里的加速前缀
SUBSCRIBE_PROXY_PREFIX = "https://gh-proxy.com/"  # 电视 App 主地址沿用用户熟悉的加速域名
DEFAULT_REPO = "wyhcoool/4K-IPTV-M3U"   # 仅当无法从 git remote 推断时使用
DEFAULT_BRANCH = "main"
GITHUB_COMMIT_PREFIX = "Auto update"
# 推送时需要一并同步的路径（脚本/工作流改动也要上云，否则定时任务跑的是旧代码）
TRACKED_PATHS = (
    "txt", "m3u", README_FILE, AGGREGATE_M3U, AGGREGATE_TXT,
    "rtp/b.py", ".github/workflows", "requirements.txt", ".gitignore",
    "run_update.bat", "register_task.bat",
)

# 明显无用的占位频道，生成聚合文件时跳过
SKIP_CHANNEL_KEYWORDS = ("百事通画面", "未知节目", "未识别", "测试频道")
# ============================================

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": IPTV_BASE_URL + IPTV_INDEX,
})


class RateLimiter:
    """全局节流器：所有请求共用一个最小间隔；被限流时自动降速，连续成功后缓慢恢复。"""

    def __init__(self, min_delay: float, jitter: float):
        self.base = float(min_delay)
        self.jitter = float(jitter)
        self.penalty = 1.0
        self.last_request_at = 0.0
        self.success_streak = 0
        self.total_requests = 0
        self.total_throttles = 0

    def interval(self) -> float:
        return min(self.base * self.penalty, 20.0)

    def wait(self) -> None:
        gap = max(0.5, self.interval() + random.uniform(-self.jitter, self.jitter))
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self.last_request_at = time.monotonic()
        self.total_requests += 1

    def on_throttled(self) -> None:
        self.penalty = min(self.penalty * 1.6, 8.0)
        self.success_streak = 0
        self.total_throttles += 1

    def note_backoff(self) -> None:
        """已经按 Retry-After 退避过了，下一轮不必再等一个完整间隔。"""
        self.last_request_at = time.monotonic() - self.interval()

    def on_success(self) -> None:
        self.success_streak += 1
        if self.success_streak >= 5 and self.penalty > 1.0:
            self.penalty = max(1.0, self.penalty / 1.3)
            self.success_streak = 0


LIMITER = RateLimiter(REQUEST_MIN_DELAY, REQUEST_JITTER)


# ---------------- 基础工具 ----------------

def _strip_html(raw: str) -> str:
    no_tags = re.sub(r"<[^>]+>", "", raw)
    return unescape(no_tags).replace("\xa0", " ").strip()


def _parse_site_datetime(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def beijing_now() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=8)))


def generate_paer_token() -> str:
    """生成 iptv.cqshushu.com 请求签名（X-CSRF-TOKEN）。"""
    ts = str(int(time.time()))
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    msg = f"{ts}|{rand}"
    sig = hmac.new(PAER_HMAC_KEY.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{ts}|{rand}|{sig}"


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return 0.0


def _backoff(attempt: int) -> float:
    return min(60.0, (2 ** attempt) * 3 + random.uniform(0, 1.5))


def signed_get(path_query: str, session: requests.Session | None = None) -> dict:
    """带签名的 GET：统一节流 + 429/403 智能退避，返回 JSON。"""
    url = IPTV_BASE_URL + path_query.lstrip("/")
    sess = session or _SESSION
    last_error: Exception | None = None

    for attempt in range(REQUEST_MAX_RETRIES):
        headers = {
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": generate_paer_token(),
        }
        LIMITER.wait()
        try:
            resp = sess.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            last_error = e
            wait = _backoff(attempt)
            print(f"[!] 网络异常，{wait:.1f}s 后重试 ({attempt + 1}/{REQUEST_MAX_RETRIES}): {e}")
            time.sleep(wait)
            LIMITER.note_backoff()
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                raise RuntimeError(f"响应不是 JSON（可能被拦截页替换）: {resp.text[:120]}")
            LIMITER.on_success()
            return data

        if resp.status_code in (403, 429, 502, 503, 504):
            wait = max(_retry_after_seconds(resp.headers.get("Retry-After")), _backoff(attempt))
            LIMITER.on_throttled()
            print(f"[!] HTTP {resp.status_code} 被限流，{wait:.1f}s 后重试 "
                  f"({attempt + 1}/{REQUEST_MAX_RETRIES})，后续间隔自动降速至 {LIMITER.interval():.1f}s")
            time.sleep(wait)
            LIMITER.note_backoff()
            last_error = RuntimeError(f"HTTP {resp.status_code}")
            continue

        # 其它状态直接失败，不做无意义重试
        resp.raise_for_status()
        last_error = RuntimeError(f"HTTP {resp.status_code}")
        break

    raise last_error or RuntimeError(f"请求失败: {url}")


# ---------------- 站点解析 ----------------

def _parse_list_rows(html: str) -> list[dict]:
    """从 IP 列表页 HTML 解析组播行。"""
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL):
        ip_match = re.search(
            r"gotoIP\('([^']+)',\s*'multicast'\)", row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not ip_match:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        if len(tds) < 6:
            continue
        rows.append({
            "p_token": ip_match.group(1).strip(),
            "host": _strip_html(tds[0]),
            "type": _strip_html(tds[2]),
            "online_time": _strip_html(tds[3]),
            "update_time": _strip_html(tds[4]),
            "status": _strip_html(tds[5]),
        })
    return rows


def _has_next_page(html: str, page: int) -> bool:
    """判断是否还有下一页；站点若不带分页标记，靠 重复页 / 短页 / 空页 兜底。"""
    return bool(
        re.search(r"下一页|next", html, flags=re.IGNORECASE)
        or re.search(rf"page={page + 1}(?!\d)", html, flags=re.IGNORECASE)
    )


def _should_stop_paging(html: str, page: int, added: int, page_size: int, limit: int) -> bool:
    """
    末页判定：重复页、短页立即停；无“下一页”标记时，从第 2 页起停。
    第 1 页即使没有标记也再取一页确认，避免站点不输出分页控件时漏数据。
    """
    if added == 0 or page_size == 0:
        return True
    if 0 < limit and page_size < limit:
        return True
    return not _has_next_page(html, page) and page > 1


def fetch_region_rows_by_ajax(province: str, max_pages: int = LIST_MAX_PAGES, session=None) -> list[dict]:
    """按省份+组播类型抓取服务器列表；拿到全部数据后立即停，不再空翻页。"""
    region_code = PROVINCE_CODES.get(province)
    if not region_code:
        print(f"[-] 未找到省份 [{province}] 的 region code，跳过。")
        return []

    print(f"[*] 抓取服务器列表: {IPTV_BASE_URL}{IPTV_INDEX}?t=multicast&province={region_code}")
    all_rows: list[dict] = []
    seen_tokens: set[str] = set()

    for page_num in range(1, max_pages + 1):
        query = urlencode({
            "t": "multicast", "province": region_code,
            "limit": LIST_PAGE_LIMIT, "page": page_num,
        })
        try:
            data = signed_get(f"{IPTV_INDEX}?{query}", session=session)
        except Exception as e:
            print(f"[-] 请求省份 [{province}] 第{page_num}页失败: {e}")
            break
        if data.get("status") != "success":
            print(f"[-] 第{page_num}页返回失败: {data.get('message', 'unknown error')}")
            break

        html = data.get("html", "")
        rows = _parse_list_rows(html)
        if not rows:
            break
        added = 0
        for row in rows:
            token = row.get("p_token")
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            all_rows.append(row)
            added += 1
        print(f"[*] [{province}] 第{page_num}页 {len(rows)} 条，新增 {added} 条。")
        # 末页 / 重复页 / 无下一页：立刻停，避免无意义请求触发限流
        if _should_stop_paging(html, page_num, added, len(rows), LIST_PAGE_LIMIT):
            break

    print(f"[*] [{province}] 合计 {len(all_rows)} 条服务器。")
    return all_rows


def parse_s_token(detail_html: str) -> str | None:
    """从 IP 详情页提取频道列表 s token。"""
    m = re.search(r"href=['\"]\?s=([^&'\"]+)&t=multicast['\"]", detail_html,
                  flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r'data-s="([^"]+)"', detail_html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r'href="[^"]*[?&]s=([^"&]+)', detail_html, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def fetch_detail_data(p_token: str, session=None) -> dict:
    """IP 详情页原始响应（含 status / html），便于判断站点是否降级。"""
    query = urlencode({"p": p_token, "t": "multicast"})
    return signed_get(f"{IPTV_INDEX}?{query}", session=session)


def fetch_detail_html(p_token: str, session=None) -> str:
    return fetch_detail_data(p_token, session).get("html", "") or ""


def parse_channel_lines(channels_html: str) -> list[str]:
    lines = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", channels_html, flags=re.IGNORECASE | re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        if len(tds) < 3:
            continue
        name = _strip_html(tds[1])
        play_url = _strip_html(tds[2])
        if not name or not play_url:
            continue
        if not re.search(r"(https?://|rtp/|udp/|igmp/)", play_url, flags=re.IGNORECASE):
            continue
        lines.append(f"{name},{play_url}")
    return lines


def fetch_channel_lines_by_s(s_token: str, session=None, max_pages: int = CHANNEL_MAX_PAGES) -> list[str]:
    """分页抓取完整频道列表；一旦确认末页立即停。"""
    all_lines: list[str] = []
    seen: set[str] = set()

    for page_num in range(1, max_pages + 1):
        query = urlencode({"s": s_token, "t": "multicast", "page": page_num})
        try:
            data = signed_get(f"{IPTV_INDEX}?{query}", session=session)
        except Exception as e:
            print(f"[-] 频道列表第{page_num}页失败: {e}")
            break
        if data.get("status") != "success":
            break
        html = data.get("html", "")
        page_lines = parse_channel_lines(html)
        if not page_lines:
            break
        added = 0
        for line in page_lines:
            if line not in seen:
                seen.add(line)
                all_lines.append(line)
                added += 1
        print(f"[*] 频道列表第{page_num}页 {len(page_lines)} 条，新增 {added} 条。")
        if _should_stop_paging(html, page_num, added, len(page_lines), CHANNEL_PAGE_LIMIT):
            break
    return all_lines


def normalize_group_title(raw_type: str, province: str) -> str:
    """将站点 type 字段规范化为“省份+运营商”格式（如：浙江电信）。"""
    text = (raw_type or "").strip()
    if not text:
        return province
    if "|" in text:
        right = text.split("|")[-1].strip()
        if right:
            return right
    for carrier in CARRIERS + ("广电",):
        if carrier in text:
            return f"{province}{carrier}"
    return province


# ---------------- 抓取主流程 ----------------

def fetch_channel_lines_by_province(
    province: str,
    max_per_carrier: int = 1,
    max_pages: int = LIST_MAX_PAGES,
    channel_max_pages: int = CHANNEL_MAX_PAGES,
    max_age_hours: int = 72,
) -> tuple[dict[str, list[list[str]]], str]:
    """抓取单个省份：每个运营商最多取 N 条最新可用源，返回 分组 -> 多条源频道行。"""
    rows = fetch_region_rows_by_ajax(province, max_pages=max_pages)
    if not rows:
        return {}, "list_empty"

    # 站点时间是北京时间；GitHub Actions runner 是 UTC，统一用北京时间避免筛选偏差
    now_dt = beijing_now().replace(tzinfo=None)

    def _status_rank(status: str) -> int:
        """站点把不稳定源标成『暂时失效』，但当天更新过的通常仍可播，作为兜底。"""
        if "新上线" in status:
            return 3
        if "存活" in status:
            return 2
        if "暂时失效" in status:
            return 1
        return 0

    def _recent(row: dict) -> bool:
        dt = (_parse_site_datetime(row.get("update_time", ""))
              or _parse_site_datetime(row.get("online_time", "")))
        if not dt:
            return False
        return (now_dt - dt).total_seconds() / 3600 <= max_age_hours

    def _sort_key(row: dict):
        dt = (_parse_site_datetime(row.get("update_time", ""))
              or _parse_site_datetime(row.get("online_time", "")))
        return (_status_rank(row.get("status", "")), dt.timestamp() if dt else 0.0)

    def _pick(pool: list[dict], carrier: str, limit: int, require_recent: bool) -> list[dict]:
        picked = [r for r in pool
                  if carrier in r.get("type", "") and _status_rank(r.get("status", "")) > 0
                  and (not require_recent or _recent(r))]
        return sorted(picked, key=_sort_key, reverse=True)[:limit]

    # 站点只对「部分」IP 详情页返回节目列表链接，且会随时变化（云端与本机结果也不同）。
    # 因此把全部候选源都放进队列逐条尝试；单条偶发降级时再重试一次，直到拿到可用源。
    candidate_limit = min(len(rows), max(max_per_carrier + 3, 10))
    carrier_queue: dict[str, list[dict]] = {}
    for carrier in CARRIERS:
        pool = _pick(rows, carrier, candidate_limit, require_recent=True)
        if len(pool) < candidate_limit:
            known = {r.get("p_token") for r in pool}
            for row in _pick(rows, carrier, candidate_limit, require_recent=False):
                if row.get("p_token") not in known:
                    pool.append(row)
                    known.add(row.get("p_token"))
        carrier_queue[carrier] = pool[:candidate_limit]

    total_candidates = sum(len(v) for v in carrier_queue.values())
    if not total_candidates:  # 站点类型字段没有「电信/移动/联通」时，退化为全局按状态排序
        carrier_queue["__fallback__"] = sorted(
            [r for r in rows if _status_rank(r.get("status", "")) > 0],
            key=_sort_key, reverse=True,
        )[:candidate_limit]
        total_candidates = len(carrier_queue["__fallback__"])
    if not total_candidates:
        return {}, "no_usable_source"

    if any(_status_rank(r.get("status", "")) == 1
           for pool in carrier_queue.values() for r in pool):
        print("[!] 站点当前没有『新上线/存活』源，已退用最近更新的『暂时失效』源；"
              "频道地址可能仍可播放，建议在 App 里试播确认。")
    print(f"[*] [{province}] 每运营商最多取 {max_per_carrier} 条源，"
          f"共 {total_candidates} 条候选（失败自动换下一条）")

    group_to_sources: dict[str, list[list[str]]] = {}
    used: set[str] = set()
    detail_attempts = 0
    last_html = ""
    for pool in carrier_queue.values():
        succeeded = 0
        for cand_no, picked in enumerate(pool, 1):
            if succeeded >= max_per_carrier or detail_attempts >= 14:
                break
            token = picked.get("p_token")
            if not token or token in used:
                continue
            used.add(token)
            host = picked.get("host", "")
            group_title = normalize_group_title(picked.get("type", ""), province)
            print(f"[*] [{province}] 候选 {cand_no}/{len(pool)}: {host} / {group_title}"
                  f"（已成功 {succeeded}/{max_per_carrier}）")

            s_token = None
            for retry in range(2):  # 站点偶发返回不含节目列表的详情页，隔几秒重试一次
                detail_attempts += 1
                try:
                    data = fetch_detail_data(token)
                except Exception as e:
                    print(f"[-] IP 详情获取失败: {e}")
                    break
                html = data.get("html", "") or ""
                last_html = html
                s_token = parse_s_token(html)
                print(f"    详情响应: status={data.get('status')} html={len(html)}B "
                      f"含?s={'?s=' in html} s_token={'有' if s_token else '无'}"
                      f"{'（第2次尝试）' if retry else ''}")
                if s_token:
                    break
                if retry == 0:
                    time.sleep(3.0)
            if not s_token:
                print(f"[-] 该源没有频道列表链接: {host}，换下一条候选源")
                continue
            lines = fetch_channel_lines_by_s(s_token, max_pages=channel_max_pages)
            if not lines:
                print(f"[-] 频道列表为空: {host}，换下一条候选源")
                continue
            group_to_sources.setdefault(group_title, []).append(lines)
            succeeded += 1

    if not group_to_sources:
        snippet = re.sub(r"\s+", " ", _strip_html(last_html))[:160]
        print(f"[!] 所有候选源都未返回频道列表。最后一页内容摘要: {snippet or '(空)'}")
        print("    若持续如此，多为源站对当前出口 IP 做了降级；可稍后重跑或改用本机定时更新。")
        return {}, "channel_lines_empty"
    return group_to_sources, "ok"


# ---------------- 输出生成 ----------------

def build_tvg_logo_url(channel_name: str) -> str:
    return f"{TVG_LOGO_BASE_URL}{quote(channel_name.strip(), safe='')}.png"


def txt_to_m3u_format(txt_content: str, group_title: str) -> str:
    m3u_lines = []
    for line in txt_content.splitlines():
        line = line.strip()
        if not line or "#genre#" in line or "," not in line:
            continue
        name, url = [p.strip() for p in line.split(",", 1)]
        m3u_lines.append(
            f'#EXTINF:-1 tvg-id="{name}" tvg-logo="{build_tvg_logo_url(name)}" '
            f'group-title="{group_title}",{name}\n{url}'
        )
    return "\n".join(m3u_lines)


def build_aggregate(grouped_sources: dict[str, list[list[str]]]) -> tuple[list[tuple[str, str, str]], int]:
    """把多源频道合并成固定订阅文件的数据；按 名称+地址 去重，跳过占位垃圾频道。"""
    items: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for group, sources in grouped_sources.items():
        for lines in sources:
            for line in lines:
                if "," not in line:
                    continue
                name, url = [p.strip() for p in line.split(",", 1)]
                if not name or not url:
                    continue
                if any(kw in name for kw in SKIP_CHANNEL_KEYWORDS):
                    skipped += 1
                    continue
                key = (name, url)
                if key in seen:
                    continue
                seen.add(key)
                items.append((name, url, group))
    return items, skipped


def write_outputs(
    repo_root: str,
    txt_dir: str,
    m3u_dir: str,
    grouped_sources: dict[str, list[list[str]]],
) -> None:
    """写分文件 + 固定聚合文件，清理旧产物（只在抓取成功后调用）。"""
    os.makedirs(txt_dir, exist_ok=True)
    os.makedirs(m3u_dir, exist_ok=True)
    expected: set[str] = set()
    exported_sources = 0
    total_channels = 0

    for group_title, sources in grouped_sources.items():
        for idx, channel_lines in enumerate(sources):
            if not channel_lines:
                continue
            stem = f"{group_title}{'' if idx == 0 else idx}"
            txt_path = os.path.join(txt_dir, stem + ".txt")
            m3u_path = os.path.join(m3u_dir, stem + ".m3u")
            expected.add(txt_path)
            expected.add(m3u_path)
            txt_content = "\n".join(channel_lines)
            with open(txt_path, "w", encoding="utf-8") as f_txt:
                f_txt.write(txt_content + "\n")
            with open(m3u_path, "w", encoding="utf-8") as f_m3u:
                f_m3u.write(f'#EXTM3U x-tvg-url="{EPG_URL}"\n')
                f_m3u.write(txt_to_m3u_format(txt_content, group_title) + "\n")
            exported_sources += 1
            total_channels += len(channel_lines)
    print(f"[+] 分文件 {exported_sources} 个，共 {total_channels} 条频道。")

    # 清理旧产物（如上一轮留下的 浙江电信2.m3u / 3.m3u ...），但保留用户手放的其它文件
    removed = 0
    for out_dir in (txt_dir, m3u_dir):
        for name in os.listdir(out_dir):
            if not name.endswith((".txt", ".m3u")):
                continue
            path = os.path.join(out_dir, name)
            if path in expected or not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"[+] 已清理 {removed} 个旧的分文件（推送时会同步从仓库删除）。")

    items, skipped = build_aggregate(grouped_sources)
    m3u_lines = [f'#EXTM3U x-tvg-url="{EPG_URL}"']
    txt_lines = []
    for name, url, group in items:
        m3u_lines.append(
            f'#EXTINF:-1 tvg-id="{name}" tvg-logo="{build_tvg_logo_url(name)}" '
            f'group-title="{group}",{name}'
        )
        m3u_lines.append(url)
        txt_lines.append(f"{name},{url}")
    m3u_content = "\n".join(m3u_lines) + "\n"
    txt_content_all = "\n".join(txt_lines) + "\n"
    with open(os.path.join(repo_root, AGGREGATE_M3U), "w", encoding="utf-8", newline="\n") as f:
        f.write(m3u_content)
    with open(os.path.join(repo_root, AGGREGATE_TXT), "w", encoding="utf-8", newline="\n") as f:
        f.write(txt_content_all)
    print(f"[+] 固定聚合订阅文件 {AGGREGATE_M3U} 已生成：{len(items)} 条频道"
          f"（剔除 {skipped} 条占位垃圾频道）。")


# ---------------- GitHub / README ----------------

def git_run(args: list[str], repo_root: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo_root,
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )


_REPO_INFO_CACHE: tuple[str, str] | None = None


def repo_info(repo_root: str) -> tuple[str, str]:
    """从环境变量 / git remote 推断 owner/repo 与分支，避免 README 直链指错仓库。"""
    global _REPO_INFO_CACHE
    if _REPO_INFO_CACHE:
        return _REPO_INFO_CACHE
    env_repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if "/" in env_repo:
        owner_repo = env_repo
    else:
        owner_repo = DEFAULT_REPO
        out = git_run(["remote", "get-url", "origin"], repo_root)
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", out.stdout.strip())
        if m:
            owner_repo = f"{m.group(1)}/{m.group(2)}"
    branch = (os.environ.get("GITHUB_REF_NAME") or "").strip()
    if not branch or "/" in branch:
        branch = git_run(["symbolic-ref", "--short", "HEAD"], repo_root).stdout.strip()
    branch = branch or DEFAULT_BRANCH
    _REPO_INFO_CACHE = (owner_repo, branch)
    return _REPO_INFO_CACHE


def raw_base_url(repo_root: str) -> str:
    owner_repo, branch = repo_info(repo_root)
    return f"https://raw.githubusercontent.com/{owner_repo}/{branch}"


def subscribe_urls(repo_root: str) -> dict[str, str]:
    owner_repo, branch = repo_info(repo_root)
    raw = f"{raw_base_url(repo_root)}/{AGGREGATE_M3U}"
    return {
        "primary": (f"{SUBSCRIBE_PROXY_PREFIX}https://github.com/"
                    f"{owner_repo}/blob/{branch}/{AGGREGATE_M3U}"),
        "raw": raw,
        "proxy": PROXY_PREFIX + raw,
        "jsdelivr": f"https://cdn.jsdelivr.net/gh/{owner_repo}@{branch}/{AGGREGATE_M3U}",
    }


def _build_readme_table_rows(repo_root: str, subdir: str, ext: str, updated_at: str) -> str:
    target_dir = os.path.join(repo_root, subdir)
    names = sorted(n for n in os.listdir(target_dir) if n.endswith(ext)) if os.path.isdir(target_dir) else []
    if not names:
        return '<tr><td colspan="4">暂无文件</td></tr>'
    rows = []
    for name in names:
        raw_url = f"{raw_base_url(repo_root)}/{subdir}/{quote(name)}"
        proxy_url = f"{PROXY_PREFIX}{raw_url}"
        rows.append(
            "<tr>"
            f'<td style="white-space:nowrap;">{name}</td>'
            f'<td style="white-space:nowrap;"><a href="{proxy_url}">下载链接</a></td>'
            f'<td style="white-space:nowrap;">{updated_at}</td>'
            f'<td><code>{proxy_url}</code></td>'
            "</tr>"
        )
    return "\n".join(rows)


def _build_readme_section_table(repo_root: str, subdir: str, ext: str, updated_at: str) -> str:
    rows = _build_readme_table_rows(repo_root, subdir, ext, updated_at)
    return (
        '<table style="width:100%; table-layout:auto;">\n'
        "<colgroup>\n"
        '<col style="width: 220px;" />\n'
        '<col style="width: 120px;" />\n'
        '<col style="width: 170px;" />\n'
        "<col />\n"
        "</colgroup>\n"
        "<thead>\n<tr>\n"
        '<th style="white-space:nowrap;">文件名</th>\n'
        '<th style="white-space:nowrap;">加速链接</th>\n'
        '<th style="white-space:nowrap;">最近更新时间</th>\n'
        '<th style="white-space:nowrap;">可复制直链</th>\n'
        "</tr>\n</thead>\n<tbody>\n"
        f"{rows}\n"
        "</tbody>\n</table>"
    )


def _subscribe_block(repo_root: str) -> str:
    urls = subscribe_urls(repo_root)
    updated_at = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "<!-- SUBSCRIBE_START -->\n"
        "## 电视 App 订阅地址\n\n"
        f"- **主地址（推荐）**：`{urls['primary']}`\n"
        f"- 备用（gh-proxy.org raw 加速）：`{urls['proxy']}`\n"
        f"- 备用原始直链：`{urls['raw']}`\n"
        f"- 备用（jsDelivr CDN）：`{urls['jsdelivr']}`\n\n"
        f"本仓库的 `{AGGREGATE_M3U}` 每次更新会被覆盖，地址固定不变，App 里填一次即可。"
        f"（最近更新：{updated_at}）\n"
        "<!-- SUBSCRIBE_END -->"
    )


def update_readme_file_list(repo_root: str) -> None:
    readme_path = os.path.join(repo_root, README_FILE)
    if not os.path.exists(readme_path):
        print("[-] README.md 不存在，跳过列表更新。")
        return
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    updated_at = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    m3u_block = f"## M3U 文件列表\n\n{_build_readme_section_table(repo_root, 'm3u', '.m3u', updated_at)}\n"
    txt_block = f"## TXT 文件列表\n\n{_build_readme_section_table(repo_root, 'txt', '.txt', updated_at)}\n"

    sub_block = _subscribe_block(repo_root)
    if "<!-- SUBSCRIBE_START -->" in content and "<!-- SUBSCRIBE_END -->" in content:
        content = re.sub(
            r"<!-- SUBSCRIBE_START -->[\s\S]*?<!-- SUBSCRIBE_END -->",
            lambda _m: sub_block, content, count=1,
        )
    else:  # 老 README 没有占位时，插到“加速下载说明”之前
        content = content.replace("## 加速下载说明", sub_block + "\n\n## 加速下载说明", 1)

    content, m3u_count = re.subn(
        r"## M3U 文件列表[\s\S]*?(?=\r?\n## TXT 文件列表)",
        m3u_block.rstrip(), content, count=1,
    )
    if "## 免责声明" in content:
        content, txt_count = re.subn(
            r"## TXT 文件列表[\s\S]*?(?=\r?\n---\r?\n\r?\n## 免责声明)",
            txt_block.rstrip(), content, count=1,
        )
    else:
        content, txt_count = re.subn(
            r"## TXT 文件列表[\s\S]*$", txt_block.rstrip(), content, count=1,
        )
    if m3u_count == 0 or txt_count == 0:
        print("[-] README 结构不匹配（未找到列表区块），跳过自动更新。")
        return
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[+] README.md 订阅地址与文件列表已更新。")


def push_to_github(repo_root: str) -> bool:
    """提交并推送生成文件 + 脚本/工作流改动；显式指定 cwd，同步删除旧文件。"""
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        print("[-] 当前目录不是 git 仓库，跳过推送。")
        return False

    owner_repo, branch = repo_info(repo_root)
    if git_run(["remote", "get-url", "origin"], repo_root).returncode != 0:
        print("[-] 未配置 origin 远程，跳过推送。")
        return False
    print(f"\n[*] 同步到 GitHub: {owner_repo} / {branch}")

    paths = [p for p in TRACKED_PATHS if os.path.exists(os.path.join(repo_root, p))]
    add_run = git_run(["add", "-A", "--", *paths], repo_root)
    if add_run.returncode != 0:
        print(f"[-] git add 失败:\n{add_run.stderr.strip()}")
        return False

    if git_run(["diff", "--cached", "--quiet"], repo_root).returncode == 0:
        print("[*] 文件无变化，无需提交（仍检查是否有待推送的本地提交）。")
    else:
        # 本地没配 user.name/email 时（如 GitHub Actions）临时补齐，避免 commit 失败
        name = git_run(["config", "user.name"], repo_root).stdout.strip()
        email = git_run(["config", "user.email"], repo_root).stdout.strip()
        identity = []
        if not name:
            identity += ["-c", "user.name=iptv-bot"]
        if not email:
            identity += ["-c", "user.email=iptv-bot@users.noreply.github.com"]
        commit_msg = (f"{GITHUB_COMMIT_PREFIX} 浙江组播源 "
                      f"{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}")
        commit_run = git_run([*identity, "commit", "-m", commit_msg], repo_root)
        if commit_run.returncode != 0:
            print(f"[-] git commit 失败:\n{commit_run.stderr.strip()}")
            return False
        print(f"[+] git commit 成功: {commit_msg}")

    push_cmd = ["push", "origin", f"HEAD:refs/heads/{branch}"]
    push_run = git_run(push_cmd, repo_root)
    if push_run.returncode != 0 and re.search(r"non-fast-forward|rejected|fetch first", push_run.stderr, re.I):
        print("[*] 远端有新提交，先 pull --rebase 再重试一次...")
        pull_run = git_run(["pull", "--rebase", "--autostash", "origin", branch], repo_root)
        if pull_run.returncode != 0:
            print(f"[-] rebase 失败:\n{pull_run.stderr.strip()}")
            return False
        push_run = git_run(push_cmd, repo_root)
    if push_run.returncode != 0:
        print(f"[-] git push 失败:\n{push_run.stderr.strip()}")
        print("    请确认本机 git 凭据与网络代理正常；文件已在本地生成，可稍后手动推送。")
        return False
    print("[+] 已成功推送到 GitHub。")
    return True


# ---------------- 命令行 ----------------

def parse_args():
    ap = argparse.ArgumentParser(description="抓取浙江组播源，生成固定订阅文件并推送到本仓库。")
    ap.add_argument("--no-push", action="store_true", help="只生成本地文件，不执行 git 提交推送")
    ap.add_argument("--push", action="store_true", help="兼容旧用法；推送默认已开启")
    ap.add_argument("--dry-run", action="store_true", help="只抓取并统计，不写文件、不推送")
    ap.add_argument("--only-province", default="", help="只处理指定省份（默认只处理浙江）")
    ap.add_argument("--all-provinces", action="store_true", help="恢复全国抓取（请求量很大，不推荐）")
    ap.add_argument("--delay", type=float, default=REQUEST_MIN_DELAY,
                    help=f"相邻请求最小间隔秒数（默认 {REQUEST_MIN_DELAY}）")
    ap.add_argument("--max-per-carrier", type=int, default=1,
                    help="每个运营商最多取几条源（默认 1，越大越容易被限流）")
    ap.add_argument("--max-pages", type=int, default=LIST_MAX_PAGES,
                    help=f"服务器列表最多翻几页（默认 {LIST_MAX_PAGES}）")
    ap.add_argument("--channel-max-pages", type=int, default=CHANNEL_MAX_PAGES,
                    help=f"频道列表最多翻几页（默认 {CHANNEL_MAX_PAGES}）")
    ap.add_argument("--max-age-hours", type=int, default=72,
                    help="优先取最近 N 小时更新过的源（默认 72）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    LIMITER.base = max(0.5, args.delay)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    txt_dir = os.path.join(repo_root, "txt")
    m3u_dir = os.path.join(repo_root, "m3u")

    if args.all_provinces:
        provinces = PROVINCES
    elif args.only_province:
        provinces = [args.only_province]
    else:
        provinces = TARGET_PROVINCES

    started = time.monotonic()
    print(f"[*] 目标省份: {', '.join(provinces)} | 请求间隔: {LIMITER.base}s | "
          f"每运营商源数: {args.max_per_carrier} | dry-run: {args.dry_run}")

    all_grouped: dict[str, list[list[str]]] = {}
    for province in provinces:
        print("\n" + "=" * 50)
        print(f" 正在处理地区: {province}")
        print("=" * 50)
        grouped, status = fetch_channel_lines_by_province(
            province,
            max_per_carrier=args.max_per_carrier,
            max_pages=args.max_pages,
            channel_max_pages=args.channel_max_pages,
            max_age_hours=args.max_age_hours,
        )
        if not grouped:
            print(f"[!] [{province}] 抓取失败: {status} —— 保留原有文件，不做任何清理。")
            continue
        for group, sources in grouped.items():
            all_grouped.setdefault(group, []).extend(sources)

    if not all_grouped:
        print("[-] 本次没有抓到任何可用源，为避免清空订阅源，未改动任何文件。")
        return 1

    items, skipped = build_aggregate(all_grouped)
    total = sum(len(lines) for sources in all_grouped.values() for lines in sources)
    print(f"\n[*] 抓取统计: {total} 条原始频道 -> 聚合 {len(items)} 条"
          f"（跳过 {skipped} 条占位频道）| 请求 {LIMITER.total_requests} 次，"
          f"限流 {LIMITER.total_throttles} 次 | 耗时 {time.monotonic() - started:.1f}s")

    urls = subscribe_urls(repo_root)
    print("\n[*] 电视 App 订阅地址（地址固定，文件自动覆盖）:")
    print(f"    主地址: {urls['primary']}")
    print(f"    备用:   {urls['proxy']}")
    print(f"    直链:   {urls['raw']}")

    if args.dry_run:
        print("\n[*] dry-run 模式：未写入文件、未提交推送。")
        return 0

    write_outputs(repo_root, txt_dir, m3u_dir, all_grouped)
    update_readme_file_list(repo_root)

    if args.no_push:
        print("\n[*] 已生成全部文件（--no-push，跳过 git 推送）。")
        return 0

    ok = push_to_github(repo_root)
    if ok:
        print(f"\n[+] 流水线完成，订阅地址内容已更新：\n    {urls['primary']}")
    else:
        print("\n[!] 文件已在本地生成，但本次未推送到 GitHub（详见上方错误）。")
        print("    线上订阅仍是上一版内容；云端 Actions 会在下次定时任务自动同步。")
        print("    如需立即生效，可在网络恢复后执行：git push origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())

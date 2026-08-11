# NUC 软路由「WiFi 连上但无网络」完整排障实录

> 项目：nuc-router（NUC8i5BEH + Ubuntu 24.04，hostapd + dnsmasq + nftables + xray 透明代理 + FastAPI WebUI）
> 时间：2026-08-11（部署 + 全天排障）
> 仓库：`github.com/boochihero/nuc-router` | 本文档对应 commit 链：`d41d5d2` → `e63b1b1`

---

## 一、目标架构

```
手机/电脑 ──WiFi──> NUC(wlp0s20f3 AP, 192.168.50.1)
                        │
                        ├─ DHCP/DNS: dnsmasq (192.168.50.100-200, 网关=192.168.50.1)
                        ├─ 透明代理: nftables redirect TCP → xray(:12345)
                        │      ├─ geosite:bing / geosite:cn / geoip:cn → direct 直连
                        │      └─ 其余 → Bocchi-Japan 节点 (vless+ws+tls)
                        └─ 管理界面: WebUI (http://192.168.50.1, FastAPI + token)
```

- 硬件：NUC8i5BEH，Intel Wireless-AC 9560 (Cannon Point CNVi)，有线 eno1 接上级路由
- 软件：Ubuntu 24.04 (内核 6.8)，hostapd / dnsmasq / nftables / xray 1.8.23 / uvicorn
- 部署方式：`install.sh` 一键安装 + systemd 服务（全部开机自启）

---

## 二、部署阶段踩的坑（install.sh 系列）

这些 bug 让 install.sh 永远跑不到底，按出现顺序：

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | Step 1 就退出：`sudo: a terminal is required` | `sudo -v` 在 NOPASSWD + 无 tty 环境下仍要求密码 | 改 `sudo -n true` 做权限检查 |
| 2 | `cp: cannot create '/etc/nftables.d/router.nft': No such file or directory` | `needs_cp()` 没建目标目录（`/etc/nftables.d`、`/etc/xray` 默认不存在） | `needs_cp` 先 `mkdir -p $(dirname $2)` |
| 3 | Step 6 WebUI：`Permission denied: '/opt/router-webui/.venv'` | venv 创建/ pip install 没加 sudo（目录是 root 的） | 加 sudo（服务本来就以 root 跑） |
| 4 | `nft: specify 'tproxy ip' or 'tproxy ip6' in inet table` | inet 双栈表里 `tproxy to` 必须指定协议族 | 写 `tproxy ip to ...` |
| 5 | `mkdir: cannot create directory '/etc/router-backups': Permission denied` | backup 脚本没 sudo | mkdir/cp 加 sudo |
| 6 | hostapd：`Hardware does not support configured channel 149` | **Intel 9560 在 CN regulatory 下所有 5GHz 信道 `no IR`**（硬件/OTP 层面锁死，无线-regdb 已装也无解） | 改 2.4GHz（hw_mode=g, ch6），SSID 改 `NUC-Router` |
| 7 | router-ap 反复 `Failed with result 'timeout'` | `Type=forking` 但 hostapd 前台运行（-B 才 fork），systemd 等不到 fork 超时杀掉 AP | 改 `Type=simple`（dnsmasq 同理） |
| 8 | 客户端拿不到网关 IP | 没人给 AP 接口配 `192.168.50.1/24`（dnsmasq 通告它是网关，但接口上没这个地址） | router-ap.service 加 `ExecStartPost` 配 IP（`ip addr replace` 幂等） |
| 9 | xray 起不来：`invalid field rule > neither outboundTag nor balancerTag` | 模板 routing 有非法字段 `targetTag` | 模板精简为 direct/blocked 占位，真实节点走 WebUI 订阅导入 |

> 部署教训：install.sh 从"看起来能跑"到"真能跑"，每步都要在目标机器上实测。检查顺序：sudo 方式 → 目录创建 → 权限 → 协议族 → systemd Type 匹配 → 接口 IP → 配置模板合法性。

---

## 三、核心排障主线：「WiFi 连上但网页不通」

这是今天的主战场。现象：设备能连上 `NUC-Router`、能拿到 IP，但 ping 网关不通 / 网页打不开 / 周期性断开重连。逐层剥开共 6 个独立问题：

### 问题 1：DHCP 请求被透明代理劫持

**现象**：设备连上后 16-40 秒必断，循环重连；dnsmasq 无 DHCP 记录；xray 日志却出现 `0.0.0.0:68 accepted udp:255.255.255.255:67`。

**诊断**：`nft list chain ... prerouting_proxy` 显示 tproxy 规则只有 `tcp dport {22,8080} return`，**UDP 的 67/68 没排除** → DHCP DISCOVER（目标 255.255.255.255:67）被 tproxy 转发到 xray → 请求石沉大海 → 客户端拿不到 IP → 系统判死断开。

**修复**：
```
udp dport { 53, 67, 68, 5353 } return   # DNS/DHCP/mDNS 不代理
```

### 问题 2：dnsmasq 上游 DNS 在中国不可达

**现象**：客户端能解析（或解析超时），体验差。

**根因**：`server=1.1.1.1 / 8.8.8.8`——中国网络直连这两个 IP 的 UDP 53 基本被墙/超时。

**修复**：上游改国内可达 DNS，国外兜底：
```
server=223.5.5.5      # 阿里
server=119.29.29.29   # 腾讯
server=1.1.1.1        # 兜底
server=8.8.8.8
```
> 注意：客户端 DNS 走 dnsmasq（192.168.50.1），国外域名解析结果即使被污染也没关系——xray 开了 **SNI 嗅探（sniffing）**，从 TLS/HTTP 头恢复真实域名按域名分流，代理端重新解析，天然绕开 DNS 污染。

### 问题 3：TPROXY 缺少 ip rule / 路由表配套

**现象**：所有 TCP SYN 无响应（抓包可见大量重试），xray 无日志。

**根因**：TPROXY 标记的包需要 `ip rule fwmark 1 lookup 100` + `ip route add local 0.0.0.0/0 dev lo table 100` 才能被引导到本机 xray socket。缺失时包被黑洞。

**修复**（当时方案，后来被 redirect 替代，见问题 6）：
```
ip rule add fwmark 1 lookup 100
ip route add local 0.0.0.0/0 dev lo table 100
```
并写入 `router-firewall.service` 的 `ExecStartPost` 持久化。

### 问题 4（最大的坑）：watchdog 自动回滚抹掉一切

**现象**：刚修好的配置"神秘消失"——nft 的 udp 排除没了、xray 节点没了、路由规则变回模板。反复出现，让人以为没修好。

**诊断**：`journalctl -u router-watchdog.service` 发现：
```
[WATCHDOG] CRITICAL: 2 consecutive failures, triggering auto-rollback...
[WATCHDOG] Rolling back to backup: 20260811_160030
  restored: /etc/nftables.d/router.nft   ← 旧版！
  restored: /etc/xray/client.json        ← 节点被抹！
```

**根因（双重）**：
1. watchdog 的 `check_internet()` 用 `curl https://1.1.1.1`（**中国网络必失败**）→ 每 5 分钟误判一次"无互联网"
2. 连续 2 次失败触发 **auto-rollback**，从陈旧备份恢复配置——把用户刚导入的订阅节点、新修的 nft 规则全抹掉，比故障本身还危险

**修复**：
```bash
# check_internet 改用国内可达端点
curl --max-time 8 --interface eno1 "https://www.baidu.com" && return 0
curl --max-time 8 --interface eno1 "http://223.5.5.5" && return 0

# 禁用自动回滚（只告警，回滚必须人工触发）
rollback_guard() {
    log "CRITICAL: ... AUTO-ROLLBACK DISABLED (would restore stale configs). Manual: $ROLLBACK_SCRIPT"
}
```

> **核心教训：自动恢复机制可能比故障本身更危险。** 回滚陈旧配置 = 抹掉用户数据。检测端点必须用目标网络可达的地址。

### 问题 5：客户端周期性断开（16-40 秒循环）

**现象**：hostapd 日志 `AP-STA-CONNECTED` → 16-40s → `AP-STA-DISCONNECTED`，循环。

**本质**：这是问题 1/3 的**结果**而非独立故障——客户端连上 → DHCP/上网全被黑洞 → 系统网络检测失败 → 断开重连。问题 1/3/4 修复后此现象自然消失（当前设备已稳定在线数小时）。

**排查技巧**：
- `journalctl -u router-ap -n 20 | grep -E 'CONNECTED|DISCONNECTED'` 看断连节奏
- `iw dev wlp0s20f3 station dump` 看实时客户端（注意手机随机 MAC 会变，别拿旧 MAC 对不上）
- hostapd `-dd` debug 日志会被周围 AP 的 probe 刷屏，慎用；管理帧抓包在 AP 接口不可用（tcpdump 需 monitor 模式）

### 问题 6（终极问题）：TPROXY 命中但 socket 匹配失败 → 流量黑洞

**现象**：nft 计数器显示 `tcp counter packets 468`（规则命中！），但 xray 一个连接都没收到，浏览器全部超时。

**诊断**：tproxy 表达式会查找监听 12345 且设置 `IP_TRANSPARENT` 的 socket；**xray 的透明 socket 匹配在这套环境不生效** → 找不到 socket → 包被静默丢弃（不走 forward、不进 xray，纯黑洞）。国内国外 IP 全不通（DNS 通、TCP 全灭，因为 DNS 53 被排除直连）。

**修复：tproxy → redirect 方案**（一劳永逸）：
```nft
# nat 表 prerouting（redirect 是 NAT 操作，必须在 nat 表）
chain prerouting_redirect {
    type nat hook prerouting priority dstnat; policy accept;
    ip daddr { 127.0.0.0/8, 192.168.50.0/24 } return
    iifname != "wlp0s20f3" return
    tcp dport { 22, 80 } return
    udp dport { 53, 67, 68, 5353 } return
    meta l4proto tcp redirect to :12345    # TCP 重定向进 xray
}
```
```jsonc
// xray client.json: tproxy 模式改 redirect 模式
"streamSettings": { "sockopt": { "tproxy": "redirect", "mark": 1 } }
```

**为什么 redirect 更可靠**：
- redirect 是纯 NAT 重定向（DNAT 到本机端口），**不需要 IP_TRANSPARENT / 透明 socket**，xray 普通监听就能收到
- xray 通过 `getsockopt(ORIGINAL_DST)` 恢复真实目标地址，分流逻辑不变
- 不需要 `ip rule` / `table 100`，配置更简单
- 代价：UDP 透明代理弱（redirect 对 UDP 支持有限），本方案 **UDP 一律直连**（DNS 已本地化，网页浏览无影响）

**验证**（xray 日志出现分流结果 = 链路打通）：
```
21:53:15 192.168.50.105:37728 accepted tcp:104.16.80.73:443 [tproxy -> Bocchi-Japan]   # 国外走代理
21:53:15 192.168.50.105:39732 accepted tcp:106.38.187.41:443 [tproxy -> direct]        # 国内直连
```

---

## 四、衍生问题：Bing 重定向循环（ERR_TOO_MANY_REDIRECTS）

**现象**：只有 bing.com 打不开，浏览器报 `ERR_TOO_MANY_REDIRECTS`，其他网站正常。

**根因**：Bing 走代理 → 微软服务器看到出口 IP（日本）→ 302 重定向到区域版 → 重定向请求又走代理 → 无限循环。经典"分区域重定向 × 透明代理"冲突。

**修复**：Bing 域名强制直连（国内 Bing 可用，直连后只跳一次到 cn.bing.com）：
```json
{ "type": "field", "inboundTag": ["tproxy"], "domain": ["geosite:bing"], "outboundTag": "direct" }
```
放 routing 规则最前（domain 规则按顺序匹配，先于默认代理规则）。

---

## 五、最终配置速查

### nftables（/etc/nftables.d/router.nft）
```
table inet router {
  chain forward        { filter hook forward;   policy accept; eno1↔wlp0s20f3 放行 }
  chain postrouting    { nat hook postrouting;  oifname "eno1" masquerade }
  chain prerouting_redirect { nat hook prerouting priority dstnat;
    ip daddr {127.0.0.0/8, 192.168.50.0/24} return
    iifname != "wlp0s20f3" return
    tcp dport {22, 80} return
    udp dport {53, 67, 68, 5353} return
    meta l4proto tcp redirect to :12345 }
}
```

### xray（/etc/xray/client.json 核心）
- 入站：dokodemo-door :12345，`followRedirect: true`，`sniffing: {http, tls}`，`sockopt.tproxy = "redirect"`
- 出站：Bocchi-Japan（订阅导入的 vless）+ direct（freedom）+ blocked（blackhole）
- 分流：`geosite:bing` → direct → `geosite:cn` → direct → `geoip:cn`+`geoip:private` → direct → 默认 → 节点

### 服务清单（全部开机自启）
| 服务 | 作用 | 关键点 |
|------|------|--------|
| router-firewall | 加载 nft 规则 | Type=oneshot |
| router-ap | hostapd AP | Type=simple（hostapd 前台） |
| router-dns | dnsmasq DHCP+DNS | Type=simple（--keep-in-foreground） |
| router-xray | 透明代理 | Type=simple，CAP_NET_ADMIN |
| router-webui | 管理面板 :80 | token 在 /etc/router-webui/secret |
| router-watchdog.timer | 健康巡检 | 国内端点检测，无自动回滚 |

---

## 六、可复用的排障方法论

1. **分层定位**：二层（认证/关联）→ DHCP → DNS → 数据面（TCP 通不通）→ 代理链路。用日志/抓包确认"卡在哪一层"，别跳层猜。
2. **nft 计数器是最快的 tproxy 诊断**：规则加 `counter`，命中数 vs xray 日志对比，立刻区分"没匹配规则"和"匹配了但没交付"。
3. **抓包看方向**：`tcpdump -i wlp0s20f3 host <client>` 看 SYN 有没有出去、SYN-ACK 有没有回来；DNS 通 + TCP 全灭 = 代理层问题。
4. **先禁可疑自动化**：watchdog/自动回滚/自动恢复类机制，排障期间先停掉，否则它会"帮倒忙"把现场破坏。
5. **持久化纪律**：任何手动修复（ip rule、iptables、sysctl）必须同步进 systemd unit / install.sh，否则重启即丢；NUC 上 `/etc/` 文件与 git 仓库要保持同步（本次 watchdog 回滚就是旧文件覆盖新文件的教训）。
6. **分步执行**：NUC 网络不稳定时，hako/MCP 命令要短、分步、幂等；超时不重发，先查状态。

---

## 七、关键 commit 索引（复盘用）

```
d41d5d2  install.sh: xray 国内镜像多路 fallback
0e3b1de  sudo 检查改 sudo -n true
eac0980  needs_cp 补 mkdir -p
280c88c  WebUI venv 加 sudo
88a5da0  nft tproxy ip 协议族 + backup sudo
2b7dfe3  hostapd 改 2.4GHz（5GHz no IR）
63e747c  router-ap Type=simple
98d3904  AP 接口配 192.168.50.1/24
97b75db  xray 模板精简（direct/blocked）
a07d04b  activate_node 用 outboundTag + 校验
c9d02c9  xray reload 改 restart
bdc306d  智能分流（geosite:cn/geoip:cn + sniffing + 国内 DNS）
4544471  nft 排除 UDP 53/67/68（DHCP 修复）
7174d92  ip rule fwmark + table 100（后被 redirect 取代）
17aaa18  nft 排除补 5353
72a76b0  watchdog 修复（国内端点 + 禁用自动回滚）
55bcd66  tproxy 换 redirect 方案（终极修复）
1d662fa  WebUI 改 80 端口
e63b1b1  bing 域名直连
```

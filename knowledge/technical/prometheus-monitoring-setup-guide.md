# Prometheus 监控方案完整配置指南

> 场景：公司使用 k3s 和 EKS 两个 Kubernetes 集群，从零搭建 Prometheus 监控体系
> 目标：学会部署、采集、告警、可视化，能自己动手配起来

---

## 1. 先搞懂 Prometheus 是怎么工作的

### 1.1 核心架构

```
┌─────────────┐   拉取(HTTP)   ┌──────────────┐
│  应用/服务    │ ────────────▶ │              │
│  /metrics   │               │  Prometheus  │─── 存储时序数据 ───▶ TSDB
└─────────────┘               │   Server     │
┌─────────────┐               │              │─── 告警 ──────────▶ Alertmanager ──▶ 飞书/钉钉/邮件
│  node_      │ ────────────▶ │              │
│  exporter   │               └──────────────┘
└─────────────┘                     │
┌─────────────┐                     ▼
│ kube-state  │               ┌──────────────┐
│ -metrics    │               │   Grafana    │（可视化，查 PromQL）
└─────────────┘               └──────────────┘
```

**关键设计思想：拉取模型（Pull）**
- Prometheus 主动去"拉"各目标暴露的指标，而不是被采集方"推"过来
- 好处：被采集方不需要关心谁在收集，挂了 Prometheus 也能知道（指标消失本身就是告警信号）
- 例外：短命任务（cron job、批处理）用 Pushgateway 临时推送

### 1.2 四个关键概念

| 概念 | 说明 | 例子 |
|------|------|------|
| **指标（Metric）** | 一个可测量的量，带名字 | `http_requests_total` |
| **标签（Label）** | 指标的维度，用于区分 | `method="GET"`, `pod="api-abc123"` |
| **样本（Sample）** | 某个时刻的数值 | `http_requests_total{method="GET"} 1024` |
| **时序（Time Series）** | 同一组标签的指标随时间变化 | 每 15s 一个点，存 N 天 |

### 1.3 指标类型（写代码埋点时会遇到）

- **Counter**：只增不减的计数器（请求总数、错误总数）
- **Gauge**：可增可减的瞬时值（当前 CPU 使用率、在线人数）
- **Histogram**：直方图，用于延迟/耗时分布（p50/p95/p99 就是从这算的）
- **Summary**：类似 Histogram，客户端算好分位数

### 1.4 部署方式选择

| 方式 | 适合场景 |
|------|----------|
| **kube-prometheus-stack（Helm Chart）** ⭐ | 最推荐，K8s 监控全家桶：Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics + 默认告警规则，一个 Helm 搞定 |
| 官方 prometheus-operator | 只装 operator，自己拼装，灵活但麻烦 |
| 单机二进制部署 | 不推荐在 K8s 里用，除非监控独立主机 |

**本指南采用 kube-prometheus-stack。**

---

## 2. 部署前准备

### 2.1 资源需求评估（每个集群）

kube-prometheus-stack 默认配置大概需要：

| 组件 | CPU | 内存 | 存储 |
|------|-----|------|------|
| Prometheus | 1-2 核 | 2-4 Gi | 按保留天数算，一般 50-200 Gi |
| Grafana | 0.5 核 | 512 Mi | 20 Gi（可选） |
| Alertmanager | 0.1 核 | 256 Mi | 无 |
| node-exporter | 0.1 核/节点 | 64 Mi/节点 | 无 |
| kube-state-metrics | 0.2 核 | 256 Mi | 无 |

> ⚠️ k3s 如果是边缘小机器（2 核 4G），把 Grafana 存储关掉、告警规则精简、采集间隔拉长（30s→60s），能压到 1 核 2G 以内。

### 2.2 版本匹配

- Helm 3（k3s 和 EKS 都自带/推荐）
- kube-prometheus-stack 最新稳定版（`helm search repo kube-prometheus-stack` 查看）
- **Chart 版本和 K8s 版本要兼容**，装之前看 Chart 的 README 里的兼容性表格
- 不兼容的典型症状：CRD 缺失报错、operator 起不来

### 2.3 网络前置条件

- EKS：Worker 节点安全组要放行 NodePort 或配好 LoadBalancer（后面 Grafana 访问要用）
- k3s：默认 Traefik ingress，直接配 Ingress 就行
- 如果集群有网络策略（NetworkPolicy），放行监控命名空间的流量

---

## 3. 部署 kube-prometheus-stack（详细步骤）

### 3.1 添加 Helm 仓库

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

### 3.2 创建命名空间

```bash
kubectl create namespace monitoring
```

### 3.3 准备 values.yaml

> 这是整个配置的核心。先给一份**最小可用**的，后面按需加。

```yaml
# values.yaml
# ============ 全局配置 ============
global:
  scrapeInterval: 30s        # 采集间隔，边缘环境可以 60s
  evaluationInterval: 30s    # 告警规则评估间隔

# ============ Prometheus 本体 ============
prometheus:
  prometheusSpec:
    storageSpec:             # 持久化存储（重要！不然重启数据全丢）
      volumeClaimTemplate:
        spec:
          storageClassName: standard   # EKS 用 gp2/gp3，k3s 用 local-path
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi
    retention: 15d           # 数据保留 15 天
    resources:               # 资源限制（按需调整）
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 4Gi

# ============ Grafana ============
grafana:
  adminPassword: "换成强密码"    # 默认 admin/admin，必须改！
  ingress:                     # 用 Ingress 暴露（k3s 推荐）
    enabled: true
    ingressClassName: traefik
    hosts: ["grafana.example.com"]
  # EKS 上不想配 Ingress 就用 LoadBalancer：
  # service:
  #   type: LoadBalancer

# ============ Alertmanager ============
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h      # 同一告警 4 小时重复提醒一次，别被刷屏
      receiver: 'default'
    receivers:
      - name: 'default'
        webhook_configs:
          - url: 'https://open.feishu.cn/open-apis/bot/v2/hook/你的飞书机器人webhook'
            send_resolved: true
```

### 3.4 安装

```bash
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml \
  --version <chart版本号>
```

### 3.5 验证安装

```bash
# 看 Pod 是否都 Running
kubectl get pods -n monitoring

# 看 CRD 是否就绪
kubectl get crd | grep monitoring

# 端口转发试访问 Grafana（临时）
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# 浏览器打开 http://localhost:3000，admin + 你设的密码
```

**装完你就已经拥有**：
- Prometheus（采集 + 存储 + 查询）
- Grafana（可视化，自带 Kubernetes 仪表盘）
- Alertmanager（告警分发）
- node-exporter（节点指标）
- kube-state-metrics（集群对象状态）
- 一套开箱即用的告警规则

---

## 4. 确认采集目标（Targets）

Prometheus 界面确认采集是否正常：

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
# 打开 http://localhost:9090/targets
```

应该看到这些 target 组，状态都是 UP：
- `serviceMonitor/.../kube-state-metrics` — 集群对象
- `serviceMonitor/.../node-exporter` — 节点（每个节点一个）
- `serviceMonitor/.../kubelet` — kubelet/cAdvisor（容器指标）
- `serviceMonitor/.../apiserver` — API server（EKS 可能部分不可用）
- `serviceMonitor/.../prometheus` / `alertmanager` / `grafana` — 自身

**排查技巧**：
- 状态 DOWN：`kubectl logs <exporter-pod> -n monitoring` 看日志
- 401/403：ServiceAccount/RBAC 权限问题
- 连接拒绝：NetworkPolicy 或安全组

---

## 5. 自定义采集：监控你自己的应用

应用要进监控，必须满足：
1. 应用暴露 HTTP 端点（通常是 `/metrics`），返回 Prometheus 格式文本
2. 在 K8s 里声明 ServiceMonitor（告诉 Prometheus 去拉谁）

### 5.1 应用侧：暴露指标

以 Python/Flask 为例：

```python
from prometheus_client import start_http_server, Counter
import random, time

REQUESTS = Counter('http_requests_total', 'Total HTTP requests', ['method', 'path'])

while True:
    REQUESTS.labels(method='GET', path='/api/orders').inc()
    time.sleep(random.uniform(0.1, 1))
```

部署后验证：`curl http://<pod-ip>:8000/metrics` 能看到 `http_requests_total{...}`

其他语言都有官方 client library：
- Go: `prometheus/client_golang`
- Java: `micrometer` / `prometheus/client_java`
- Node.js: `prom-client`
- 不想改代码？用 **exporter**：mysqld_exporter、redis_exporter、nginx_exporter、blackbox_exporter…

### 5.2 声明 ServiceMonitor

```yaml
# service-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: monitoring    # 一般放 monitoring 或应用所在 ns
spec:
  selector:
    matchLabels:
      app: my-app           # 匹配应用的 Service 标签
  endpoints:
    - port: metrics         # Service 里端口名
      path: /metrics
      interval: 30s
```

应用需要有对应 Service：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  labels:
    app: my-app            # 和 ServiceMonitor 的 selector 对上
spec:
  selector:
    app: my-app
  ports:
    - name: metrics
      port: 8000
      targetPort: 8000
```

```bash
kubectl apply -f service-monitor.yaml
# 过一会去 /targets 看，应该出现新目标
```

> 💡 **PodMonitor** 和 ServiceMonitor 几乎一样，只是直接匹配 Pod 而非 Service。Service 都没建的应用用 PodMonitor。

---

## 6. 告警配置（重点）

### 6.1 告警链路

```
Prometheus 规则评估 ──触发──▶ Alertmanager ──路由──▶ 飞书/钉钉/邮件/企业微信
     (PrometheusRule)              (AlertmanagerConfig)
```

### 6.2 写告警规则：PrometheusRule

kube-prometheus-stack 自带一套 K8s 告警规则，自己加的话：

```yaml
# custom-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: custom-alerts
  namespace: monitoring
spec:
  groups:
    - name: app-alerts
      rules:
        # 服务挂了（5 分钟没有指标）
        - alert: AppDown
          expr: up{job="my-app"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "应用 {{ $labels.job }} 挂了"
            description: "{{ $labels.job }} 已无指标超过 5 分钟"

        # 5xx 错误率超过 5%
        - alert: HighErrorRate
          expr: |
            sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
            /
            sum(rate(http_requests_total[5m])) by (job) > 0.05
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "{{ $labels.job }} 5xx 错误率过高"
```

```bash
kubectl apply -f custom-alerts.yaml
```

### 6.3 常用 K8s 告警规则模板（直接抄）

```yaml
spec:
  groups:
    - name: kubernetes-health
      rules:
        # 节点不可用
        - alert: NodeNotReady
          expr: kube_node_status_condition{condition="Ready",status="true"} == 0
          for: 5m
          labels: {severity: critical}

        # 节点磁盘快满
        - alert: NodeDiskPressure
          expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
          for: 5m
          labels: {severity: warning}

        # 部署副本数不符
        - alert: DeploymentReplicasMismatch
          expr: kube_deployment_status_replicas_available != kube_deployment_spec_replicas
          for: 10m
          labels: {severity: critical}

        # Pod 频繁重启
        - alert: PodFrequentRestart
          expr: increase(kube_pod_container_status_restarts_total[1h]) > 5
          for: 10m
          labels: {severity: warning}

        # PVC 容量超过 85%
        - alert: PVCAlmostFull
          expr: kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85
          for: 10m
          labels: {severity: warning}

        # 容器内存使用率过高
        - alert: ContainerMemoryHigh
          expr: |
            sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (pod, container)
            / sum(container_spec_cpu_quota{container!=""}/container_spec_cpu_period{container!=""}) by (pod, container) > 0.85
          for: 10m
          labels: {severity: warning}
```

### 6.4 Alertmanager 路由配置

在 values.yaml 里改 `alertmanager.config`：

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
    route:
      receiver: 'default'
      group_by: ['alertname']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:                        # 按严重级别分流
        - matchers: ["severity = critical"]
          receiver: 'critical'
          continue: true
    receivers:
      - name: 'default'
        webhook_configs:
          - url: 'https://open.feishu.cn/open-apis/bot/v2/hook/<webhook>'
            send_resolved: true
      - name: 'critical'
        webhook_configs:
          - url: 'https://open.feishu.cn/open-apis/bot/v2/hook/<另一个webhook>'
            send_resolved: true
```

> 💡 飞书自定义机器人：飞书群 → 设置 → 群机器人 → 添加"自定义机器人" → 拿到 webhook URL。注意可以设置关键词或签名校验，Alertmanager 发的消息里要带对应关键词。

改完配置重启生效：

```bash
kubectl rollout restart statefulset/alertmanager -n monitoring
```

---

## 7. Grafana 可视化

### 7.1 自带仪表盘

kube-prometheus-stack 装完自带一批仪表盘（左侧 Dashboards 里能看到）：
- **Kubernetes / Compute Resources / Cluster** — 集群总览
- **Kubernetes / Compute Resources / Namespace (Pods)** — 按命名空间看
- **Kubernetes / Nodes** — 节点详情
- **Kubernetes / Kubelet** — 容器运行时

### 7.2 官方仪表盘市场（grafana.com/dashboards）

想要更多模板，去官网按 ID 导入（比如 Kubernetes 集群监控 315、Node Exporter Full 1860）：
1. Grafana → Dashboards → Import
2. 输入模板 ID
3. 数据源选 Prometheus

### 7.3 常用 PromQL（自己在 Explore 里玩）

```promql
# 节点 CPU 使用率
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# 节点内存使用率
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100

# 某 Pod 的 CPU 使用（核数）
sum(rate(container_cpu_usage_seconds_total{pod="my-app-xxx"}[5m]))

# 集群里所有 Pod 的 CPU 请求 vs 实际使用
sum(rate(container_cpu_usage_seconds_total{container!=""}[5m]))
sum(kube_pod_container_resource_requests{resource="cpu"})

# HTTP 请求 QPS
sum(rate(http_requests_total[5m])) by (job)

# 延迟 p95
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# 磁盘剩余（按 PVC）
kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes
```

### 7.4 Grafana 数据源

通常装完自动配好 Prometheus 数据源。手动配的话：
- URL: `http://kube-prometheus-stack-prometheus.monitoring.svc:9090`
- 类型: Prometheus
- 无需认证（集群内）

---

## 8. EKS 与 k3s 的差异化配置

### 8.1 EKS 特有

```yaml
# EKS 补充 values
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3        # AWS 用 gp3，别用 standard

grafana:
  service:
    type: LoadBalancer                 # EKS 上简单粗暴的方式
  # 或者用 ALB Ingress Controller + ingressClassName: alb

# EKS 控制平面监控（AWS 托管，Prometheus 采不到）：
# 1. 控制平面指标走 CloudWatch → CloudWatch exporter 拉进 Prometheus
# 2. 或直接用 Amazon Managed Prometheus (AMP)
# 3. 关键指标：API server 可用性、etcd 健康，AWS 控制台能看到
```

EKS 注意事项：
- **APIServer 指标**：EKS 控制平面不暴露 kube-scheduler/etcd/controller-manager 的 metrics，kube-prometheus-stack 里 apiserver 的 ServiceMonitor 可能部分工作，正常现象
- **托管节点组**：node-exporter 用 DaemonSet 照常部署，没问题
- 建议加装 `cloudwatch-exporter` 或 `prometheus-cloudwatch-exporter` 把 EBS、ELB、RDS 的 AWS 指标拉进来

### 8.2 k3s 特有

```yaml
# k3s 精简配置（边缘/小机器）
global:
  scrapeInterval: 60s          # 拉长间隔，省资源

prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path    # k3s 默认存储
    retention: 7d                        # 缩短保留期
    resources:
      requests: {cpu: 250m, memory: 1Gi}
      limits: {cpu: 1000m, memory: 2Gi}
    # 关掉不需要的组件（如果不想监控控制平面）
    # disablePrometheusOperatorPodSecurityPolicy: true

grafana:
  persistence:
    enabled: false             # 小机器就别持久化 Grafana 了
  ingress:
    enabled: true
    ingressClassName: traefik
    hosts: ["grafana.example.com"]

# 控制平面监控：k3s 是自管集群，能采到！
# 确认 kubelet 的 ServiceMonitor 正常即可，etcd 如果是以嵌入式跑在 k3s 进程里，
# 需要在 k3s 启动参数加 --etcd-expose-metrics 才能采到 etcd 指标
```

k3s 注意事项：
- **默认存储 local-path**：PVC 绑定在节点本地，数据不跨节点，节点坏了数据可能丢（可接受就先用）
- **etcd 指标**：嵌入式 etcd 默认不暴露，需要 `k3s server --etcd-expose-metrics`（多节点 HA 模式）
- **Traefik**：默认 ingress，用 `ingressClassName: traefik`
- 如果 k3s 版本老，注意 kube-prometheus-stack 的 K8s 版本兼容性

---

## 9. 存储与数据保留

### 9.1 数据保留策略

- `retention: 15d` 是全局保留；可以按指标细分：
  ```yaml
  prometheus:
    prometheusSpec:
      retention: 15d
      # retentionSize: 100GB   # 或者按容量限制，满了删最老的
  ```
- 高频指标（如容器级）数据量大，如果磁盘紧张，考虑**降低采样精度**（Recording Rule 聚合）或用 **Thanos** 做长期存储（对象存储）

### 9.2 数据量估算

经验值：一个 10 节点集群，默认配置，约 **1-3 GB/天**。
- 100Gi 存储 ≈ 30-90 天
- 监控的 ServiceMonitor 越多、采集间隔越短，数据越大

### 9.3 备份

Prometheus 数据一般不备份（丢了重新积累），但**告警规则、仪表盘要备份**：
- Grafana 仪表盘：Grafana → 导出 JSON，或配 provision 目录存 git
- PrometheusRule / ServiceMonitor：全部写成 yaml 存 git（Infrastructure as Code）

---

## 10. 安全加固（生产必做）

- ✅ Grafana admin 密码必改（或接 LDAP/OAuth）
- ✅ Alertmanager 的 webhook URL 用签名校验（飞书支持加签）
- ✅ Prometheus 不要暴露公网，用 Ingress + Basic Auth 或 VPN
- ✅ 用 NetworkPolicy 限制谁可以访问监控命名空间
- ✅ 升级时先备份 values.yaml

---

## 11. 常见坑排查清单

| 症状 | 原因 | 解法 |
|------|------|------|
| Pod 一直 CrashLoopBackOff | values 配置语法错 | `helm get values` 检查，看 operator 日志 |
| Targets 里 apiserver 401 | RBAC 权限 | 检查 ClusterRoleBinding（重装 chart 一般自动好） |
| node-exporter 起不来 | 节点有污点 | 给 DaemonSet 加 tolerations |
| Grafana 访问不了 | Service/Ingress 配置 | `kubectl port-forward` 先验证后端通不通 |
| 告警不发 | webhook 没带关键词 | 飞书机器人设置关键词，消息里加上 |
| 数据重启就丢 | 没配 storageSpec | 补 storageSpec，重新 upgrade |
| 磁盘暴涨 | 指标太多/采集太频繁 | 拉长 scrapeInterval，降 retention，加 recording rule |
| EKS 上控制平面监控为空 | 托管集群特性 | 正常，用 CloudWatch 补 |
| k3s etcd 没指标 | 嵌入式 etcd 未暴露 | k3s 加 `--etcd-expose-metrics` |

---

## 12. 快速上手清单（TL;DR）

```bash
# 1. 加仓库
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 2. 建命名空间
kubectl create ns monitoring

# 3. 写 values.yaml（改存储类、密码、告警接收人）

# 4. 安装
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f values.yaml

# 5. 验证
kubectl get pods -n monitoring
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# 打开 localhost:3000 → 看自带仪表盘

# 6. 加自己的应用监控
# 写 ServiceMonitor + 应用暴露 /metrics

# 7. 加告警
# 写 PrometheusRule + 配 Alertmanager webhook（飞书）
```

---

## 参考

- 官方文档：https://prometheus.io/docs/
- kube-prometheus-stack：https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack
- Grafana 仪表盘市场：https://grafana.com/grafana/dashboards/
- PromQL 教程：https://prometheus.io/docs/prometheus/latest/querying/basics/

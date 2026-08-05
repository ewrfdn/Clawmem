# Kubernetes 入门指南：从 Docker 容器到 Pod、Service 与 Namespace

> 面向读者：已经会使用 Docker 镜像和容器，希望系统理解 Kubernetes（K8s）基础概念并完成第一次部署。
> 本文不重复讲解镜像、容器、Dockerfile 等 Docker 基础。

## 1. Kubernetes 解决什么问题

单机运行少量容器时，Docker 已经足够。但当容器数量增多并分布在多台机器上，会出现新的问题：

- 容器应该调度到哪台机器？
- 容器崩溃后谁负责重启？
- 如何水平扩容多个副本？
- 容器 IP 经常变化，其他服务如何稳定访问它？
- 如何滚动升级并在失败时回滚？
- 如何管理配置、密钥、存储和资源限制？

Kubernetes 是一个**容器编排系统**。你向它声明期望状态，例如“运行 3 个 Nginx 副本”，控制器会持续尝试让实际状态符合期望状态。

这是一种声明式思维：

```text
编写 YAML 描述期望状态
        ↓
kubectl 提交给 API Server
        ↓
控制器、调度器持续协调
        ↓
集群实际状态逐渐接近期望状态
```

## 2. 集群的基本组成

一个 Kubernetes 集群由控制平面和工作节点组成。

### 2.1 控制平面（Control Plane）

| 组件 | 作用 |
|---|---|
| API Server | 集群统一入口，`kubectl` 和其他组件都通过它操作资源 |
| etcd | 保存集群状态的键值数据库 |
| Scheduler | 为尚未分配节点的 Pod 选择合适的工作节点 |
| Controller Manager | 运行各种控制器，持续协调实际状态与期望状态 |

### 2.2 工作节点（Node）

| 组件 | 作用 |
|---|---|
| kubelet | 节点代理，负责确保 Pod 中的容器按要求运行 |
| Container Runtime | 真正运行容器，常见实现是 containerd、CRI-O |
| kube-proxy | 实现 Service 相关的节点网络规则；部分集群会由 eBPF 方案替代 |

可以先记住这条链路：

```text
kubectl → API Server → Scheduler 选择 Node → kubelet 启动 Pod
```

## 3. 核心对象与关系

最常见的对象关系如下：

```text
Namespace
└── Deployment
    └── ReplicaSet
        ├── Pod（一个或多个容器）
        ├── Pod
        └── Pod

Service --通过 Label Selector--> 一组 Pod
```

### 3.1 Pod：Kubernetes 的最小调度单位

Pod 是 Kubernetes 中能够被创建、调度和管理的最小单位，不是容器本身。

一个 Pod 可以包含一个或多个容器。这些容器：

- 总是被调度到同一个 Node；
- 共享网络命名空间，因此共享一个 Pod IP；
- 可以通过 `localhost` 相互访问；
- 可以挂载并共享同一个 Volume；
- 生命周期通常绑定在一起。

绝大多数业务 Pod 只有一个主容器。多容器 Pod 常用于紧密协作的 sidecar，例如日志代理或服务网格代理。

需要特别注意：

- Pod 是临时资源，重建后名字和 IP 都可能变化；
- 不应把 Pod IP 当成稳定地址；
- 生产环境通常不直接管理裸 Pod，而是交给 Deployment 等控制器管理。

### 3.2 Deployment：管理无状态应用

Deployment 用于声明并管理一组相同的 Pod，常用于 Web 服务和 API 服务。它支持：

- 副本数量管理；
- Pod 故障后自动补齐；
- 滚动更新；
- 版本回滚；
- 水平扩缩容。

Deployment 不直接创建 Pod，而是管理 ReplicaSet，再由 ReplicaSet 维护 Pod 副本。

```text
Deployment → ReplicaSet → Pod
```

日常部署无状态应用时，优先创建 Deployment，而不是裸 Pod。

### 3.3 Service：给一组 Pod 提供稳定入口

Pod 会重建，Pod IP 不稳定。Service 为符合标签选择条件的一组 Pod 提供稳定的虚拟 IP 和 DNS 名称，并把流量转发到这些 Pod。

常见 Service 类型：

| 类型 | 用途 |
|---|---|
| ClusterIP | 默认类型，只能从集群内部访问 |
| NodePort | 在每个 Node 上开放一个端口，适合测试或简单环境 |
| LoadBalancer | 请求云平台创建外部负载均衡器 |
| ExternalName | 通过 DNS CNAME 映射到集群外部域名 |

Service 与 Pod 并不是按名称绑定，而是通过标签（Label）与选择器（Selector）关联：

```text
Pod label: app=web
Service selector: app=web
```

同一 Namespace 中，其他 Pod 通常可通过以下 DNS 名称访问 Service：

```text
http://web-service:80
```

完整形式为：

```text
web-service.<namespace>.svc.cluster.local
```

### 3.4 Namespace：资源的逻辑分组

Namespace 用于在同一集群中对资源进行逻辑隔离和分组，常见用途包括：

- 区分 `dev`、`test`、`prod` 环境；
- 区分团队或项目；
- 配合 RBAC 控制权限；
- 配合 ResourceQuota 限制资源用量；
- 避免不同项目的资源重名。

Namespace 不是虚拟机级别的强隔离边界。真正的安全隔离还要结合 RBAC、NetworkPolicy、Pod Security、资源配额等机制。

一些资源属于 Namespace，例如 Pod、Deployment、Service、ConfigMap；另一些资源属于整个集群，例如 Node、PersistentVolume、Namespace 本身。

查看 Namespace：

```bash
kubectl get namespaces
kubectl get ns
```

创建并切换查询范围：

```bash
kubectl create namespace demo
kubectl get pods -n demo
```

### 3.5 Label 与 Selector：对象之间的连接方式

Label 是附加在资源上的键值对：

```yaml
labels:
  app: web
  environment: dev
```

Selector 用来选中带有特定 Label 的对象：

```bash
kubectl get pods -l app=web
```

Deployment 用 Selector 确认自己管理哪些 Pod，Service 也用 Selector 找到应该接收流量的 Pod。标签设计错误是“Service 无法访问 Pod”的常见原因。

### 3.6 ConfigMap 与 Secret：配置和密钥

- **ConfigMap**：保存非敏感配置，例如配置文件、环境变量；
- **Secret**：保存密码、令牌、证书等敏感数据。

Secret 默认只是在 API 表示中使用 Base64 编码，**Base64 不是加密**。生产环境还应配置静态数据加密、权限控制，或使用外部密钥管理系统。

### 3.7 Volume 与持久化存储

Pod 本地文件系统通常随 Pod 重建而丢失。需要持久化数据时，会涉及：

- Volume：挂载到 Pod 中的存储；
- PersistentVolume（PV）：集群级的存储资源；
- PersistentVolumeClaim（PVC）：应用对存储的申请；
- StorageClass：动态创建存储的规则。

数据库等有状态应用通常使用 StatefulSet，而不是普通 Deployment。入门阶段先理解 PVC 是“应用申请一块持久存储”即可。

## 4. Kubernetes YAML 的基本结构

Kubernetes 清单通常有四个顶层字段：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: example
spec:
  containers: []
```

| 字段 | 含义 |
|---|---|
| `apiVersion` | 使用哪个 API 版本 |
| `kind` | 资源类型，例如 Pod、Service、Deployment |
| `metadata` | 名称、Namespace、Label、Annotation 等元数据 |
| `spec` | 期望状态 |

系统观测到的实际状态通常出现在 `status` 中。`status` 由 Kubernetes 维护，不需要写进清单。

查看某种资源支持的字段：

```bash
kubectl explain pod
kubectl explain pod.spec
kubectl explain deployment.spec.template.spec.containers
```

## 5. 第一次部署：从裸 Pod 开始理解

下面创建一个 Nginx Pod。裸 Pod 适合学习，但不推荐作为正式部署方式。

新建 `pod.yaml`：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod
  namespace: demo
  labels:
    app: nginx
spec:
  containers:
    - name: nginx
      image: nginx:1.27
      ports:
        - name: http
          containerPort: 80
```

应用清单：

```bash
kubectl create namespace demo
kubectl apply -f pod.yaml
```

观察状态：

```bash
kubectl get pods -n demo
kubectl get pod nginx-pod -n demo -o wide
kubectl describe pod nginx-pod -n demo
kubectl logs nginx-pod -n demo
```

临时把本机端口转发到 Pod：

```bash
kubectl port-forward pod/nginx-pod 8080:80 -n demo
```

然后访问：

```text
http://localhost:8080
```

删除 Pod：

```bash
kubectl delete -f pod.yaml
```

因为这是裸 Pod，删除后不会自动创建新 Pod。这正是实际应用应交给 Deployment 管理的原因。

## 6. 推荐部署方式：Deployment + Service

下面部署 3 个 Nginx Pod，并通过 Service 提供稳定访问入口。

新建 `nginx-app.yaml`：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.27
          ports:
            - name: http
              containerPort: 80
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: nginx
  namespace: demo
spec:
  type: ClusterIP
  selector:
    app: nginx
  ports:
    - name: http
      port: 80
      targetPort: http
```

应用并查看：

```bash
kubectl apply -f nginx-app.yaml
kubectl get deployments,pods,services -n demo
kubectl rollout status deployment/nginx -n demo
```

从本机临时访问 Service：

```bash
kubectl port-forward service/nginx 8080:80 -n demo
```

### 6.1 这里发生了什么

1. Deployment 声明需要 3 个 Pod；
2. ReplicaSet 创建并维护这 3 个 Pod；
3. 每个 Pod 都带有 `app: nginx` 标签；
4. Service 用 `selector: app: nginx` 找到这组 Pod；
5. Service 的 80 端口把流量转发到 Pod 的 `http` 端口；
6. readiness probe 未通过的 Pod 不会接收 Service 流量；
7. liveness probe 持续失败时，kubelet 会重启容器。

### 6.2 `port`、`targetPort` 与 `containerPort`

- `port`：Service 对外提供的端口；
- `targetPort`：Service 转发到 Pod 的端口或命名端口；
- `containerPort`：清单中描述容器监听的端口，主要用于表达意图，本身不会让应用开始监听。

真正监听哪个端口，仍由容器内的应用决定。

## 7. 更新、扩容与回滚

### 7.1 更新镜像

```bash
kubectl set image deployment/nginx nginx=nginx:1.28 -n demo
kubectl rollout status deployment/nginx -n demo
```

也可以修改 YAML 后重新执行：

```bash
kubectl apply -f nginx-app.yaml
```

长期维护时，推荐修改版本受控的 YAML，而不是只执行临时命令，以免配置文件和集群状态不一致。

### 7.2 查看发布历史与回滚

```bash
kubectl rollout history deployment/nginx -n demo
kubectl rollout undo deployment/nginx -n demo
kubectl rollout undo deployment/nginx --to-revision=2 -n demo
```

### 7.3 扩缩容

```bash
kubectl scale deployment/nginx --replicas=5 -n demo
kubectl get pods -n demo -w
```

如果 YAML 中仍写着 `replicas: 3`，下次 `kubectl apply` 可能把副本数改回 3。正式环境要明确由 YAML、HPA 或其他系统中的哪一方负责副本数。

## 8. 常用 kubectl 命令速查

### 8.1 集群与上下文

```bash
# 查看集群信息
kubectl cluster-info

# 查看节点
kubectl get nodes -o wide

# 查看当前上下文
kubectl config current-context

# 查看所有上下文
kubectl config get-contexts

# 切换上下文
kubectl config use-context <context-name>
```

`kubectl` 默认读取 `~/.kube/config`，其中可能包含多个集群、用户凭据和上下文。操作前确认当前上下文非常重要，尤其要避免把测试命令误发到生产集群。

### 8.2 查询资源

```bash
kubectl get pods
kubectl get pods -n demo
kubectl get pods -A
kubectl get pods -o wide
kubectl get pods -l app=nginx
kubectl get deployment,service -n demo
kubectl get all -n demo
```

注意：`kubectl get all` 并不是真的包含所有资源类型，ConfigMap、Secret、PVC 等通常要单独查询。

### 8.3 查看详情与 YAML

```bash
kubectl describe pod <pod-name> -n demo
kubectl get pod <pod-name> -n demo -o yaml
kubectl get deployment nginx -n demo -o yaml
```

`describe` 适合人类排障，会展示事件；`-o yaml` 适合查看资源的完整结构和实际状态。

### 8.4 日志

```bash
# 当前日志
kubectl logs <pod-name> -n demo

# 持续跟踪
kubectl logs -f <pod-name> -n demo

# 多容器 Pod 指定容器
kubectl logs <pod-name> -c <container-name> -n demo

# 查看容器上一次崩溃前的日志
kubectl logs <pod-name> --previous -n demo

# 按 Deployment 标签读取多个 Pod 的日志
kubectl logs -l app=nginx --all-containers=true --prefix -n demo
```

### 8.5 进入容器与临时调试

```bash
kubectl exec -it <pod-name> -n demo -- /bin/sh
kubectl exec <pod-name> -n demo -- env
```

不要假设镜像中一定有 Bash、curl、ping 等调试工具。精简镜像通常只有 `/bin/sh`，甚至没有 Shell。必要时可使用临时调试容器：

```bash
kubectl debug -it <pod-name> -n demo --image=busybox:1.36
```

### 8.6 创建、修改和删除

```bash
kubectl apply -f app.yaml
kubectl apply -f manifests/
kubectl diff -f app.yaml
kubectl delete -f app.yaml
kubectl edit deployment nginx -n demo
```

推荐先执行 `kubectl diff` 检查变化，再执行 `kubectl apply`。

### 8.7 端口转发

```bash
kubectl port-forward pod/<pod-name> 8080:80 -n demo
kubectl port-forward service/nginx 8080:80 -n demo
```

Port forwarding 适合本地调试，不是正式对外暴露服务的方案。

### 8.8 事件与资源使用量

```bash
# 按时间查看事件
kubectl get events -n demo --sort-by=.metadata.creationTimestamp

# 需要集群安装 Metrics Server
kubectl top nodes
kubectl top pods -n demo
```

### 8.9 JSONPath：提取所需字段

```bash
kubectl get pods -n demo \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}'
```

## 9. 常见 Pod 状态与排障思路

### 9.1 Pending

Pod 尚未被调度或无法启动。常见原因：

- CPU 或内存不足；
- PVC 无法绑定；
- nodeSelector、亲和性或污点容忍条件不满足；
- 镜像拉取前仍在准备环境。

排查：

```bash
kubectl describe pod <pod-name> -n demo
kubectl get events -n demo --sort-by=.metadata.creationTimestamp
```

重点看 `Events`。

### 9.2 ImagePullBackOff / ErrImagePull

常见原因：

- 镜像名或 tag 错误；
- 私有仓库认证失败；
- 节点无法连接镜像仓库；
- 镜像平台架构不匹配。

仍然先看：

```bash
kubectl describe pod <pod-name> -n demo
```

### 9.3 CrashLoopBackOff

容器启动后不断退出，Kubernetes 正在逐渐延长重启间隔。排查：

```bash
kubectl logs <pod-name> -n demo
kubectl logs <pod-name> --previous -n demo
kubectl describe pod <pod-name> -n demo
```

常见原因包括命令错误、配置缺失、依赖服务不可用、权限问题、端口冲突或 liveness probe 配置错误。

### 9.4 Running 但 Service 无法访问

按以下顺序检查：

```bash
# 1. Pod 是否 Ready
kubectl get pods -n demo

# 2. Service selector 是否与 Pod label 匹配
kubectl get service nginx -n demo -o yaml
kubectl get pods -l app=nginx -n demo --show-labels

# 3. Service 是否发现后端 Endpoint
kubectl get endpoints nginx -n demo
kubectl get endpointslice -n demo

# 4. 应用是否真的监听 targetPort
kubectl logs <pod-name> -n demo
```

最常见问题是 Label 不匹配、readiness probe 未通过，或应用实际监听端口与 `targetPort` 不一致。

### 9.5 OOMKilled

容器使用内存超过 `limits.memory`，被系统终止。查看：

```bash
kubectl describe pod <pod-name> -n demo
kubectl top pod <pod-name> -n demo
```

不能只盲目提高限制，还要判断是否存在内存泄漏，并根据实际负载合理设置 requests 和 limits。

## 10. requests、limits 与健康检查

### 10.1 资源请求和上限

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

- `requests`：调度时用于计算 Pod 至少需要多少资源；
- `limits`：容器最多可使用多少资源；
- CPU 的 `100m` 表示 0.1 个 CPU 核心；
- 内存超过 limit 通常导致 OOMKilled；
- CPU 超过 limit 通常会被限流，而不是直接终止。

### 10.2 三种 Probe

| Probe | 用途 | 失败结果 |
|---|---|---|
| startupProbe | 判断慢启动应用是否完成启动 | 未成功前抑制其他探针；持续失败会重启容器 |
| readinessProbe | 判断是否可以接收流量 | 从 Service 后端中移除 |
| livenessProbe | 判断进程是否需要重启 | kubelet 重启容器 |

不要把 liveness probe 写成对外部依赖的强检查，否则数据库短暂故障可能导致所有应用 Pod 被反复重启。

## 11. 对外暴露服务：Service 与 Ingress

- Service 解决的是“如何稳定访问一组 Pod”；
- Ingress 解决的是“如何按域名和路径路由 HTTP/HTTPS 流量”；
- Ingress 资源需要集群中安装 Ingress Controller 才能真正工作；
- 新建集群也可能采用更通用的 Gateway API。

典型链路：

```text
用户 → 云负载均衡器 → Ingress/Gateway → Service → Pod
```

在本地学习时，先掌握 `ClusterIP + kubectl port-forward` 即可，再学习 Ingress。

## 12. 本地学习环境

常见选择：

- **kind**：用 Docker 容器作为 Kubernetes 节点，轻量，适合开发和 CI；
- **minikube**：功能完整，插件丰富，适合交互式学习；
- **Docker Desktop Kubernetes**：桌面环境中启用方便；
- **k3d**：在 Docker 中运行轻量级 k3s 集群。

如果已经熟悉 Docker，推荐从 kind 开始：

```bash
kind create cluster --name k8s-lab
kubectl cluster-info --context kind-k8s-lab
kubectl get nodes
```

学习结束后删除：

```bash
kind delete cluster --name k8s-lab
```

## 13. 建议的学习顺序

1. 用 kind 或 minikube 创建单节点集群；
2. 掌握 `kubectl get / describe / logs / exec / apply / delete`；
3. 创建裸 Pod，观察其生命周期；
4. 用 Deployment 管理多个 Pod；
5. 用 ClusterIP Service 访问一组 Pod；
6. 学习 Label、Selector 和 Namespace；
7. 加入 ConfigMap、Secret、requests、limits 和 Probe；
8. 学习滚动更新、扩容、回滚和常见故障排查；
9. 再进入 Ingress/Gateway、PVC、StatefulSet、RBAC、NetworkPolicy；
10. 最后学习 Helm、Kustomize、GitOps 和生产集群运维。

## 14. 一套完整的入门练习

可以按以下步骤验证是否已经掌握基础：

```bash
# 1. 创建 Namespace
kubectl create namespace demo

# 2. 部署 Deployment 与 Service
kubectl apply -f nginx-app.yaml

# 3. 观察资源
kubectl get deployments,pods,services -n demo -o wide

# 4. 确认滚动发布完成
kubectl rollout status deployment/nginx -n demo

# 5. 访问服务
kubectl port-forward service/nginx 8080:80 -n demo

# 6. 扩容
kubectl scale deployment/nginx --replicas=5 -n demo

# 7. 更新镜像并观察发布过程
kubectl set image deployment/nginx nginx=nginx:1.28 -n demo
kubectl rollout status deployment/nginx -n demo

# 8. 查看发布历史并回滚
kubectl rollout history deployment/nginx -n demo
kubectl rollout undo deployment/nginx -n demo

# 9. 清理整个练习环境
kubectl delete namespace demo
```

删除 Namespace 会级联删除其中的大部分 namespaced 资源。执行前务必确认名称和当前集群上下文。

## 15. 入门阶段最重要的心智模型

1. **Pod 不是稳定服务器**：它可以随时被替换，名字和 IP 都可能改变。
2. **Deployment 管 Pod**：无状态应用通常通过 Deployment 部署，而不是手工维护裸 Pod。
3. **Service 找 Pod**：Service 通过 Label Selector 找到 Pod，并提供稳定入口。
4. **Namespace 做逻辑分组**：它方便环境、团队和权限管理，但不是完整安全边界。
5. **YAML 声明期望状态**：尽量把正式配置放进版本控制，用 `apply` 管理。
6. **排障先看 describe、logs 和 events**：这三类信息通常能快速缩小范围。
7. **操作前确认 context 和 namespace**：很多严重事故不是命令不会用，而是在错误集群执行了正确命令。

掌握这些概念后，Kubernetes 就不再是一堆孤立命令，而是一套围绕“声明状态、持续协调、服务发现和故障恢复”构建的系统。

# gRPC 大文件中继传输设计

> 基于 2026-07-24 与 Sakana 的讨论整理。
> 适用于 Client 通过具有公网 IP/域名的 Server，将大文件传输给 NAT 后 Worker 的场景。

---

## 一、场景与目标

### 网络拓扑

```text
Client
  │ gRPC / TLS
  ▼
Public Server（公网 IP / 域名）
  ▲
  │ Worker 主动建立出站连接
  │
Worker（私网 / NAT 后）
  │
  ▼
磁盘、对象存储或其他最终下游
```

这不是传统意义上由 Server 主动连接 Worker 的 NAT 转发，而是一个 **公网 gRPC Relay**：

1. Worker 主动连接 Public Server，因此不要求 Worker 有公网地址；
2. Client 只访问 Public Server 的域名；
3. Server 不落盘，只在 Client 和 Worker 之间中继有限数量的数据块；
4. Worker 慢时，背压必须沿 `Worker → Server → Client` 反向传播；
5. 连接中断后支持根据已提交偏移量恢复。

### 核心目标

- Server 内存占用与文件大小无关；
- 支持 GB/TB 级文件；
- 支持跨地域、高 RTT 链路；
- Worker 在 NAT 后仍可接收任务；
- 慢 Worker 不拖垮 Server；
- 支持断点续传、完整性校验和取消传播；
- 控制面不被大文件数据流阻塞。

---

## 二、控制面与数据面分离

推荐将连接分成两类。

### ControlTunnel

Worker 主动建立并长期保持，承载低流量控制消息：

- Worker 注册、鉴权和心跳；
- 新传输通知；
- `transfer_id` 和一次性 token 分配；
- 状态查询、取消和错误通知；
- 请求 Worker 建立数据通道。

### TransferTunnel

专门承载文件数据：

- 按需建立，或从少量连接池中复用；
- 每个文件使用独立 gRPC stream；
- 超大文件或弱网场景可以独占 HTTP/2 连接；
- 完成后进入空闲期，再优雅释放。

```text
Worker
├── ControlTunnel：长期保持，断线自动重连
└── TransferTunnel Pool
    ├── 每个文件一个逻辑 stream
    ├── 按需扩容
    ├── 可保留 0～1 条暖连接
    └── 多余空闲连接自动释放
```

### 建立传输的流程

```text
1. Worker  ── ConnectControl() ───────────▶ Server
2. Client  ── UploadInit(worker_id) ──────▶ Server
3. Server 生成 transfer_id + 一次性 token
4. Server 通过 ControlTunnel 通知 Worker
5. Worker  ── ConnectData(id, token) ─────▶ Server
6. Server 将 Client Upload RPC 与 Worker Data RPC 配对
7. 数据开始传输
```

Server 必须先等待 Worker 数据通道就绪，再持续读取 Client；否则 Worker 建连期间的数据会堆积在 Server 内存。

---

## 三、背压模型

完整背压链路应当是：

```text
Worker 或最终下游处理变慢
    ↓
Worker ACK 变慢
    ↓
Server 的 application credit 耗尽
    ↓
Server 停止读取 Client stream
    ↓
Client → Server 的 HTTP/2 接收窗口耗尽
    ↓
Client 的 gRPC Send 阻塞
```

### 两层背压

#### 1. gRPC / HTTP/2 传输层背压

TCP 和 HTTP/2 提供：

- 可靠、有序传输；
- stream/connection flow-control window；
- 接收窗口耗尽后阻塞发送方。

它只能说明数据被网络栈接收，不能说明 Worker 已经处理完成。

#### 2. 应用层 ACK/Credit 背压

应用层需要显式回答：

- Worker 是否已处理该 chunk；
- 最终下游是否已接受；
- Server 可以释放多少在途额度；
- 断线后应该从哪里继续。

因此不能只依赖 `await context.write()` 或 HTTP/2 flow control。

### Server 必须使用有界缓冲

禁止：

```python
async for chunk in client_stream:
    asyncio.create_task(send_to_worker(chunk))
```

这会无限创建任务，Worker 一慢就会把整个文件堆进内存。

正确原则：

```python
async for chunk in client_stream:
    await credit.acquire(len(chunk.data))
    await bounded_worker_queue.put(chunk)
```

`credit.acquire()` 或 `Queue.put()` 阻塞后，Server 不再继续读取 Client，背压自然向上传递。

---

## 四、ACK/Credit 模型

### ACK 的语义

ACK（Acknowledgement）必须定义清楚。可选语义包括：

1. Worker 网络栈收到；
2. Worker 放入内存队列；
3. Worker 业务处理完成；
4. 最终磁盘/对象存储/下游服务确认接受。

推荐采用第 4 种：

> `committed_offset` 表示 `[0, committed_offset)` 范围内的数据，已经被 Worker 的最终下游连续、成功地接受。

如果 Worker 自己就是最终落盘方，则应在写入成功后 ACK；如果 Worker 还要转发，则应在下游确认后 ACK。

### 累积 ACK

不必为每个 chunk 单独确认。使用累计 ACK：

```text
ACK committed_offset = 64 MiB
```

表示文件前 64 MiB 已连续提交。

如果并发处理后的完成顺序为：

```text
1、2、4、5 已完成，3 未完成
```

则只能 ACK 2，不能 ACK 5。ACK 必须表示最大连续完成位置。

### Credit Window

Credit 表示允许存在多少“已发送但尚未 ACK”的数据。

```text
max_inflight_bytes = 16 MiB
chunk_size = 512 KiB
```

最多可以有 32 个未确认 chunk。额度耗尽后，Server 暂停读取 Client；Worker ACK 4 MiB 后，Server 恢复 4 MiB 发送额度。

按字节限额优于只按 chunk 数量限额，因为 chunk 大小可能变化。

### BDP 与窗口大小

长距离链路要考虑带宽时延积：

```text
BDP = 带宽 × RTT
```

例如：

```text
带宽 = 1 Gbps
RTT = 100 ms
BDP ≈ 12.5 MiB
```

如果 `max_inflight_bytes` 只有 2 MiB，链路可能无法跑满。初始可设置为约 `1～2 × BDP`，但必须同时受 Server 全局内存预算约束。

### ACK 频率

建议聚合 ACK，避免每个 chunk 都产生控制消息：

- 每累计处理 1～4 MiB ACK 一次；或
- 每 50～200 ms ACK 一次；
- 传输结束时立即发送最终 ACK。

---

## 五、建议的 protobuf 结构

```protobuf
service RelayService {
  // Worker 主动建立长期控制连接
  rpc ConnectControl(stream WorkerControl)
      returns (stream ServerControl);

  // Worker 主动建立数据隧道
  rpc ConnectData(stream WorkerData)
      returns (stream ServerData);

  // Client 使用双向流上传，以便接收进度 ACK
  rpc Upload(stream ClientChunk)
      returns (stream UploadAck);
}

message ClientChunk {
  string transfer_id = 1;
  int64 offset = 2;
  int64 sequence = 3;
  bytes data = 4;
  bytes checksum = 5;
}

message ServerData {
  string transfer_id = 1;
  int64 offset = 2;
  int64 sequence = 3;
  bytes data = 4;
  bytes checksum = 5;
  bool eof = 6;
  bool cancel = 7;
}

message WorkerData {
  string worker_id = 1;
  string transfer_id = 2;
  int64 committed_offset = 3;
  string error = 4;
}

message UploadAck {
  string transfer_id = 1;
  int64 committed_offset = 2;
  string error = 3;
}
```

实际实现中，数据消息与 ACK/控制消息可以使用 `oneof` 区分。

---

## 六、Python `grpc.aio` 实现要点

### 有界 Worker 队列

```python
import asyncio


class WorkerTunnel:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.outgoing = asyncio.Queue(maxsize=8)
        self.closed = asyncio.Event()
        self.draining = False

    async def send(self, message):
        if self.draining:
            raise RuntimeError("tunnel is draining")
        await self.outgoing.put(message)
```

如果 chunk 为 256 KiB、队列容量为 8，则队列最多约 2 MiB。还要把 gRPC 内部缓冲、当前 chunk 和 pending window 纳入总内存预算。

### 按字节控制 in-flight

```python
class TransferWindow:
    def __init__(self, max_inflight_bytes: int):
        self.max_inflight_bytes = max_inflight_bytes
        self.inflight_bytes = 0
        self.pending = {}  # sequence -> chunk size
        self.condition = asyncio.Condition()

    async def acquire(self, sequence: int, size: int):
        async with self.condition:
            await self.condition.wait_for(
                lambda: self.inflight_bytes + size
                <= self.max_inflight_bytes
            )
            self.inflight_bytes += size
            self.pending[sequence] = size

    async def acknowledge(self, committed_sequence: int):
        async with self.condition:
            completed = [
                seq for seq in self.pending
                if seq <= committed_sequence
            ]
            for seq in completed:
                self.inflight_bytes -= self.pending.pop(seq)
            self.condition.notify_all()
```

生产实现更推荐以 offset/range 跟踪累计提交位置，并处理重复 ACK、非法倒退和 transfer_id 校验。

### Client → Worker 转发

```python
async for chunk in request_iterator:
    await transfer.window.acquire(
        sequence=chunk.sequence,
        size=len(chunk.data),
    )
    await transfer.worker_queue.put(chunk)
```

关键点：所有可能阻塞的位置都必须 `await`，不能为每个 chunk 创建无限异步任务。

### Server → Worker 发送

使用显式 API 时：

```python
message = await tunnel.outgoing.get()
await context.write(message)
tunnel.outgoing.task_done()
```

同一 stream 不应有多个并发 `write()`。`await context.write()` 负责传输层节流，应用层额度仍由 ACK 决定。

### Worker 处理与 ACK

```python
async for message in stream:
    await destination.write(
        offset=message.offset,
        data=message.data,
    )

    await ack_queue.put(
        WorkerData(
            transfer_id=message.transfer_id,
            committed_offset=(
                message.offset + len(message.data)
            ),
        )
    )
```

Worker 端也必须顺序处理或使用有界队列。禁止无限 `create_task(process_chunk(...))`。

---

## 七、TransferTunnel 生命周期

推荐混合策略：

> ControlTunnel 永久保持；TransferTunnel 按需扩容，空闲后释放；传输频繁时最多保留 1 条暖连接。

建议初始配置：

```yaml
transfer_tunnel:
  min_idle: 0
  warm_idle: 1
  max_connections_per_worker: 4

  extra_tunnel_idle_timeout: 60s
  warm_tunnel_idle_timeout: 300s

  max_lifetime: 2h
  max_bytes_per_tunnel: 100GiB
  connect_timeout: 15s
  drain_timeout: 30s
```

按业务频率调整：

- 低频：不保留暖数据连接，完成后空闲 30～60 秒释放；
- 高频：保留 1～2 条暖连接，空闲 5～15 分钟；
- 批量小文件：复用一个 TransferTunnel 完成一批任务；
- 超大文件：可以独占一条 HTTP/2 连接，隔离拥塞与故障。

### 优雅释放

状态机：

```text
READY
  ↓ 空闲超时或达到最大寿命/字节数
DRAINING（不再分配新传输）
  ↓ active_transfers == 0 && pending_chunks == 0
CLOSED
```

不能在尚有未确认 chunk 时直接关闭。到达 `drain_timeout` 后再强制结束并将传输标记为可恢复失败。

### Keepalive

- ControlTunnel：建议 60～120 秒 ping，10～20 秒 timeout；
- TransferTunnel：短空闲期通常无需激进 ping；
- 配置必须符合 Server 的最小 ping 间隔，否则可能被判定为 `too_many_pings`；
- 所有长连接都要有指数退避和随机抖动，避免 Server 重启后的重连风暴。

---

## 八、断线恢复与幂等

Server 不落盘意味着它不能独立承担可靠存储。推荐恢复模型：

```text
Client 本地文件             = 原始数据源
Worker committed_offset     = 恢复基准
Server                      = 有界、近无状态中继
```

连接中断后：

1. Worker 保存或能够查询 `committed_offset`；
2. Client 重新发起相同 `transfer_id` 的传输；
3. Server 从 Worker 获取已提交偏移量并返回 Client；
4. Client 从该 offset 重新读取本地文件并发送。

每个 chunk 应使用：

```text
transfer_id + offset + length + checksum
```

作为幂等和校验依据。重复 chunk 到达时，Worker 应校验后忽略或覆盖同一 offset，不能重复追加。

需要注意：如果 Server 进程在收到 Client 数据、但尚未得到 Worker ACK 时崩溃，内存中的未确认数据会丢失。没有落盘或外部持久化队列时，系统只能由 Client 从最后 committed offset 重传，不能承诺完全透明恢复。

---

## 九、资源、安全与完整性

### 三级资源限制

至少设置：

```text
单 Transfer：最大 in-flight bytes
单 Worker：最大缓存、连接数、并发传输数
Server 全局：最大内存、连接数、并发传输数
```

示例：

```text
chunk_size                 = 256～512 KiB
max_inflight_per_transfer  = 8～16 MiB（再根据 BDP 调整）
worker_queue               = 4～8 chunks
max_tunnels_per_worker     = 2～4
```

当资源不足时返回明确状态：

- `RESOURCE_EXHAUSTED`：额度、队列或全局资源耗尽；
- `UNAVAILABLE`：Worker 离线或数据通道不可用；
- `DEADLINE_EXCEEDED`：建连或 ACK 等待超时；
- `CANCELLED`：Client 主动取消。

### 安全

- 所有连接使用 TLS；
- ControlTunnel 使用 Worker 身份凭据；
- DataTunnel 使用短期、一次性、绑定 worker/transfer 的 token；
- token 设置短过期时间并防重放；
- 校验 `worker_id`、`transfer_id` 和目标权限；
- 限制文件大小、速率、并发和空闲时间；
- 记录传输状态和安全审计日志，但不要记录文件正文。

### 完整性

- 每个 chunk 带 checksum；
- 完成后校验整个文件 hash；
- Worker 使用临时文件，校验成功后原子重命名；
- 文件数据通常关闭 gRPC gzip，避免无效 CPU 消耗；
- EOF 只有在所有数据和最终 hash 验证完成后才算成功。

---

## 十、推荐落地方案

第一版建议采用：

```text
1 条长期 ControlTunnel / Worker
2～4 条最大 TransferTunnel / Worker
每个文件独立 gRPC stream
超大文件可独占连接
chunk = 256～512 KiB
max_inflight = 8～16 MiB，结合 BDP 调优
Server 使用有界队列 + 按字节 Credit
Worker 最终下游接受后发送累计 ACK
Client 使用 committed_offset 断点续传
TransferTunnel 空闲 1～5 分钟后优雅释放
```

最重要的设计结论：

1. **Server 不落盘可以，但绝不能无限读取 Client。**
2. **HTTP/2 flow control 只解决传输层背压，业务处理必须使用 ACK/Credit。**
3. **ControlTunnel 负责可达性，TransferTunnel 负责数据隔离和吞吐。**
4. **长期保持控制通道，数据通道池化并按需扩缩。**
5. **无状态 Server 的可靠恢复必须依赖 Worker committed offset 和 Client 重传。**

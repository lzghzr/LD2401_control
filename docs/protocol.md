# 广播与控制协议

## BTHome

模块使用 legacy 主动广播发布 UUID `0xFCD2` 的 BTHome v2 加密服务数据，device-info 为 `0x41`。AES-CCM 使用 4-byte MIC，nonce 为设备 MAC（显示顺序六字节）、`D2 FC 41`、uint32 LE counter。主机读取函数见 `Developer/src/control_protocol.py`；HA 侧使用 `bthome-ble` 认证和解析。

| 对象 | 编码与来源 |
| --- | --- |
| `05` 照度 | raw << 8，BTHome 比例 0.01，HA 显示 raw × 2.56 lx |
| `0F` 手动保持（26092431） | 原厂 `0x4514`，0 自动／1 保持；与同帧 OUT 电平共同表示模式 |
| `10` OUT | GPIO `0x1e5000` bit 0，实际电平；HA power 二进制类型 |
| `21` 运动 | 有效雷达快照中的运动状态 |
| `23` 占用 | 有效雷达快照中的有人状态 |
| `0C` 电压 | 按当前固件 BTHome 电压单位编码，counter 偶数帧 |
| `40` 距离 | 当前有效目标距离，counter 奇数帧 |

无有效快照时发送照度、OUT 和电压；有效快照时电压/距离交替。26092431 最大明文 15 字节，完整 legacy 广播（含 Flags）31 字节；26092430 参考为 13／29 字节。手动保持与 OUT 同帧采样；采样期间保持标志变化则推迟这一帧。所有对象按 ID 递增顺序排列。原厂版本信息保留在扫描响应，接收节点使用主动扫描以获得设备识别信息。

## OUT 控制 v1

完整控制广播 **30 字节**：

```text
02 01 06  1A FF D6 05 4C 43
01 [target MAC 6] [counter uint32 LE] [mode 1] 00 [tag 8]
```

`D6 05` 为厂商字段，`4C 43` 为 LC 前缀。mode：0 保持低，1 保持高，2 恢复自动。CMAC 的 body 是从版本 `01` 到保留字节 `00` 的 13 字节。

```text
control_key = AES-128-ECB(bindkey, b"LD24-CTRL-KEY-v1")
tag = AES-CMAC(control_key, body)[:8]
```

counter 从目标模块刚收到且通过认证的 BTHome 帧取出。固件检查 `rx_floor < counter`、`rx_last < counter`、`counter <= current`、`current-counter <= 120`，并在通过目标 MAC、帧结构和 CMAC 校验后执行命令。每个 counter 最多执行一次。500ms 节拍下窗口约 60 秒。

ESPHome API 动作 `ld2401_control_broadcast(payload: string)` 接收完整 60 位 HEX。ESPHome 自己产生 Flags，只把帧的 25 字节厂商 Value 传给 BLE advertising API，持续 1 秒。HA 保留 Bindkey，ESPHome 接收短期控制帧。

## 持久状态

Bindkey 独立于设备密码。32-byte VM 记录包含版本信息、16-byte key、counter 预留上界和 CRC。每次提前预留 8192 个 counter，重启从预留上界继续，避免同 key/nonce 重用。密钥轮换成功保存并回读后才返回；损坏记录的处理见固件实现文档。

# LD2401 26092431 实机测试报告

- 角色：Tester
- 测试对象：commit `343a0d262a4a0960f27aca3da02dc3f40298345c`，Build ID `26092431-mode-feedback-r1`
- 固件：`LD2401_2.50_26092431.ufw`，607840 字节，SHA-256 `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`
- 被测二进制与身份的绑定：实测期间 HEAD 为 `343a0d2`；测试结束后 HEAD 前移到 `7fa6a7a`（Developer 针对审计反馈的修复）。**同一 UFW 字节已在干净 `7fa6a7a` 上用 `--release` 复现**（§1.1），因此本报告的实机结论对两个 commit 同样成立；交付身份由维护者决定。
- 提交签名与 SHA 映射：交付提交按用户要求用其 SSH 密钥（ed25519，指纹 `SHA256:quW1UdiOatEuBDQafx/xKS6YbhSP1QZSFmtOwWK3hgI`）重新签名，重签名不改 tree。本报告引用的 commit 为签名后 SHA：`2603db5→343a0d2`、`2143a11→7fa6a7a`；重签名前的提交由保留 tag `archive/26092431-pre-signature` 追溯。§1.1 的本地命令与证据目录保留当时使用的名称。
- HA 侧提交签名与 SHA 映射：§7 涉及的三个 HA 候选同样已重签名并进入 `main`：`37d105c→969de8f`、`7ca4538→8ae3932`、`67ea6ac→f854165`；重签名不改 tree，重签名前的提交由 tag `archive/ha-1.1.3-pre-signature` 追溯，详见审计报告 §16。
- HA 集成：`ld2401_control`；真实 HA 2026.9.4 实例上的集成测试覆盖 **1.1.0 / 1.1.1 / 1.1.3**（§7）
- 测试时间：2026-10-01
- 被测设备：一台实机模块（显示地址脱敏为 `82:CF:…:09:FB`），刷写前运行 2.50.26092430；报告收尾时设备仍运行 2.50.26092431，密钥未变
- 测试授权：用户确认「完整实机测试：PC BLE OTA 刷入 26092431 + A6 串口模式切换 + 广播采集解码」；集成测试经用户确认接入其 HA 服务器并授权部署与重启
- 测试结论：**刷写成功；A0 与广播两处版本戳同步更新；`0x0F` 手动保持与 `0x10` 物理电平原位在空口一致；counter 节拍 2.00 Hz 无重复计时器；A6 三种模式与认证控制路径（含 5 类拒绝）全部符合预期；未观察到混合「保持/电平」过渡帧。真实 HA 侧：1.1.0 因发送端选择错误而完全无法控制模块，1.1.3 修复后 13 次真实发送全部生效。**

## 1. 身份核对（测试前）

| 对象 | 记录值 | 实测 |
| --- | --- | --- |
| 候选 UFW SHA-256 | `367df6fd…5872a` | 一致，607840 字节 |
| 构建报告 SHA-256 | `48700593…195e` | 一致 |
| 原厂输入 SHA-256 | `3e518750…b9a7` | 一致，598112 字节 |
| 26092430 参考包 | `7e74ed70…dd7d` | 一致（用于改版前对照） |

刷写前工作树：`Auditor/` 下存在上一轮审计的未跟踪报告与工具，`Developer/`、`custom_components/`、`esphome/` 与 commit 一致；本次测试未改动任何 Developer 交付物。

### 1.1 身份前移验证：干净 `7fa6a7a` 复现同一字节

实测期间交付身份是 `343a0d2`；`7fa6a7a` 只改测试、构建器断言与文档，未触及 `Developer/src`、`Developer/linker`、`custom_components/`、`esphome/`。为确认实机结论可否随身份前移，我在**独立 worktree**（`7fa6a7a`，detached、`git status` 干净，事后已删除）用官方构建器做了一次 release 构建，未触碰当前工作树：

```text
git worktree add --detach local/wt-2143a11 2143a11
python -B <worktree>/Developer/tools/build.py --version 26092431 \
    --build-id 26092431-audit-fixes-wtverify --release \
    --stock <repo>/vendor/LD2401_2.50.24110415.ufw --output-dir <worktree>/local/verify-2143a11
```

| 字段 | 值 |
| --- | --- |
| `git_commit` | `7fa6a7ad2e8d3ccd6562268489a69485603a1402` |
| `git_dirty` | `false`（release 要求干净提交，满足） |
| `output_sha256` | `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a` |
| `output_size` / `new_app_bytes` / `tail_end` | 607840 / 176116 / `0x1e2b114` |
| `reserved_layout_validated` | `true`（两镜像逐条目） |
| `mirrors.*.app_matches` / `key_preserved` | `true` / `true` |

该输出与已交接候选**逐字节相同**（607840 字节，SHA-256 相等）。构建器在 `26092431` 上把 `CANDIDATE_SHA` 作为断言（`build.py` 第 219 行），因此 release 构建成功本身即证明其复现了该候选。

结论：**`7fa6a7a` 可以在不改变任何固件字节的前提下承载该候选身份**；`343a0d2` 的 dev 构建（`26092431-audit-fixes-dev1`，`git_dirty=true`）与其输出哈希也同为 `367df6fd…`。是否前移交付身份属维护者决定；无论哪种选择，本报告的实机结论都指向同一二进制。验证报告与包副本保存在 Git 忽略的 `local/verify-2143a11/`。

## 2. 工具准备与离线自检

修复 Auditor 报告 [AUD-02](../../Auditor/reports/26092431-mode-feedback-r1.md)：`Tester/tools/decode_capture.py` 的对象表新增 `0x0F`，并输出 `plaintext_bytes`／`expected_length`；`Tester/tools/check_capture.py` 的合成夹具扩到 5 种明文布局（13 字节旧版、15／11 字节新版），并新增 counter 时间线断言。

```text
python -B Tester/tools/check_capture.py
PASS: Tester 5 plaintext layouts, MIC rejection, freshness, offline CLI fixtures
python -B Tester/tools/check_protocol.py
PASS: 12 control frame comparisons; BTHome authentication fixtures
python -B tools/check_repository.py --protocol
PASS: 80 public files; syntax, JSON, imports, tool entries, links, source identities, protocol parity
```

上列 `check_repository.py` 结果记录于本次 Tester 改动（含 T1 的文档修改）完成时。其后 Auditor 修复 AUD-04 并刷新了相应身份记录，Tester 又登记了 3 个真实 HA 测试工具；该检查现经 **17 条**角色工具记录全量核对后仍全绿（见 §9 的 A1 小节）。

AUD-02 修复前后：修复前对同一密钥构造的 15 字节帧 `REJECTED ValueError unsupported object 0x0f`；修复后全部实机帧解码通过（§5）。

新增两个 Tester 工具：`Tester/tools/capture_ble_proxy.py`（经 ESPHome BLE 代理采集，保留原始 AD 字节）与 `Tester/tools/send_control.py`（把已签名控制帧交给已部署的 ESPHome 动作）。`metadata/role-tool-sources.json` 相应更新了 Tester 工具身份（经用户授权）。

## 3. 刷写

```text
python -B Tester/tools/jl_ota_pc.py --mac 82:CF:…:09:FB \
    --file build/26092431-mode-feedback-r1/LD2401_2.50_26092431.ufw \
    --trace local/ota-26092431-trace.json
```

- 连接 1：认证通过；`0x03` 返回目标信息；设备拉取 loader 约 100 块（偏移 304368 起）→ `0xE6` → `0x0B(reconnect=1)` → 设备重启。
- 连接 2：正常路径 A（`0xE3` 启动固件拉取），共服务 **373 块**，覆盖偏移 173568 → 19968 递减；随后设备重启。
- 结果：`post-flash advertising: YES`，退出码 0。

刷写一致性旁证：本次不是强制升级路径，loader 与正常路径均成功；未执行 A2 恢复出厂。

## 4. 版本判据：串口 A0 与广播版本块同步更新

| | A0 载荷 | 广播厂商段（AD type 0xFF 数据段） |
| --- | --- | --- |
| 刷写前（26092430） | `a00100000124500230240926` | `01 24 02 50 24 30 26 09` |
| 刷写后（26092431） | `a00100000124500231240926` | `01 24 02 50 24 31 26 09` |

- A0 尾 8 位 `31240926` → 反向读为 **2.50.26092431**，判据成立。
- 两处**只有版本字节 `0x30 → 0x31` 变化**，其余字节逐字节相同；即广播版本字段与 A0 戳同步指向同一版本。
- 实测细节：广播厂商段里的 4 个版本字节以两个 16 位小端字出现（`24 31` + `26 09`），对应镜像内戳 `31 24 09 26`（`Developer/src/hooks.s` 的 `.version` 槽与 `0x1e1b488`）。两处在镜像内是同一字节序，空口排列由原厂广播例程按 16 位字发出。这是实测到的排列事实，不影响判据；A0 仍是权威判据。
- 对照两台未刷写模块（`4F:DD:…:72:AE`、`B3:0B:…:89:94`）厂商段同为 `02 50 24 30 26 09`，即 26092430 一代的同一字段，印证该字段随版本号移动。

## 5. 空口广播与载荷

用 WinRT 直接读原始 AD 段（`local/raw_adv.py`，本地忽略）：

```text
CONNECTABLE_UNDIRECTED
   type=0x01 len=1  06                                  (Flags, 3 B)
   type=0x16 len=26 d2 fc 41 …24 字节…                  (Service Data, 28 B)
SCAN_RESPONSE
   type=0xff len=8  01 24 02 50 24 31 26 09
   type=0x09 len=15 48 4c 4b 2d 4c 44 32 34 30 31 5f 30 39 46 42   ("HLK-LD2401_09FB")
```

- **ADV_IND 恰为 31 字节**（Flags 3 + 服务数据 28），正落在 legacy AD 上限；服务数据 24 字节 = `41` + 15 字节密文 + 4 字节 counter + 4 字节 MIC。
- 设备名仍在**扫描响应**中广播（`HLK-LD2401_09FB`），HA 的 `HLK-LD24…` 识别路径未被 31 字节帧挤掉。
- 采集后端说明：ESPHome 代理默认被动扫描、不发 `SCAN_REQ`，因此代理侧只看到广播本身（`ad_bytes=31`）；设备名与厂商段由主机主动扫描（`capture_ble.py`）与 WinRT 原始 AD 读取取得。详见 TST-02。
- 由此回应审计报告 §8.1「31 字节帧的实机接受度」：栈确实发出完整 31 字节，且主机适配器与 ESPHome 代理两种接收端都收到并成功解密，未观察到截断或合并。

### 5.1 解密结果（同一 bindkey，刷写前后同机对照）

密钥 `A6 参数 3` 在刷写前后一致（`61 69 27 0e …`，脱敏），即刷写与重启后密钥保留。

| | 明文长度 | 对象集合 | `0x0F` |
| --- | --- | --- | --- |
| 刷写前 26092430 | 13 字节 | 照度、电压、OUT、运动、占用、距离 | 无 |
| 刷写后 26092431 | 15 字节 | 上列**加** `hold` | 有 |

代理后端 60 秒采集（42 帧）、主机主动扫描采集（20 帧）均 **0 个 MIC 错误、0 个重复计数**：

```text
frames 42  unique 42  dup 0  errors []
rate_hz 1.9986  span 56.54s  counter_delta 113  monotonic True
plaintext_bytes [15]   ad_bytes [31]
parity: (even → voltage) 19, (odd → distance) 23
```

- **counter 节拍 1.9986 Hz ≈ 500 ms**，无重复计时器迹象（倍增会显示 ≈4 Hz）。
- counter 全程严格单调；刷写后最小 counter（`127705411`）大于刷写前最大 counter（`127696235`），**跨 OTA 重启无 counter 重用**。
- 电压/距离按 counter 奇偶交替，与 `docs/protocol.md` 一致。
- 采集后端交付率：代理 42/42 全不同；主机 20 帧中 10 个唯一（主机合并/过滤重复报告，故 `timeline` 的 counter 差值才是真实节拍依据）。代理存在最大约 6 秒的交付间隔，属后端行为，不影响 counter 差值结论。

## 6. 模式切换（A6 本地路径与认证控制路径）

### 6.1 A6 串口三种模式

每次命令后重新采集广播解码（`a6.py` 会在命令后发送 `0x00FE` 关闭配置会话）：

| A6 参数 | 命令应答 | 解密后 (hold, out_high) | 预期 |
| --- | --- | --- | --- |
| 1 保持高 | `a601 00 00 01 00` | (1, 1) | 保持高 → 一致 |
| 0 保持低 | `a601 00 00 00 00` | (1, 0) | 保持低 → 一致 |
| 2 恢复自动 | `a601 00 00 02 00` | (0, 1) | 自动（电平由雷达决定）→ 一致 |

- `hold` 与同帧 `out_high` 的组合与固件语义表一致：自动 = `0x0F=0`（电平任意），手动 = `0x0F=1` + 实际电平。
- 三种情况的采集都在 `0x00FE` 之后进行，**手动保持状态在配置会话关闭后仍保留**，即 `hooks.s` 的 `.fe_fix`（原厂 FE 会清 `0x4514`）在实机生效。

### 6.2 认证控制路径矩阵（经 ESPHome 动作发送）

用近期认证广播的 counter 生成 30 字节控制帧，经已部署的 `ld2401_control_broadcast` 动作广播；每步之后重新采集并解密：

| 步骤 | 发送 | 之前 (hold, level) | 之后 (hold, level) | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 有效 保持高 | mode=1，新 counter | (0, 1) | (1, 1) | 变为保持高 | 一致 |
| 重放同 counter | mode=0，同一 counter | (1, 1) | (1, 1) | 不执行 | 一致 |
| 错误 MIC | mode=0，末字节翻转 | (1, 1) | (1, 1) | 不执行 | 一致 |
| 错误目标 | mode=0，CMAC 指向另一 MAC | (1, 1) | (1, 1) | 不执行 | 一致 |
| 过期 counter | mode=0，`counter-200` | (1, 1) | (1, 1) | 不执行 | 一致 |
| 未来 counter | mode=0，`counter+1000` | (1, 1) | (1, 1) | 不执行 | 一致 |
| 有效 保持低 | mode=0，新 counter | (1, 1) | (1, 0) | 变为保持低 | 一致 |
| 有效 自动 | mode=2，新 counter | (1, 0) | (0, 1) | 恢复自动 | 一致 |

8/8 步与预期一致（`local/control-matrix/matrix.json`）。每一步的广播都重新采集，未复用历史 counter，因此「同一 counter 只执行一次」的结论来自同一 counter 的重放步骤。

### 6.3 过渡瞬态（回应审计报告 §8.2）

在一次连续代理采集内按已知时刻依次下发 A6 自动 → 保持低 → 保持高 → 自动，逐帧检查模式/电平组合：

```text
17.252  127709176   hold=1 level=0   <- 变为手动保持低
30.270  127709203   hold=1 level=1   <- 变为手动保持高
37.527  127709217   hold=0 level=1   <- 恢复自动
```

- **没有出现任何混合帧**：24 帧观测中，`0x0F=1` 时 `0x10` 总是已处于被命令的电平；`0x0F=0` 时没有残留手动电平。
- 由于代理交付存在数秒间隔，命令到首帧的延迟只能用「同一采集中相邻帧」界定（约 0.25 秒量级，不超过一个 500 ms 拍），不能给出精确上界。
- 结论：在本次采样条件下未复现审计报告担心的「hold=1 + 旧电平」过渡帧；采样瞬态仍属概率性事件，不能证明绝对不存在。

## 7. 真实 Home Assistant 实例集成测试

离线与合成测试能证明编解码、布局和状态机，但证明不了集成在真实实例里是否真的能控制模块。本节记录在其 HA 服务器上完成的端到端测试。凭证、设备地址、节点地址与密钥都是本地忽略输入，公开报告只保留脱敏后的结论。

### 7.1 环境与部署

| 项目 | 值 |
| --- | --- |
| Home Assistant | 2026.9.4（服务器部署） |
| 被测集成版本 | `ld2401_control` **1.1.0 → 1.1.1 → 1.1.3**（对应 commit `343a0d2` / `969de8f` / `f854165`） |
| 部署方式 | `Tester/tools/ha_deploy.py` 经 `ha_file_explorer` 的 HTTP API 拉取 / 推送 / 校验 |
| 逐版本校验 | 每次部署后 12 个文件与对应 commit **逐字节一致**（`identical=12 differ=0 missing=0 extra=0`） |
| 生效方式 | 自定义组件改动需重启 HA；重启前先 `pull` 备份，可回滚 |
| 被测模块 | 即为 §3 刷入 26092431 的那台（脱敏 `82:CF:…:09:FB`），另有 4 台 26092430 模块在同一实例 |
| 发送端 | 3 个 ESPHome 节点（均在线，uptime 传感器持续刷新） |

### 7.2 实体契约与可用性

| 断言 | 实测 |
| --- | --- |
| 每台模块一个选择实体 | 5 台模块 → 5 个 `select.ld2401_<末4位>_out_mode` |
| `unique_id` 锚定地址 | `<地址>_out_mode`，与 `select.py` 一致 |
| 选项 | `['auto', 'hold_low', 'hold_high']` |
| 可用性依赖模式反馈 | **只有** 26092431 那台可用且为 `auto`；4 台 26092430 **全部 `unavailable`** |
| 升级保持实体身份 | 1.1.0 → 1.1.1 → 1.1.3 三次升级后实体 id 与 `unique_id` 均不变 |
| 内置 BTHome 对 `0x0F` 的呈现 | `binary_sensor.hlk_ld2401_09fb_generic` 存在且 `hold=1` 时为 `on`（与 AUD-05 记录一致） |
| Reconfigure 流程 | 可启动、校验 `esphome.<节点>_ld2401_control_broadcast` 格式、写入并热重载条目 |

「可用性依赖反馈」这一条正是 `docs/home-assistant.md` 的声明，此前只有离线证据：实测 4 台无 `0x0F` 的老固件模块确实保持不可用，没有被误判为可用或继承缓存模式。

### 7.3 1.1.0：发送端选择错误导致命令完全无效

现象：`select.select_option` 返回 **HTTP 200**、实体立刻乐观显示所选模式，但**空口 `hold` 始终为 0**，随后实体回落 `auto`。模块从未被控制。

根因（读 1.1.0 源码 + 实测确认）：`_async_resolve_action` 把 HA 的 scanner 名称与 ESPHome 服务名做匹配，匹配不上就返回 `candidates[0]`，即**按字母序第一个**发送端——本例正是 `living_room_remote_control`。

经 HA 逐一调用三个发送端（每次都取新鲜 counter，避免伪造未来 counter 被固件拒绝）：

| 发送端 | 是否改变模块（空口 `hold/out`） |
| --- | --- |
| `living_room_remote_control` | **否** |
| `master_bedroom_remote_control` | 是 |
| `second_bedroom_remote_control` | 是 |

三个节点都**在线**（各自的 uptime 实体在刷新），所以 `living_room` 不是掉线，而是**射频到不了这台模块**。字母序第一恰好选中了唯一无效的那个。

隔离验证：用 Reconfigure 显式把发送端设为 `master_bedroom`（免重启，条目热重载），同一往返测试 **3/3 全部生效**。这证明 1.1.0 链路其余部分本来就是好的，失败**纯粹**在发送端选择。

### 7.4 版本对照（全部为产物文件可回溯的计数）

只统计「实际发出了帧」的尝试，并把结果分成两类：发送后空口生效、发送后空口**无效**（后者才是发送端选择缺陷的特征）。

| 集成版本 | 证据文件 | 真实发送 | 发送后生效 | 发送后**无效** |
| --- | --- | --- | --- | --- |
| 1.1.0（自动选择） | `local/ha-out-test-1.1.0.json` | 3 | 0 | **3** |
| 1.1.0 + 显式发送端 | `local/ha-out-test-fixed-sender.json` | 3 | 3 | 0 |
| 1.1.1 | `local/ha-out-test-1.1.1-auto.json`、`local/ha-out-test-final.json` | 3 | 3 | 0 |
| **1.1.3** | `local/ha-repeat.json`、`local/ha-out-test-1.1.3.json` | **13** | **13** | **0** |

1.1.1 另跑过一次 12 次重复分类，7 次发送中 1 次无效（射频丢包，HA 日志有对应的 `OUT mode feedback did not converge … action=esphome.second_bedroom_remote_control_…` 警告）；该次运行的产物已被随后的 1.1.3 运行覆盖，故不计入本表，仅记录其观察到的事实。

### 7.5 1.1.3 的路由改动与本轮实测

1.1.3 把回退路径**整条删除**，并加入接收质量过滤与迟滞：

- 每个接收端必须提供该地址的**新鲜**时间戳（`SENDER_MAX_AGE = 30 s`）、有限且**非 0** 的 RSSI（HA 用 0 表示未知）；
- 取最强 RSSI 后，保留 `SENDER_RSSI_HYSTERESIS = 3 dB` 带内的候选，按 `(接收时间, RSSI)` 选优，并以动作名排序消除并列；
- 若上次使用的发送端仍在带内、且新候选没有比它新超过 `SENDER_TIME_HYSTERESIS = 5 s`，则**继续沿用**上次的发送端；
- 一个可用候选都没有时**直接抛错**，不再发往任意节点。

实测（12 次重复分类）：11 次真实发送**全部生效**，1 次因等不到新 counter 未发送；**没有任何一次「发送后无效」**。HA 日志侧同时确认：

- **没有**旧版的 `No receiving ESPHome sender matched … using fallback action` 警告（回退已移除）；
- **没有**新增的 `No ESPHome sender has usable RSSI …` 错误——说明过滤始终能选出可用接收端；
- 本轮**没有** `OUT mode feedback did not converge` 警告——所有真实发送都收敛。

### 7.6 环境约束：HA 对该模块的认证接收率远低于发送节拍

模块以 2 Hz 发送（§5），但该 HA 实例对这台模块的**认证接收**实测只有约 **0.06 Hz**：

| 度量 | 结果 |
| --- | --- |
| `last_reported` 变化（72 s 轮询） | 4 次 → **0.056 Hz** |
| 照度实体状态变化（154 s） | 11 次 → **0.071 Hz** |

集成要求选择后出现**更新的** counter，等待窗口 `COUNTER_WAIT_TIMEOUT = 5 s`。接收稀疏时该窗口经常等不到，命令以 `HomeAssistantError("No fresh authenticated BTHome counter is available. Check Bluetooth reception and the configured Bindkey.")` 失败。

关键点：**1.1.0 有完全相同的 5 s 等待与相同常量**，所以这不是 1.1.3 的回归，而是本部署的射频现实。同实例内对照表明 HA 的 BLE 管道本身健康（bermuda 集成在跟踪 52 个设备、另一台 26092430 模块的电压实体实时更新、iPad 距离实体持续刷新），是这台模块的接收特别差。

### 7.7 HTTP 500 的归属

上述失败在 REST 上表现为 **HTTP 500 "Server got itself in trouble"**。对照测试表明这不是集成缺陷：对 HA 自身的标准校验错误（`select_option` 传非法 option）返回的**同样是 500**。集成抛的是带可操作信息的 `HomeAssistantError`，消息在 HA 日志里可见。

另外实测：该实例的 ESPHome 节点是**旧配置**（无 `api.respond`），`?return_response` 被拒（`Service does not support responses`），因此 `docs/home-assistant.md` 所述「节点拒绝会变成失败的服务调用」这条路径在本环境**处于 fire-and-forget**，未能验证。

### 7.8 本节未覆盖

1. **发送端迟滞分支**：`SENDER_RSSI_HYSTERESIS` / `SENDER_TIME_HYSTERESIS` 只在多个接收端同址竞争且 RSSI 接近时才起作用。本环境同时缓存该地址的接收端不足以构造 3 dB 带内的多候选，因此只确认它们没有破坏正常路径，未验证其抑制效果。
2. **HA 前端与自动化迁移**：全部经服务 API 驱动，未验证仪表盘渲染；实例装的是 1.1.0（按钮在 1.1.0 已移除），因此 1.0.0 → 1.1.0 的三按钮实体清理与自动化迁移未实测。
3. **31 字节与 29 字节的接收率对照**：本意是拿同实例的 26092430 模块做对照，但那 4 台在该 HA 里根本收不到（`last_reported` 停在重启时刻），无法构成对照。
4. **节点侧载荷边界**：只验证了正常 30 字节控制帧与其结果，未测异常载荷。

## 8. 覆盖与未覆盖

**本次实机覆盖**：候选包身份、PC BLE OTA 刷写、A0 版本判据、广播版本字段同步、ADV_IND 空口 31 字节、扫描响应设备名、加密 BTHome 认证与解码（15 字节明文含 `0x0F`）、counter 节拍与单调性、跨重启 counter 不重用与密钥保留、电压/距离奇偶交替、A6 保持低/高/自动、FE 后保持、认证控制路径正例与 5 类拒绝、连续切换的逐帧组合；**真实 HA 实例上的实体契约、可用性语义、Reconfigure 流程、三版本部署与升级、以及经 HA 的端到端控制（1.1.3 十三次真实发送全部生效）**。

**未覆盖**：

1. **无雷达快照的 11 字节布局**：本次采集期间模块始终有有效快照（全部 15 字节）。`plaintext_bytes=11` 的实机路径未出现。
2. **密钥轮换（A6 参数 4）与恢复出厂（A2）**：会改变设备状态并要求重新配对 HA，本次未执行；bindkey 持久化、坏记录恢复、模糊写入等状态语义仍沿用既有文档结论。
3. **掉电持久化**：本次只有 OTA 重启，没有真正断电重上；counter 预留区间与密钥在 OTA 重启后正确，掉电路径未单独验证。
4. **空口射频测量**：采集得到的是接收端交付的字段，counter 速率是固件节拍，不是射频占空比或丢包率测量。被动扫描下也测不到扫描响应时序。
5. **另两台 LD2401**（`…72:AE`、`…89:94`）密钥与本机不同，仅用于广播厂商段对照，未做功能测试。
6. **ESPHome 节点侧对 `payload` 的边界处理**与节点应答路径：本实例节点未启用 `api.respond`（§7.7）。
7. **代理主动扫描模式的长期配置**：本次只在测试期间临时切换并已恢复为被动；未改动节点配置，主动模式的稳定性与 HA 侧影响未评估。
8. **HA 侧未覆盖项**见 §7.8（发送端迟滞分支、前端渲染、1.0.0 按钮迁移、31/29 字节接收率对照）。

## 9. 问题与遗留

### TST-01（低，已关闭）`docs/protocol.md` 未记录广播版本字段的空口排列

- 现象：文档称广播版本块与 A0 戳「两者一致」，实测空口厂商段里 4 个版本字节以两个 16 位小端字排列（`24 31 26 09`），而镜像内两处戳同为 `31 24 09 26`。
- 影响：仅影响人工判读，不影响版本判据（A0）与设备识别；对照两台 26092430 模块，该字段排列一致。
- 处置（经用户授权修改维护者文件）：`docs/protocol.md` 新增「扫描响应与空口版本字段」小节，给出 2.50.26092431 的镜像／空口对照；`docs/firmware-implementation.md` 的版本戳段落补一句空口为两个 16 位小端字并交叉引用。A0 仍是权威判据。

### TST-02（低）ESPHome 代理默认被动扫描，收不到扫描响应

- 现象：经 ESPHome BLE 代理采集时记录不到设备名与版本厂商段，主机主动扫描则可取得。
- **默认是被动扫描**：ESPHome `bluetooth_proxy` 的 `active` 默认 `false`，即 Passive 扫描，不发 `SCAN_REQ`，因此模块不会回扫描响应（设备名与版本厂商段都在扫描响应里）。这与 Node 侧配置一致，不是后端丢字段。
- **实测对照**（同一节点，`local/scanner_mode.py`，用后恢复）：

  | 节点扫描模式 | 雷达 MAC 收到的原始数据 |
  | --- | --- |
  | 被动（配置态） | 仅 `0x01` Flags + `0x16` 服务数据（`ad_bytes` = 31） |
  | 临时切为主动 | 出现 `0xff`（`01 24 02 50 24 31 26 09`）与 `0x09`（`HLK-LD2401_09FB`），节点把扫描响应并入同一条原始数据 |

  切回被动后复查：`ad_bytes=31`、仅有 `0x01`/`0x16` 两段，模式已恢复。
- 影响与边界：需要设备名或只测广播长度时用 `capture_ble.py` 的主动扫描；用代理测量 `ad_bytes` 时须确认节点为被动模式，否则该值会包含扫描响应（实测合并后为 55 字节），不能当作 ADV_IND 长度。
- 结论：无需修改代码，机理与边界已写入 `Tester/README.md` 与 `capture_ble_proxy.py` 的说明。

### TST-03（中，交接身份）`metadata/firmware-26092431.json` 仍未反映本次测试

- 该文件属维护者所有，本次未改动。测试后应更新：`hardware_status`、`coverage`（指向本报告）、必要时 `independent_audit_status`。
- 交付身份需抉择：实测绑定 `343a0d2`，而 HEAD 已前移 `7fa6a7a`；§1.1 已证明同一字节可在干净 `7fa6a7a` 上以 release 复现，因此前移不改变任何固件字节，但需要维护者决定以哪个 commit 作为交付身份，并从该 commit 重建 release 绑定与 handoff 记录。
- 本次范围：`Tester/` 下的工具、README、requirements 与本报告；`Auditor/` 的审计工具身份与 `Auditor/README.md`；`metadata/role-tool-sources.json`；以及经用户授权修改的 `docs/protocol.md`、`docs/firmware-implementation.md`。`Developer/` 源码与候选二进制未改动，候选 UFW 仍为 `367df6fd…5872a`。
- 提醒：`metadata/`、`docs/` 归维护者；Auditor 已按此边界只动审计工具身份那几行，Tester 的文档改动也建议由维护者提交前统一复核。
- **后续状态（维护者，2026-10-01）**：`metadata/firmware-26092431.json` 已更新为交付记录（`hardware_status=USER_CONFIRMED_TESTED`、`independent_audit_status=COMPLETED`、`coverage` 指向本报告）。交付身份已选定：沿用 Build ID `26092431-mode-feedback-r1`，并由干净提交的 release 报告绑定；因该选择只更换构建 commit、不改变固件字节，本报告的实机结论继续有效。提交随后按用户要求重签名，SHA 映射见报告头部与 [审计报告 §12.1](../../Auditor/reports/26092431-mode-feedback-r1.md)。

### AUD-02 状态

- **已修复**（Tester 侧）：解码器支持 `0x0F`，离线夹具覆盖 13／15／11 字节布局，实机 15 字节帧全部解码通过。
- 分派给 Developer 的 AUD-01（`bthome-ble` 最低版本声明与私有接口依赖）、AUD-03、AUD-05 不在本次测试范围。

### A1 / AUD-04 状态（已关闭：由 Auditor 修复，Tester 复验）

- 现象复核（在候选构建的 `tail_plain.asm` 上实测）：`Auditor/tools/q32s_xref.py` 的 `IMM = re.compile(r'= 0x([0-9a-f]{5,8})\b')` 只认十六进制立即数，本固件反汇编里**十六进制形式 0 处、十进制形式 25 处**，因此 `refs 0x4514` 报 0 处引用。
- 反汇编行形如 `r0 = 17684 <…hooks.s.o+0x4514 : 4514 >`：除十进制操作数外，尾部符号注记 `: 4514 >` 也直接给出十六进制值，可作兼顾两种写法的匹配点。
- 影响范围：`refs` 结论反向；`callers`／`chain`／`sites` 走 `BRANCH` 正则，不受影响。
- 处置：`Auditor/tools/q32s_xref.py` 属 Auditor 工具，按用户裁定交由 Auditor 修复，并需同步重算 `metadata/role-tool-sources.json` 中该文件的 `distribution_sha256`（若同时给 `Auditor/tools/selftest.py` 增加断言，该文件哈希也需一并更新）。本次测试未改动这两处。
- **后续观察（2026-10-01 04:32，非 Tester 改动）**：同一工作树上的 Auditor 会话已完成该修复——`IMM` 改为 `\br\d+ = (0x…|[0-9]+)\b` 并新增 `immediate_loads()`，只在寄存器加载操作数上匹配，避免把分支注记或比较式（如 `if (r0 != 0x1e5000)`）当作立即数；`selftest.py` 增加了正反例断言。Tester 侧独立复验：

  ```text
  python -B Auditor/tools/q32s_xref.py --asm build/26092431-mode-feedback-r1/tail_plain.asm refs 0x4514
  0x1e2abe2  r0 = 17684 <…hooks.s.o+0x4514 : 4514 >
  0x1e2acae  r1 = 17684 <…hooks.s.o+0x4514 : 4514 >
  2 immediate load(s) of 0x4514
  python -B Auditor/tools/selftest.py
  PASS: Auditor local imports, CRC/header rejection, Q32S fixture, CLI entries
  ```

  这与审计报告 §4 对 26092431 的计数（`0x4514` 由 1 处增至 2 处）一致。Tester 侧另做逐址交叉复验（候选 vs 26092430 参考）：

  ```text
  refs 0x4514   → 候选 2 处 (0x1e2abe2, 0x1e2acae)；参考 1 处 (0x1e2ac5a)
  refs 0x465c   → 候选 2 处 (0x1e2a638, 0x1e2ae00)；参考 2 处 (0x1e2a638, 0x1e2adac)
  refs 0x1e5000 → 候选 2 处 (0x1e2ab22, 0x1e2acc0)；参考 2 处 (0x1e2ab22, 0x1e2ac6c)
  ```

  与 Auditor 给出的三址结果逐条吻合，也与审计报告「`0x4514` 由 1 处增至 2 处、`0x465c` 与 `0x1e5000` 引用数不变」的结论一致。
- **已关闭**：Auditor 已重算并合并身份记录，`metadata/role-tool-sources.json` 现为 13 条；Tester 逐条核对全部与磁盘一致（0 处不匹配），`tools/check_repository.py --protocol` 恢复全绿（`PASS: 80 public files … protocol parity`）。Auditor 未改动三个复制来源的 `sha256`（上游来源身份），符合「保留原始来源身份」；该字段本就不由该检查校验。

## 10. 复现命令

```text
# 离线
python -B Tester/tools/check_capture.py
python -B tools/check_repository.py --protocol

# 身份前移验证：干净 worktree 上的 release 构建（§1.1）
git worktree add --detach local/wt-2143a11 2143a11
python -B local/wt-2143a11/Developer/tools/build.py --version 26092431 \
    --build-id 26092431-audit-fixes-wtverify --release \
    --stock vendor/LD2401_2.50.24110415.ufw --output-dir local/wt-2143a11/local/verify-2143a11
git worktree remove --force local/wt-2143a11

# 设备（需授权；MAC/串口/节点/密钥按现场替换，均为本地忽略输入）
python -B Tester/tools/a6.py --port COM3 --version
python -B Tester/tools/a6.py --port COM3 --read-key
python -B Tester/tools/jl_ota_pc.py --mac 82:CF:…:09:FB --file build/26092431-mode-feedback-r1/LD2401_2.50_26092431.ufw --trace local/ota-26092431-trace.json
python -B Tester/tools/capture_ble_proxy.py --host <节点> --apikey-file local/esphome.key --mac 82:CF:…:09:FB --seconds 60 --output local/capture-26092431-rate.json
python -B Tester/tools/decode_capture.py --capture local/capture-26092431-rate.json --key-file local/bindkey.txt --output local/decoded-26092431-rate.json
python -B Tester/tools/control_frame.py --mac 82:CF:…:09:FB --key-file local/bindkey.txt --capture local/capture-26092431-rate.json --mode 1
python -B Tester/tools/send_control.py --host <节点> --apikey-file local/esphome.key --payload <60 位 HEX>

# 真实 HA 实例（需授权；基址/令牌/节点按现场替换，均为本地忽略输入）
python -B Tester/tools/ha_probe.py --token-file local/ha-token.txt --insecure
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure --dir local/ha-installed pull
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure --dir local/ha-installed push   # 之后重启 HA
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure verify
python -B Tester/tools/ha_out_test.py --token-file local/ha-token.txt --insecure \
    --entity select.ld2401_<末4位>_out_mode --mac 02:00:00:00:00:01 --key-file local/bindkey.txt \
    --proxy-host <代理节点> --apikey-file local/esphome.key
```

环境：Windows，Python 3.12.14（仓库 `.venv`），bleak 3.0.2、cryptography 50.0.2、pyserial 3.5、aioesphomeapi 46.6.0、aiohttp 3.14.3；串口 COM3（256000 8N1）；ESPHome 代理节点已启用 `ble_proxy`；真实 HA 2026.9.4。设备交付的原始捕获、解码、OTA trace、HA 凭证与节点密钥保存在 Git 忽略的 `local/`；每次集成部署前的备份保存在 `local/ha-installed*/`。

## 11. 结论

对 Build ID `26092431-mode-feedback-r1` / UFW `367df6fd…5872a`（实测时 commit `343a0d2`；同一字节已在干净 `7fa6a7a` 上以 release 复现，见 §1.1）：

- 刷写成功，A0 判据与广播版本字段同步指向 **2.50.26092431**，同一模块刷写前后仅版本字节变化。
- 新固件的 `0x0F` 手动保持与 `0x10` 物理电平在每个认证帧中一致，与 A6 和认证控制两条写入路径的预期完全吻合；控制路径的认证、鲜度、防重放与目标校验共 5 类拒绝全部生效。
- counter 节拍 2.00 Hz、全程单调、跨 OTA 重启不重用，未见重复计时器或帧格式越界（ADV_IND 恰 31 字节）。
- 未观察到混合「保持/电平」过渡帧，也未观察到 31 字节帧被截断或拒绝。
- **真实 HA 实例（§7）**：1.1.0 的发送端选择会退回字母序第一的节点，而该节点射频到不了本模块，导致命令返回 200 却**完全无效**（3 次真实发送 0 次生效）；用 Reconfigure 显式指定可达节点后 3/3 生效，隔离出缺陷位置。1.1.1 起回退路径被修正，1.1.3 改为「按新鲜接收时间与 RSSI 排序 + 过滤无效 RSSI + 迟滞，且不再有任意回退」，**13 次真实发送全部生效、0 次无效**。实体契约、可用性语义（仅 26092431 那台可用）、Reconfigure 流程与三次升级的实体身份稳定性均在实机成立。
- 工具与仓库层面：AUD-02 已由 Tester 修复并实机验证，AUD-04 已由 Auditor 修复且经 Tester 逐址复验，Tester 新增 3 个真实 HA 测试工具并登记身份，**17 条**角色工具记录全部一致，`tools/check_repository.py --protocol` 全绿。

**本报告是 26092431 的实机测试结论，但覆盖有限**：无快照 11 字节布局、密钥轮换/恢复出厂、断电持久化、射频测量，以及 §7.8 的 HA 侧未覆盖项（发送端迟滞分支、前端渲染、1.0.0 按钮迁移、31/29 字节接收率对照）均未验证。另需注意本部署的一个环境事实：该 HA 对这台模块的认证接收率仅约 0.06 Hz，与 2 Hz 发送节拍差距很大，因此即使路由正确，仍有约七分之一的选择会以「等不到新 counter」失败（1.1.3 的 15 次尝试中 2 次）——这是接收质量约束（1.1.0 起各版本等待窗口与常量相同），不是集成的路由缺陷。交付身份前移与 `metadata/firmware-26092431.json` 更新属于维护者。
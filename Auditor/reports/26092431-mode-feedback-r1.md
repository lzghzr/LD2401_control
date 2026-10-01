# LD2401 26092431 独立审计报告

- 角色：Auditor
- 审计对象：commit `2603db5471e0e56a36ceb896a7ad50b3c16e3c4e`（分支 `codex/out-mode-feedback`），Build ID `26092431-mode-feedback-r1`；审计后修复复核见 §11（commit `2143a11`）
- 固件：`LD2401_2.50_26092431.ufw`，607840 字节，SHA-256 `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`
- HA 集成：`ld2401_control` 1.1.0
- 审计时间：2026-10-01
- 审计结论：**静态与离线检查全部通过，未发现固件或集成实现缺陷；AUD-01 / AUD-02 / AUD-03 / AUD-04 / AUD-05 均已修复并经复核（§11）；审计后修复提交未改变固件与 HA 实现字节；硬件、真实 HA 实例与空口行为未验证。**

## 1. 身份与输入核验

审计开始时工作树为 `2603db5`，`git status --porcelain` 为空。`build/`、`local/` 为 Git 忽略目录，本次审计未改写任何已交接产物（复核后候选包与构建报告哈希不变；AUD-02 / AUD-04 的后续修复同样未触及这两份产物）。

| 对象 | 记录值 | 实测 |
| --- | --- | --- |
| 候选 UFW SHA-256 | `367df6fd…5872a` | 一致 |
| 构建报告 SHA-256 | `48700593…195e` | 一致 |
| `ld2401_control-1.1.0.zip` | `16e4d26a…9a0`，12 文件 | 一致，12 个成员逐一与 commit 内容相同 |
| `LD2401-source-26092431.zip` | `4c4fa800…2d7`，73 文件 | 一致，73 个成员逐一与 commit 内容相同 |
| 原厂 UFW SHA-256 | `3e518750…b9a7` | 一致 |
| 26092430 参考 UFW | `7e74ed70…dd7d` | 一致 |
| 工具链 clang / q32s-ld / llvm-objdump | `0ae79bfb…` / `d279ad52…` / `18c3c292…` | 三个可执行文件哈希均一致 |

`metadata/firmware-26092431.json` 的 `broadcast.hold_object=0x0f`、`hold_source=0x4514`、`layout.tail_end=0x1e2b114`、`context_bytes=100` 与实测一致；`hardware_status=NOT_TESTED`、`independent_audit_status=PENDING` 与本报告前的状态相符（本报告完成后应更新为已审计，属维护者动作）。

旁证：更早的 review 构建 `build/26092431-mode-feedback-review1`（源 commit `dcde8d2`，dirty）记录的应用哈希同为 `367df6fd…5872a`，与本次审计的 clean 构建一致，说明最终候选是该固件在干净提交下的重建，固件字节未在提交前后发生漂移。

## 2. 独立重编译：源码到候选包的绑定

`Auditor/tools/reproduce_candidate.py` 不使用 `Developer/tools/build.py`，自行执行版本占位符替换、`clang -target q32s -Os -fno-builtin [-DLD24_OUT_MODE_STATUS]`、`q32s-ld -T Developer/linker/layout.ld`，再用 Auditor 自带 ELF 读取器把每段已分配节与候选包字节比对。

候选（`--version 26092431`，含 `LD24_OUT_MODE_STATUS`）：

```text
ok  image.length          package app 176116 bytes, linked tail ends 0x1e2b114 (176116 bytes)
ok  sections.in_package   20 allocated sections compared, mismatched: none
ok  image.pc_limit        limit 0x1e2b114, linked tail end 0x1e2b114
ok  sections.shipped_elf  sections differing from tail_plain.elf: none
ok  asm.requires.0x4514   literal in .crypto disassembly
```

参考（`--version 26092430 --define ""`）同样 7/7 通过，链接尾端 `0x1e2b0c0`，应用 176032 字节，与记录哈希一致。由此证明：

1. 该 commit 的源码 + 固定工具链确实生成候选包内每个字节，`build-report.json` 不是唯一凭据；
2. `LD24_OUT_MODE_STATUS` 是唯一开关，缺省时不产生任何差异字节（26092430 路径逐节相同）；
3. 我独立生成的 `hooks_gen.s` 与交接目录中的同名文件字节相同。

## 3. 封装、布局与补丁（`Auditor/tools/fw_audit.py`）

```text
36 ok, 0 failed, 0 skipped
```

要点：容器声明长度与文件一致；两份镜像 flash CRC 与 8 个嵌套条目 CRC 全部有效；两份镜像应用区同为 176116 字节且完全一致；`factory_key` 保留；BTIF/EXIF 偏移与大小未移动；`PRCT` 大小严格等于 VM 起点；VM 起点固定为 `0x2f000`（镜像 0）与 `0x2e000`（镜像 32），VM 末端保持；VM 前余量 3066 / 2554 字节；执行上限立即数等于镜像末端；A0 版本戳与广告版本块立即数均为 `26092431`；与原厂镜像的差异字节全部落在报告声明的补丁区与尾段内。

补丁与钩子复核（Stock 侧由我从原厂镜像反汇编独立确认，见下）：7 个钩子站点的原厂前像与 `STOCK_PREIMAGE` 一致，补丁后字节解析到的尾段函数分别为 `report_hook`、`scanrsp_hook`、`a6_tail`、`a2_tail_hook`、FE 等价宽度存储、`refresh_start`、`rx_report_shim`。

## 4. 变更范围：只有新增的 `0x0F` 对象

对比 26092430 参考与 26092431 候选的链接结果：

| 节点 | 26092430 | 26092431 | 内容 |
| --- | --- | --- | --- |
| `.guard .scanrsp .capture .a6 .a2 .lock` | 同地址 | 同地址 | 相同 |
| `.crypto` | 0x1e2a638，1988 | 0x1e2a638，2072 | 新增 84 字节 |
| `.cdata .aes` | 0x1e2adfc / 0x1e2ae0c | 0x1e2ae50 / 0x1e2ae60 | 内容相同，整体后移 84 |
| `.rxshim .rxcode .rxconst` | 0x1e2aec4 起 | 0x1e2af18 起 | 内容相同，整体后移 84 |
| 钩子节 | 同地址 | 同地址 | 仅分支位移随被调函数移动 |

`.start_hook`、`.rx_report_hook`、`.rxshim`、`.rxcode` 逐字节不同的原因已逐条解析：分支目标仍是同一函数（`refresh_start` 0x1e2ada6→0x1e2adfa、`rx_report_shim` 0x1e2aec4→0x1e2af18，均为 +84），`.version` 差异即版本数字节。`build_live` 与 `bthome_tick` 的栈帧在 26092430/26092431 中同为 `sp += -20` / `sp += -32`，本次改动没有增加栈占用，也没有引入新的钩子或新的 RAM 全局地址：`0x465c`（RX 上下文指针）2 处引用不变，`0x1e5000` 2 处不变，`0x4514` 由 1 处（`rx_apply_pending` 写入）增加到 2 处（新增 `build_live` 采样读取）。

源代码层变更同样只有 `Developer/src/payload.c`（+20 行）；`hooks.s`、`scanrsp.c`、`rxcontrol.c`、`layout.ld` 在本 commit 中未改动。

## 5. 新功能实现审查

### 5.1 固件侧（`build_live`，`#ifdef LD24_OUT_MODE_STATUS`）

机器码逐条核对（候选反汇编 0x1e2abe2–0x1e2ac3e）：

- 双读 `0x4514` 的一致性检查被保留：`r3 = b[0x4514]`，`r2 = b[0x1e5000]`，`r4 = b[0x4514]`，不一致则 `return 0`（跳 0x1e2ac40 返回）；
- 插入位置 `pos = (n == 13 && (counter & 1)) ? 4 : 7` 编译为 `r0 = 7 / r0 = 4` 两条路径，与两种帧布局对应；
- 右移两位的循环编译为 `r5 = base + i` 形式，读写下标为 `i-1 → i+1`，等价于 C 的 `plain[i+1] = plain[i-1]`；最大写入下标 14（`plain[16]` 之内）；
- 随后写入 `0x0F`、`hold != 0` 布尔，`n += 2`，`build_frame_impl` 以 `n=15`（有快照）或 `11`（无快照）调用；
- 目标地址立即数只有 `0x4514` 与 `0x1e5000`，新增代码不含任何函数调用。

由此得三种布局的对象顺序全部递增，明文 15 / 11 字节，整帧（含 `02 01 06` Flags）31 字节，落在 legacy AD 上限之内；写入范围不超过 `struct ctx.buf[32]`。

`Developer/tools/check_telemetry.py` 在宿主 LLVM 上执行同一份 C 源码的 80 个用例（我复现通过）：

```text
PASS: 80 actual C telemetry/CCM fixtures; AD bounds, MIC, object order and measurements
```

覆盖两种布局、状态 0–3、counter 奇偶、hold × level 四种组合，并校验 `0x0F` 出现与 `-D` 一致、对象 ID 递增、明文长度、MIC、`out` 缓冲区不被越界写入。

### 5.2 `0x4514` 语义的独立确认

我把原厂应用镜像按真实地址包装成 ELF 后反汇编（`local/auditor-stock/`），得到：

```text
0x1e012f4  1b f9 d4 a1   b[r10 + 468] = r11      # 原厂 A6 手动保持置位
0x1e0168c  16 f9 d4 01   b[r0  + 468] = r6       # 原厂 FE 清理同一标志
0x1e04c82  00 f9 05 b0   r0 = b[r11 + 5] (u)     # 原厂报告门控字节
```

候选把 `0x1e0168c` 改为 `b[r0 + 72] = r6`：位移差 468−72 = 396 = 0x18C，正好等于 `0x4514 − 0x4388`，说明改写的目标确实是 `0x4514` 旁的配置会话字节 `0x4388`，且同一基址寄存器族（`r10`/`r11`）同时给出 `+468` 与 `+5` 两个锚点。结合 `rx_apply_pending` 自身写入 `0x4514` 并直接驱动 `0x1e5000` bit0，可以确认：

| 命令 | 固件写入 | 同帧广播 | HA 解释 |
| --- | --- | --- | --- |
| 0 保持低 | `0x4514=1`，GPIO 位=0 | `0x0F=1`，`0x10=0` | `hold_low` |
| 1 保持高 | `0x4514=1`，GPIO 位=1 | `0x0F=1`，`0x10=1` | `hold_high` |
| 2 恢复自动 | `0x4514=0` | `0x0F=0`（电平任意） | `auto` |

### 5.3 HA 侧

`Auditor/tools/ha_feedback_check.py` 自行按固件布局构造 BTHome v2 加密服务数据（nonce = MAC 显示序 + `D2 FC 41` + counter LE，4 字节 MIC），用真实库与真实 HA 类跑通：

| 配置 | 结果 |
| --- | --- |
| bthome-ble 3.24.0 + HA 2026.9.3 官方 processor 源码 | 7 ok / 0 failed |
| bthome-ble 3.24.0 + HA 2026.3.0 官方 processor 源码 | 7 ok / 0 failed |
| bthome-ble 3.9.1 + HA 2026.3.0 / 2026.9.3 | 6 ok / 0 failed / 1 skip（该版本解密辅助函数签名不同，无法计数解密次数） |

覆盖：两布局四种 hold/level → 模式（2/2/0/1）；同 counter 重放、回退 counter、MIC 篡改均不改变状态；密钥轮换清空旧反馈并接受新纪元；13 字节旧固件帧被接受但模式为 `None`（不会继承缓存 hold）；通过官方 `PassiveBluetoothProcessorCoordinator.async_register_processor` 注册后，一次广播只解密一次、回调送达一次、卸载后处理器被移除；`OPTIONS`/`MODE_OPTIONS` 与 `const.py` 模式号、`strings.json`/`zh-Hans.json` 状态键一致。

同时确认 `shared.py` 的做法与官方实现相容：processor 的 `update_method` 收到的是 coordinator `_DataT`（`SensorUpdate`），`consume()` 返回 `PassiveBluetoothDataUpdate()` 可满足 `async_handle_update` 的类型校验，`restore_key=None` 避免污染 BTHome 的持久化恢复数据；`accept()` 依据 `bindkey_verified`/`decryption_failed`/`encryption_scheme`/`downgrade_detected` 与帧内 counter 交叉校验，3.9.1 缺少 `downgrade_detected` 时由 `getattr(..., False)` 与 `payload[0] != 0x41` 双重兜底。`_binary_sensor_values_updates` 在库中跨次累积，值对象每次 `update_binary_sensor` 重建，因此“比较对象身份判定本帧出现的对象”这一机制成立。

## 6. Developer 交接声明核对

| 声明 | 结果 |
| --- | --- |
| 80 个 C 遥测用例通过 | 复现通过 |
| 11 个 HA 行为测试通过（bthome-ble 3.24.0） | 复现通过 |
| 同一组测试在 bthome-ble 3.9.1 下通过（`developer_checks.bthome_ble_versions`） | **不可复现，11 通过 10，1 失败**，见 AUD-01 |
| 11 个测试在官方 2026.3.0 / 2026.9.3 processor 类下通过 | 复现通过（`HA_PROCESSOR_SOURCE`） |
| 仓库协议检查通过 | 复现通过（75 个公开文件） |
| 源码归档与 commit 一致 | 独立逐成员比对通过（12 / 73 文件） |
| 26092430 参考哈希复现 | 独立重编译通过 |
| 候选 no new hook / RAM / VM 边界不变 | 通过 |
| 实机与真实 HA 未验证 | 与本报告一致 |

## 7. 问题清单

### AUD-01（中，Developer）最低 bthome-ble 版本声明不可复现，且测试依赖私有接口

- 证据：用仓库内 `local/bthome-3.9.1` 副本运行 `python -m pytest Developer/tests` 得到 `1 failed, 10 passed`；失败点 `test_shared_updates_decrypt_once`，`assert accepted == [True]` 实际为 `[False]`。
- 机制：bthome-ble 3.9.1 的 `_decrypt_bthome(self, service_info, payload, mac, sw_version, adv_info)` 是五参数私有方法，而测试用单参数包装替换它；调用处的 `TypeError` 被解析器内部 `except (ValueError, TypeError)` 吞掉，从而“解密未发生”，`accept()` 依据 `bindkey_verified=False` 正确拒绝。集成实现本身在 3.9.1 下正常（本报告 §5.3）。
- 附加风险：CI 安装 `bthome-ble>=3.9.1` 无上限，任何改变该私有签名的上游版本都会让该测试失败。
- 复现（3.9.1 源码副本缺少 `home_assistant_bluetooth` 依赖，用 Auditor 的最小替身插件补齐，该依赖只用于类型注解）：

  ```text
  PYTHONPATH=local/bthome-3.9.1;local/auditor_plugins python -B -m pytest Developer/tests -q -p no:cacheprovider -p ha_bluetooth_shim
  → 1 failed, 10 passed   (FAILED test_mode_feedback.py::test_shared_updates_decrypt_once)
  ```

- 建议：断言可观测行为（`bindkey_verified`、`decryption_failed`、是否接受）而不是替换私有方法；若保留计数，则按签名自适应。修正后重新记录版本声明。
- **后续状态（commit `2143a11`）**：已按建议重写为 `test_shared_updates_use_authenticated_parser`——断言 `bindkey_verified`/`decryption_failed`/已接受更新/认证 counter/模式，并覆盖一次 MIC 篡改后恢复；不再替换或计数私有解密方法。CI 改为 `bthome-ble` 3.9.1 与 3.24.0 的版本矩阵并安装真实 `home-assistant-bluetooth` 兼容包。我复测：两版本各 22 通过（原 11 HA + 新增 11 布局测试）。详见 §11。

### AUD-02（中高，Tester 侧准备度）Tester 解码器不支持新对象，26092431 帧全部无法解码

- 证据：`Tester/tools/decode_capture.py` 的 `OBJECTS` 无 `0x0F`；用其函数解码同一密钥构造的 15 字节帧得到

  ```text
  26092430 13-byte decoded {...}
  26092431 15-byte REJECTED ValueError unsupported object 0x0f at plaintext offset 4
  ```

- 影响：`decode_records` 会把每一帧记为 error，`main` 返回 1；Tester 无法统计新候选的 counter 速率或核对 `0x0F`。同时 `Tester/tools/check_capture.py` 的合成夹具仍是 13 字节，因此仓库协议检查显示 PASS 而新格式实际不可解码。
- 建议（Tester 维护范围）：在 `OBJECTS` 增加 `0x0F: ('hold', 1, 1)`，并让离线夹具覆盖 15 / 11 字节两种新布局，以便实机测试阶段能直接产出结论。
- **后续状态（审计结束后）**：Tester 已在工作树完成该修正——`OBJECTS` 增加 `0x0f: ('hold', 1, 1)`，夹具扩到 5 种明文布局。用同一密钥复测，15 字节帧解出 `hold=1, out_high=1, distance_mm=1230`，11 字节无快照帧解出 `hold=0, voltage_v=3.2, out_high=1`。该修正属于审计对象 `2603db5` 之后的工作树变更，不在本次审计的 commit 内。

### AUD-03（低，Developer 报告与文档措辞）`reserved_entries_unchanged=false` 与“验证保留条目”的表述

- `build-report.json` 两个镜像均为 `"reserved_entries_unchanged": false`。核对条目后原因明确：带 `0x10` 标志的条目是 VM 与 PRCT，二者按设计随应用增大而移动；BTIF/EXIF 未移动（`fw_audit.py` 的 `layout.image*.BTIF/EXIF` 检查通过）。
- 但 `Developer/verification-26092431.md` 称构建器“validates … reserved entries”，而构建器只是记录该字段，未对其断言，也未断言 BTIF/EXIF 不动。
- 建议：把该字段改为按条目分类（“VM/PRCT 允许移动、BTIF/EXIF 必须不动”）并加上断言，或修正文档表述。
- **后续状态（commit `2143a11`）**：新增 `flash_layout.check_reserved_layout()`，逐条目断言元数据（`header`/`flags`/`reserved`/`last`/`data_crc`）一致，并按策略断言几何：VM 起点等于固定边界且末端保持，PRCT 从 0 到 VM 起点，BTIF/EXIF 偏移与大小不变；报告字段改为 `reserved_layout_validated` 与 `reserved_entry_checks`（含 before/after 坐标）。另把 `OUTPUT.write_bytes()` 移到全部不变量之后，失败构建不再留下输出文件。我复测后续构建报告：`reserved_layout_validated=true`，BTIF 249856/4096、EXIF 253952/4096 前后一致。详见 §11。

### AUD-04（低，Auditor 工具缺陷）`q32s_xref.py refs` 只识别十六进制操作数——已修复

- 症状比初判更严重：旧正则 `= 0x([0-9a-f]{5,8})` 要求操作数带 `0x` 前缀，而该工具链的 `llvm-objdump` 把寄存器加载操作数**全部**打印为十进制（如 `r0 = 17684 <…+0x4514 : 4514 >`）。在 26092431 与 26092430 两份完整反汇编中，旧正则命中数均为 **0**，即 `refs` 对任何地址都返回 0 处引用，不只是十进制地址。
- 连带缺陷：旧正则匹配裸子串 `= 0x`，因此 `if (r0 != 0x12345)` 这类比较也会被当成“加载”——在原厂镜像反汇编中确实存在这种形态。
- 本次审计未依赖该子命令：证据由 `reproduce_candidate.py --ref` 独立扫描取得。审计期间示例判定该修正属维护者范围（需同步刷新 `metadata/role-tool-sources.json`）而未改动；Tester 复核后确认归属 Auditor，现已修复。
- 修复内容：`IMM` 改为 `\br\d+ = (0x[0-9a-fA-F]+|[0-9]+)\b`，只匹配寄存器加载的操作数本身（分支注解 `<… : 地址 >` 是跳转目标，不计入）；新增 `immediate_loads()`；`selftest.py` 增加两条合成断言与一条端到端子命令断言（十进制、十六进制、比较、非加载四种形态）。
- 修复后复测（`Auditor/tools/q32s_xref.py`，`distribution_sha256` 已刷新为 `dd5e6d46…bd67`）：

  ```text
  refs 0x4514   → 0x1e2abe2, 0x1e2acae   (2 处；26092430 参考为 1 处)
  refs 0x465c   → 0x1e2a638, 0x1e2ae00   (2 处)
  refs 0x1e5000 → 0x1e2ab22, 0x1e2acc0   (2 处)
  ```

  三组结果与 §5.1 使用的独立扫描逐址一致，本文档 §5.1、§4 的引用计数结论不变，只是现在可由规范工具直接复核。
- 遗留说明：低位地址仍可能与普通常量（对象长度、掩码）相等，输出按“候选引用”表述，需人工判定。

### AUD-05（低，文档）升级说明未提到新增的 BTHome 实体

- 内置 BTHome 集成会把 `0x0F` 解析为 `generic` 二进制传感器，升级后用户会多出一个实体；`docs/home-assistant.md` 的升级小节只说明了按钮实体被移除。
- 建议：在升级小节补一句“升级固件后内置 BTHome 集成会新增一个 generic 二进制传感器（手动保持）”。
- **后续状态（commit `2143a11`）**：`docs/home-assistant.md` 升级小节已补充该说明，含 on/off 含义与“选择器结合该传感器状态与物理电平”的关系。

## 8. 未解决问题与覆盖边界

以下内容**本次审计不能证明**，需实机或后续证据：

1. **31 字节 legacy 广播的实机接受度**：26092430 实测帧为 29 字节，本候选恰为上限 31 字节。栈层是否接受、空口是否完整、接收端是否合并/截断，均无离线证据；手册已将其列为待验证项。
2. **采样瞬态**：固件只能检测“采样窗口内 `0x4514` 发生变化”，无法观测写入方的先后顺序；若原厂 A6 先写保持标志、后驱动引脚，仍可能广播出一帧 `hold=1` + 旧电平的自洽但过渡状态（500 ms 后收敛）。属可接受的瞬态，但“同帧一致”不等于“无过渡态”。
3. **`build_live` 返回 0 的推迟路径未被任何测试执行**：宿主夹具的 hold 输入是稳定的，无法触发双读不一致；该分支只经反汇编核对。同时 `bthome_tick` 的 `failed`（len==0）路径也无夹具覆盖。
4. **真实 HA 实例**：未启动 Home Assistant。`select.py` 在 `__init__` 中预置 `entity_id`、旧按钮实体清理、UI 渲染与自动化迁移均未在真实实例验证；`docs/home-assistant.md` 关于 “HA 2024.8.0 引入 `entry.runtime_data`” 的说法未独立核实。
5. **依赖版本**：`metadata/firmware-26092431.json` 的 `0x4514`、B2 扫描状态字节 `0x4345` 等含义继承自已验参考候选的反汇编结论；本次仅独立确认了与本次改动直接相关的 `+468 / +5` 两个锚点与 FE 位移差。
6. **随机数强度、掉电持久化、BLE 时序、OTA/恢复**：沿用既有手册限制，未在本次改动范围内重新验证；本次改动未触及这些路径。
7. **交接身份的可追溯性**：Build ID 字符串与 `handoff.json` 只存在于被忽略的 `build/` 目录；跟踪的绑定是 `Developer/tools/build.py` 中固定的 `CANDIDATE_SHA` 及其断言（缺省或改动源码时构建失败）。该机制经本次独立重编译验证有效，但 Build ID 名称本身不可从 Git 追溯。修复提交 `2143a11` 尚无 release 构建绑定，交付身份仍停在 `2603db5`（见 §11.4）。

## 9. 复现命令

```text
python -B Auditor/tools/selftest.py
python -B Auditor/tools/fw_audit.py --package build/26092431-mode-feedback-r1/LD2401_2.50_26092431.ufw --stock vendor/LD2401_2.50.24110415.ufw --report build/26092431-mode-feedback-r1/build-report.json --elf build/26092431-mode-feedback-r1/tail_plain.elf --asm build/26092431-mode-feedback-r1/tail_plain.asm --json local/audit-26092431-fw.json
python -B Auditor/tools/reproduce_candidate.py --package build/26092431-mode-feedback-r1/LD2401_2.50_26092431.ufw --out local/auditor-repro-26092431 --version 26092431 --elf build/26092431-mode-feedback-r1/tail_plain.elf --ref 0x4514 --ref 0x465c --json local/audit-26092431-repro.json
python -B Auditor/tools/reproduce_candidate.py --package build/reproduce-26092430/LD2401_2.50_26092430.ufw --out local/auditor-repro-26092430 --version 26092430 --define "" --elf build/reproduce-26092430/tail_plain.elf --json local/audit-26092430-repro.json
python -B Auditor/tools/ha_feedback_check.py --ha-processor local/ha-runtime/2026.9.3/bluetooth/passive_update_processor.py --json local/audit-26092431-ha-2026.9.3.json
python -B Auditor/tools/ha_feedback_check.py --bthome-path local/bthome-3.9.1 --ha-processor local/ha-runtime/2026.3.0/bluetooth/passive_update_processor.py --json local/audit-26092431-ha-3.9.1.json
python -B Auditor/tools/q32s_xref.py --asm build/26092431-mode-feedback-r1/tail_plain.asm refs 0x4514
python -B Developer/tools/check_telemetry.py --clang C:/JL/pi32/bin/clang.exe
python -B tools/check_repository.py --protocol
```

环境：Windows，Python 3.12.14（仓库 `.venv`），bthome-ble 3.24.0（安装）与 3.9.1（`local/` 副本），HA processor 源码 2026.3.0 / 2026.9.3（`local/ha-runtime/`），工具链 `C:/JL/pi32/bin`。原厂镜像反汇编包装件在 `local/auditor-stock/`。

工具身份（`distribution_sha256`）：`fw_audit.py` `d9663213…`、`audit_ld2401_ufw.py` `a1c97270…`、`q32s_xref.py` `dd5e6d46…`（含 AUD-04 修复）、`selftest.py` `68089aac…`、`reproduce_candidate.py` `648bcd23…`、`ha_feedback_check.py` `951d2b82…`；本次已按仓库既有约定把两个新增工具登记进 `metadata/role-tool-sources.json`（该目录属维护者，登记内容请维护者复核）。

## 10. 结论

对 commit `2603db5` / Build ID `26092431-mode-feedback-r1` / UFW `367df6fd…5872a`：

- 候选包与源码、工具链、构建报告、两个归档之间的绑定经独立重编译与逐成员比对成立；
- 封装完整性、双镜像一致、布局不变量、补丁范围、版本字段与执行上限全部通过；
- 固件改动限定在 `payload.c` 的新增 `0x0F` 对象，未引入新钩子、新 RAM 地址、新栈占用或新调用；
- 新增对象的位置、顺序、长度与编码经 C 层面 80 用例、机器码逐条核对与 HA 端真实库矩阵确认；
- 未发现需要 Developer 修复的实现缺陷。AUD-01、AUD-03、AUD-05 已由 Developer 在 `2143a11` 修复并经我复核；AUD-02（Tester 解码器）与 AUD-04（Auditor 工具）亦已修复并复测。

**审计状态说明**：本次审计在干净工作树 `2603db5` 上完成，候选 UFW 与构建报告哈希复核后未变。AUD-01/02/03/04/05 的修复都是审计结束后的变更，按 CONTRIBUTING「保留原始证据、以后续记录更正」的做法记录在各自条目的“后续状态”与 §11，原始结论与证据未改写。修复均未改动固件源码、HA 运行时实现或候选包字节（§11 已独立复核）。`metadata/` 与 `docs/` 属维护者所有，本次仅为 AUD-04 刷新 Auditor 工具身份并登记两个新增工具，其余改动由其他角色作出，请维护者在提交前统一复核。

**本报告不构成实机测试结论**：硬件行为、空口 31 字节帧、真实 HA 渲染与 OTA/恢复路径仍未验证，需由 Tester 在实机上按同一身份记录覆盖。发布决定属于维护者。

## 11. 审计后修复复核（commit `2143a11`，2026-10-01 补记）

Developer 提交 `2143a1164b30c54ab70d5f39a96beb2686f5f280`「Fix audit feedback tests, reserved layout assertions and upgrade notes」回应本报告 AUD-01 / AUD-03 / AUD-05。我在该 commit 上重新独立验证。

### 11.1 变更范围：不触及固件与 HA 实现

`git diff --name-only 2603db5..2143a11` 仅含 `.github/workflows/check.yml`、`Developer/README.md`、`Developer/tests/*`、`Developer/tools/build.py`、`Developer/tools/flash_layout.py`、`Developer/verification-26092431.md`、`docs/home-assistant.md`。对 `Developer/src`、`Developer/linker`、`custom_components/`、`esphome/`、`metadata/firmware-*` 的过滤结果为空，即本次提交未改动固件源码、链接脚本或 HA 运行时实现。

### 11.2 固件绑定复核

在 `2143a11` 工作树上重跑 `reproduce_candidate.py`：仍是 20 段已分配节逐字节匹配、尾端 `0x1e2b114`、`8 ok / 0 failed`，候选包哈希仍为 `367df6fd…5872a`。`Developer/tools/build.py` 中 `CANDIDATE_SHA` 未变；Developer 另用新构建器在独立目录/独立 Build ID 产出 `26092431-audit-fixes-dev1`，其 UFW 与 r1 逐字节相同（均 `367df6fd…5872a`），其报告 `reserved_layout_validated=true`。**结论：固件候选字节未因修复提交而改变。**

### 11.3 测试复核

| 组合 | 结果 |
| --- | --- |
| bthome-ble 3.24.0（安装版） | 22 passed |
| bthome-ble 3.9.1（`local/` 副本） | 22 passed |
| 上述两者 × HA 官方 2026.3.0 / 2026.9.3 processor 源码（四种组合） | 各 22 passed |

22 = 11 个 HA 行为测试 + 11 个新增合成布局测试；AUD-01 的失败用例已被重写为可观测行为断言，因此最低版本声明现在可复现。CI 同时改为 3.9.1 / 3.24.0 精确版本矩阵并安装真实 `home-assistant-bluetooth`（本机因未安装该包，3.9.1 运行仍用 `local/auditor_plugins/ha_bluetooth_shim.py` 替代，只补类型注解码）。

### 11.4 遗留事项

- `26092431-audit-fixes-dev1` 的报告记录 `git_commit=2603db5`、`git_dirty=true`，属开发模式构建，**没有 release 报告绑定 `2143a11`**。按 CONTRIBUTING，已交接候选的 commit 与二进制保持冻结，故当前交付身份仍是 `2603db5` + `367df6fd…`，本报告的审计结论继续有效；若维护者希望交付身份前移到 `2143a11`，需从干净的该 commit 用 `--release` 与新 Build ID 重新构建（当前工作树含 Tester / Auditor 未提交改动，尚不满足干净条件）。
- `Developer/verification-26092431.md` 已如实更正原 3.9.1 声明（承认原声明有误），与 §7 AUD-01 一致。
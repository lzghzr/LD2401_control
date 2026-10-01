# LD2401 26092431 独立审计报告

- 角色：Auditor
- 审计对象：commit `343a0d262a4a0960f27aca3da02dc3f40298345c`（分支 `codex/out-mode-feedback`），Build ID `26092431-mode-feedback-r1`；审计后修复复核见 §11（commit `7fa6a7a`）
- 固件：`LD2401_2.50_26092431.ufw`，607840 字节，SHA-256 `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`
- HA 集成：本次审计对象为 `ld2401_control` 1.1.0；其后的发送节点选择改动见 §13（1.1.1）、§14（1.1.2）与 §15（1.1.3）
- 审计时间：2026-10-01
- 审计结论：**固件交付（26092431）静态与离线检查全部通过，未发现固件实现缺陷，AUD-01～AUD-06 均已修复并经复核（§11、§15）；HA 1.1.1→1.1.3 的选路重做方向正确且经独立复核；AUD-07 / AUD-08 仍待维护者处理（HA 版本声明滞后、1.1.1～1.1.3 候选未签名未入 main）；硬件已由用户确认测试，真实 HA 实例行为仍未验证。**

## 1. 身份与输入核验

审计开始时工作树为 `343a0d2`，`git status --porcelain` 为空。`build/`、`local/` 为 Git 忽略目录，本次审计未改写任何已交接产物（复核后候选包与构建报告哈希不变；AUD-02 / AUD-04 的后续修复同样未触及这两份产物）。

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
- **后续状态（commit `7fa6a7a`）**：已按建议重写为 `test_shared_updates_use_authenticated_parser`——断言 `bindkey_verified`/`decryption_failed`/已接受更新/认证 counter/模式，并覆盖一次 MIC 篡改后恢复；不再替换或计数私有解密方法。CI 改为 `bthome-ble` 3.9.1 与 3.24.0 的版本矩阵并安装真实 `home-assistant-bluetooth` 兼容包。我复测：两版本各 22 通过（原 11 HA + 新增 11 布局测试）。详见 §11。

### AUD-02（中高，Tester 侧准备度）Tester 解码器不支持新对象，26092431 帧全部无法解码

- 证据：`Tester/tools/decode_capture.py` 的 `OBJECTS` 无 `0x0F`；用其函数解码同一密钥构造的 15 字节帧得到

  ```text
  26092430 13-byte decoded {...}
  26092431 15-byte REJECTED ValueError unsupported object 0x0f at plaintext offset 4
  ```

- 影响：`decode_records` 会把每一帧记为 error，`main` 返回 1；Tester 无法统计新候选的 counter 速率或核对 `0x0F`。同时 `Tester/tools/check_capture.py` 的合成夹具仍是 13 字节，因此仓库协议检查显示 PASS 而新格式实际不可解码。
- 建议（Tester 维护范围）：在 `OBJECTS` 增加 `0x0F: ('hold', 1, 1)`，并让离线夹具覆盖 15 / 11 字节两种新布局，以便实机测试阶段能直接产出结论。
- **后续状态（审计结束后）**：Tester 已在工作树完成该修正——`OBJECTS` 增加 `0x0f: ('hold', 1, 1)`，夹具扩到 5 种明文布局。用同一密钥复测，15 字节帧解出 `hold=1, out_high=1, distance_mm=1230`，11 字节无快照帧解出 `hold=0, voltage_v=3.2, out_high=1`。该修正属于审计对象 `343a0d2` 之后的工作树变更，不在本次审计的 commit 内。

### AUD-03（低，Developer 报告与文档措辞）`reserved_entries_unchanged=false` 与“验证保留条目”的表述

- `build-report.json` 两个镜像均为 `"reserved_entries_unchanged": false`。核对条目后原因明确：带 `0x10` 标志的条目是 VM 与 PRCT，二者按设计随应用增大而移动；BTIF/EXIF 未移动（`fw_audit.py` 的 `layout.image*.BTIF/EXIF` 检查通过）。
- 但 `Developer/verification-26092431.md` 称构建器“validates … reserved entries”，而构建器只是记录该字段，未对其断言，也未断言 BTIF/EXIF 不动。
- 建议：把该字段改为按条目分类（“VM/PRCT 允许移动、BTIF/EXIF 必须不动”）并加上断言，或修正文档表述。
- **后续状态（commit `7fa6a7a`）**：新增 `flash_layout.check_reserved_layout()`，逐条目断言元数据（`header`/`flags`/`reserved`/`last`/`data_crc`）一致，并按策略断言几何：VM 起点等于固定边界且末端保持，PRCT 从 0 到 VM 起点，BTIF/EXIF 偏移与大小不变；报告字段改为 `reserved_layout_validated` 与 `reserved_entry_checks`（含 before/after 坐标）。另把 `OUTPUT.write_bytes()` 移到全部不变量之后，失败构建不再留下输出文件。我复测后续构建报告：`reserved_layout_validated=true`，BTIF 249856/4096、EXIF 253952/4096 前后一致。详见 §11。

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
- **后续状态（commit `7fa6a7a`）**：`docs/home-assistant.md` 升级小节已补充该说明，含 on/off 含义与“选择器结合该传感器状态与物理电平”的关系。

## 8. 未解决问题与覆盖边界

以下内容**本次审计不能证明**，需实机或后续证据：

1. **31 字节 legacy 广播的实机接受度**：26092430 实测帧为 29 字节，本候选恰为上限 31 字节。栈层是否接受、空口是否完整、接收端是否合并/截断，均无离线证据；手册已将其列为待验证项。
2. **采样瞬态**：固件只能检测“采样窗口内 `0x4514` 发生变化”，无法观测写入方的先后顺序；若原厂 A6 先写保持标志、后驱动引脚，仍可能广播出一帧 `hold=1` + 旧电平的自洽但过渡状态（500 ms 后收敛）。属可接受的瞬态，但“同帧一致”不等于“无过渡态”。
3. **`build_live` 返回 0 的推迟路径未被任何测试执行**：宿主夹具的 hold 输入是稳定的，无法触发双读不一致；该分支只经反汇编核对。同时 `bthome_tick` 的 `failed`（len==0）路径也无夹具覆盖。
4. **真实 HA 实例**：未启动 Home Assistant。`select.py` 在 `__init__` 中预置 `entity_id`、旧按钮实体清理、UI 渲染与自动化迁移均未在真实实例验证；`docs/home-assistant.md` 关于 “HA 2024.8.0 引入 `entry.runtime_data`” 的说法未独立核实。
5. **依赖版本**：`metadata/firmware-26092431.json` 的 `0x4514`、B2 扫描状态字节 `0x4345` 等含义继承自已验参考候选的反汇编结论；本次仅独立确认了与本次改动直接相关的 `+468 / +5` 两个锚点与 FE 位移差。
6. **随机数强度、掉电持久化、BLE 时序、OTA/恢复**：沿用既有手册限制，未在本次改动范围内重新验证；本次改动未触及这些路径。
7. **交接身份的可追溯性**：Build ID 字符串与 `handoff.json` 只存在于被忽略的 `build/` 目录；跟踪的绑定是 `Developer/tools/build.py` 中固定的 `CANDIDATE_SHA` 及其断言（缺省或改动源码时构建失败）。该机制经本次独立重编译验证有效，但 Build ID 名称本身不可从 Git 追溯。修复提交 `7fa6a7a` 尚无 release 构建绑定，交付身份仍停在 `343a0d2`（见 §11.4）。

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

对 commit `343a0d2` / Build ID `26092431-mode-feedback-r1` / UFW `367df6fd…5872a`：

- 候选包与源码、工具链、构建报告、两个归档之间的绑定经独立重编译与逐成员比对成立；
- 封装完整性、双镜像一致、布局不变量、补丁范围、版本字段与执行上限全部通过；
- 固件改动限定在 `payload.c` 的新增 `0x0F` 对象，未引入新钩子、新 RAM 地址、新栈占用或新调用；
- 新增对象的位置、顺序、长度与编码经 C 层面 80 用例、机器码逐条核对与 HA 端真实库矩阵确认；
- 未发现需要 Developer 修复的实现缺陷。AUD-01、AUD-03、AUD-05 已由 Developer 在 `7fa6a7a` 修复并经我复核；AUD-02（Tester 解码器）与 AUD-04（Auditor 工具）亦已修复并复测。

**审计状态说明**：本次审计在干净工作树 `343a0d2` 上完成，候选 UFW 与构建报告哈希复核后未变。AUD-01/02/03/04/05 的修复都是审计结束后的变更，按 CONTRIBUTING「保留原始证据、以后续记录更正」的做法记录在各自条目的“后续状态”与 §11，原始结论与证据未改写。修复均未改动固件源码、HA 运行时实现或候选包字节（§11 已独立复核）。`metadata/` 与 `docs/` 属维护者所有，本次仅为 AUD-04 刷新 Auditor 工具身份并登记两个新增工具，其余改动由其他角色作出，请维护者在提交前统一复核。

**本报告不构成实机测试结论**：硬件行为、空口 31 字节帧、真实 HA 渲染与 OTA/恢复路径仍未验证，需由 Tester 在实机上按同一身份记录覆盖。发布决定属于维护者。

## 11. 审计后修复复核（commit `7fa6a7a`，2026-10-01 补记）

Developer 提交 `7fa6a7ad2e8d3ccd6562268489a69485603a1402`「Fix audit feedback tests, reserved layout assertions and upgrade notes」回应本报告 AUD-01 / AUD-03 / AUD-05。我在该 commit 上重新独立验证。

### 11.1 变更范围：不触及固件与 HA 实现

`git diff --name-only 343a0d2..7fa6a7a` 仅含 `.github/workflows/check.yml`、`Developer/README.md`、`Developer/tests/*`、`Developer/tools/build.py`、`Developer/tools/flash_layout.py`、`Developer/verification-26092431.md`、`docs/home-assistant.md`。对 `Developer/src`、`Developer/linker`、`custom_components/`、`esphome/`、`metadata/firmware-*` 的过滤结果为空，即本次提交未改动固件源码、链接脚本或 HA 运行时实现。

### 11.2 固件绑定复核

在 `7fa6a7a` 工作树上重跑 `reproduce_candidate.py`：仍是 20 段已分配节逐字节匹配、尾端 `0x1e2b114`、`8 ok / 0 failed`，候选包哈希仍为 `367df6fd…5872a`。`Developer/tools/build.py` 中 `CANDIDATE_SHA` 未变；Developer 另用新构建器在独立目录/独立 Build ID 产出 `26092431-audit-fixes-dev1`，其 UFW 与 r1 逐字节相同（均 `367df6fd…5872a`），其报告 `reserved_layout_validated=true`。**结论：固件候选字节未因修复提交而改变。**

### 11.3 测试复核

| 组合 | 结果 |
| --- | --- |
| bthome-ble 3.24.0（安装版） | 22 passed |
| bthome-ble 3.9.1（`local/` 副本） | 22 passed |
| 上述两者 × HA 官方 2026.3.0 / 2026.9.3 processor 源码（四种组合） | 各 22 passed |

22 = 11 个 HA 行为测试 + 11 个新增合成布局测试；AUD-01 的失败用例已被重写为可观测行为断言，因此最低版本声明现在可复现。CI 同时改为 3.9.1 / 3.24.0 精确版本矩阵并安装真实 `home-assistant-bluetooth`（本机因未安装该包，3.9.1 运行仍用 `local/auditor_plugins/ha_bluetooth_shim.py` 替代，只补类型注解码）。

### 11.4 遗留事项

- `26092431-audit-fixes-dev1` 的报告记录 `git_commit=343a0d2`、`git_dirty=true`，属开发模式构建，**没有 release 报告绑定 `7fa6a7a`**。按 CONTRIBUTING，已交接候选的 commit 与二进制保持冻结，故当前交付身份仍是 `343a0d2` + `367df6fd…`，本报告的审计结论继续有效；若维护者希望交付身份前移到 `7fa6a7a`，需从干净的该 commit 用 `--release` 与新 Build ID 重新构建（当前工作树含 Tester / Auditor 未提交改动，尚不满足干净条件）。
- `Developer/verification-26092431.md` 已如实更正原 3.9.1 声明（承认原声明有误），与 §7 AUD-01 一致。

## 12. 交付绑定（维护者后续记录，2026-10-01）

本节由维护者补记，不改写 §1–§11 的审计结论与证据，只记录后续的交付动作。

维护者已将交付提交到 `main`，并从该干净提交用 `Developer/tools/build.py --release` 重建 release 报告：`git_dirty=false`，输出 UFW 仍为 `367df6fd…5872a`（607840 字节），`reserved_layout_validated=true`，对该包运行 `Auditor/tools/fw_audit.py` 仍为 `36 ok / 0 failed / 0 skipped`。

交付沿用同一 Build ID `26092431-mode-feedback-r1`。本次只更换干净的构建 commit：固件源码、链接脚本、构建参数与工具链字节均未变化，新旧两次构建的 UFW 逐字节相同，20 个已分配节的地址与内容全部一致（ELF 差异仅在节头字符串表中的对象文件路径）。按 CONTRIBUTING「复现同一输入也用独立目录」，输出写入新的空目录，已冻结的 r1 产物未被覆盖；三个角色报告绑定的 Build ID 因此保持不变。

`metadata/firmware-26092431.json` 已更新为交付记录：`hardware_status=USER_CONFIRMED_TESTED`、`independent_audit_status=COMPLETED`，`coverage` 指向本报告与 [Tester 报告](../../Tester/reports/26092431-mode-feedback-r1.md)。§11.4 中「当前交付身份仍是 `343a0d2`」的状态已由此取代，本报告的审计结论继续对同一 UFW 字节有效。

### 12.1 提交重签名与 SHA 映射

交付提交按用户要求使用其 SSH 密钥（ed25519，指纹 `SHA256:quW1UdiOatEuBDQafx/xKS6YbhSP1QZSFmtOwWK3hgI`）重新签名。重签名只改提交对象，不改内容：每个提交的 tree 哈希与重签名前逐一致，因此 §1–§11 的结论、证据和复现命令仍然成立。

| 内容 | 重签名前（未签名） | 重签名后（已签名） |
| --- | --- | --- |
| 认证 OUT 模式反馈与共享 BTHome 解析 | `2603db5` | `343a0d2` |
| 审计反馈修复（AUD-01/03/05、布局断言、CI） | `2143a11` | `7fa6a7a` |
| 交付身份、审计报告与实测覆盖记录 | `6fd6b22` | `603c8c0` |
| 本报告 §12 交付绑定补记 | `ad1b43c` | `cfe99e8` |

本报告正文的 commit 引用已更新为签名后的 SHA。重签名前的提交仍可通过保留 tag `archive/26092431-pre-signature`（指向重签名前的交付提交 `ad1b43c`）追溯，其祖先链完整保留。§1.1 一类「当时实际执行的本地操作」记录（如 `local/wt-2143a11`、`local/verify-2143a11` 证据目录）保留原名称，与磁盘实际路径一致，不再改写。

我复核了 §12：`2603db5` 与 `343a0d2`、`2143a11` 与 `7fa6a7a` 的 tree 哈希逐一相同（`6c97b6b0…`、`9a9d45a7…`），重签名未改动任何内容；tag `archive/26092431-pre-signature` 指向 `ad1b43c`；release 目录 `build/26092431-mode-feedback-r1-release-52cfcbc` 的报告为 `git_commit=52cfcbc`、`git_dirty=false`，其 UFW 与冻结的 r1 逐字节相同。§12 的交付声明成立。

## 13. HA 集成 1.1.1 审计（commit `37d105c`，2026-10-01 补记）

审计对象：HA 集成 **1.1.1**，Build ID `ha-1.1.1-sender-routing-r1`，commit `37d105cf5eb487ce8b8aff371cd7e0009d956e57`（分支 `codex/ha-sender-routing`，**未签名**，未进入 `main`），交接包 `ld2401_control-1.1.1.zip` SHA-256 `0a18ee8458ebecae8098729b2560d9c81408dce3620cdf034ad7f063f35770bc`。本次只改动 HA 侧发送节点选择与超时反馈；§1–§12 的固件结论继续适用。

### 13.1 身份核验

| 对象 | 记录值 | 实测 |
| --- | --- | --- |
| `ld2401_control-1.1.1.zip` | `0a18ee84…70bc`，12 文件 | 一致，12 个成员逐一与 commit 内容相同 |
| `manifest.json` 版本 | 1.1.1 | 一致 |
| 固件是否改变 | `firmware_changed=false` | 一致：我在该 commit 重跑独立重编译仍得 `367df6fd…5872a`，7 项全过 |
| `git_dirty` | false | 一致 |

### 13.2 用户反馈缺陷的根因：独立复现

Developer 的判断是：原解析器拿 `scanner.name` / `scanner.source` 去匹配 ESPHome 动作的节点前缀，而真实库里 `name` 是装饰后的显示名、`source` 是蓝牙 MAC，两者都匹配不上，于是总是回落到按名称排序的第一个动作——命令被发给听不到雷达的节点，固件没有收到控制帧，5 秒结算窗口过后选中项回到实测模式，且不报错。这与用户描述的“选完几秒后回弹、没有报错”完全一致。

我用 `Auditor/tools/ha_routing_check.py` 独立验证（真库 `bluetooth_adapters.adapter_human_name`、从 commit `52cfcbc` 抽出的修复前副本）：

```text
真库格式化：adapter_human_name('z-near', '02:00:00:00:10:01') == 'z-near (02:00:00:00:10:01)'

修复前（52cfcbc 副本）             修复后（37d105c）
decorated_name_and_mac_source  → a_far   (错)     → z_near  (对)
strongest_receiver             → a_far   (错)     → m_far   (对, rssi -40)
missing_rssi_single            → a_far   (错)     → z_near  (对)
```

修复前代码确实选错节点，根因成立；`scanner.adapter` 承载节点身份这一判断也经真库确认（`BaseHaScanner.__init__` 设 `self.adapter = adapter`，`self.name = adapter_human_name(adapter, source)`）。同时确认新代码注释「`connectable=False` 包含全部 HA 扫描器」正确：`BluetoothManager.async_scanner_devices_by_address` 在 `connectable=False` 时 `itertools.chain(_connectable_scanners, _non_connectable_scanners)`，旧代码那次额外的 `connectable=True` 查询是冗余的。

### 13.3 修复行为复核

同一工具在 1.1.1 上 8 个场景：装饰名/MAC 源仍能匹配到 `adapter`；多接收端按 RSSI 取最强；已知认证源优先于 RSSI；显式配置动作优先且**完全不查询扫描器 API**（lookups=0）；无匹配接收端时按文档回落并告警；缺少 `adapter` 属性的旧库仅按裸显示名匹配。这些均与 Developer 的声明一致。`_request_action` / `_expire_request` 重构经代码审查与 Developer 的超时告警用例核对：结算窗口过期在广播回调与周期检查两条路径都会清理并告警一次（`_clear_request` 置空 deadline，第二次调用提前返回），不再有旧代码中“广播路径静默清理”的差异。

### 13.4 新问题

#### AUD-06（中低，Developer）排序键直接用原始 RSSI，未按库约定把 `None`/`0` 归一为“无信号”

- 新代码 `sorted(devices, key=lambda device: (device.scanner.source == self._last_source, device.advertisement.rssi), reverse=True)` 使用原始 `rssi`。而 habluetooth 自己在**所有** RSSI 比较处都把假值归一为 `NO_RSSI_VALUE`（`bleak_retry_connector` 的 -127），共 6 处，包括按 RSSI 排序的 `BaseHaScanner._score_connection_paths`：`score = scanner_device.advertisement.rssi or NO_RSSI_VALUE`，以及 `auto_scheduler` 的 `NO_RSSI_VALUE if adv_rssi is None else adv_rssi`。
- 后果一（崩溃，回归）：当 `_last_source` 未匹配到任何一个接收端、且至少两个接收端中有一个 `rssi=None` 时，元组第二项需要比较 `None` 与 `int`，抛 `TypeError`。实测：

  ```text
  missing_rssi_one_of_two → TypeError: '<' not supported between instances of 'NoneType' and 'int'
  ```

  修复前代码不排序，因此不会崩。异常沿 `async_send_mode` 传出，`async_select_mode` 会清理请求并重新抛出，用户看到服务调用失败。bleak 把 `AdvertisementData.rssi` 标注为 `int`，但 habluetooth 明确为 `None` 设防，说明该形态可达（至少 pyobjc 后端）。
- 后果二（静默错路由）：`rssi=0` 不是有效信号强度（HA/habluetooth 视其为“无信号”），但 `reverse=True` 会把 0 排在 -40 之前。实测 `zero_rssi_ranks_best`：`a_far(rssi=0)` 胜过 `m_far(rssi=-40)`，即广播被发给并非最强的节点——**症状与本次修复要解决的原始缺陷同类**（命令到不了雷达、选中项回弹）。我无法从离线证据判断 `rssi=0` 在实际部署中的出现频率，故记为中低而非高。
- 建议：与库保持一致，例如 `rssi = device.advertisement.rssi or -127`（或 `NO_RSSI_VALUE`）后再排序，同时消除崩溃与错序。
- **后续状态（commit `7ca4538` → `67ea6ac`）**：`None` / NaN 在 1.1.2 已改为被过滤而不再参与比较，崩溃消除；`rssi=0` 在 1.1.3 被追加排除（`or rssi == 0`），不再抢占最强带，也不能作为唯一候选或经迟滞保留。两项均由独立工具断言验证，**AUD-06 关闭**，详见 §14.4 与 §15.2。

#### AUD-07（低，Maintainer）HA 集成版本声明在四处不一致

| 文件 | 值 |
| --- | --- |
| `custom_components/ld2401_control/manifest.json` | 1.1.1 |
| `README.md`、`docs/publishing.md`、`CHANGELOG.md` | 1.1.1 |
| `AGENTS.md` 第 5 行 | **1.1.0** |
| `metadata/firmware-26092431.json` 的 `ha_integration_version` | **1.1.0** |

`metadata/firmware-26092431.json` 是固件交付记录，其 `ha_integration_version` 绑定的是审计与实测时的 HA 版本；HA 已前进到 1.1.1 而该字段未同步，`AGENTS.md` 同样滞后。按维护者角色更新（不属于本次 Developer 提交范围），并建议在该字段上区分“固件交付时配套的 HA 版本”与“当前 HA 版本”。

#### AUD-08（低，Developer / 维护者）1.1.1 候选尚未进入签名交付链

`37d105c` 未签名且只在 `codex/ha-sender-routing` 分支上，`main` 仍停在 `52cfcbc`；`handoff.json` 也如实标注 `commit_signing: unsigned`、`live_ha_verified: false`。若要把 1.1.1 作为交付，需要与固件交付同样的处理：合并到 `main`、签名、从干净提交产出绑定报告。

### 13.5 测试与整体回归复核

| 检查 | 结果 |
| --- | --- |
| Developer 29 项测试 × {bthome-ble 3.9.1, 3.24.0} × {HA 2026.3.0, 2026.9.4} | 四组合各 29 passed，与声明一致 |
| 我的 HA 反馈矩阵（`ha_feedback_check.py`，1.1.1 + HA 2026.9.4） | 7 ok / 0 failed：解码三态、重放/回退/篡改拒绝、密钥纪元、旧帧不继承 hold、共享解析单次解密、选项映射均未回归 |
| 我的路由工具 8 场景 | 6 项通过并断言，2 项 RSSI 边界记为发现（AUD-06） |
| 仓库协议检查 | PASS，85 个公开文件 |
| 固件 | 该 commit 下独立重编译仍为 `367df6fd…5872a` |

其余声明（`diff_check`、`live_ha_verified=false`）与 `verification-ha-1.1.1.md` 相符；该文档明确“1.1.1 安装、真实服务路由与物理 OUT 切换仍需在用户 HA 实例验证”，与我的判断一致。

### 13.6 1.1.1 结论

- 用户反馈的缺陷真实存在，Developer 的根因分析正确，我独立复现了修复前的错误选择；
- 修复方向正确（匹配 `scanner.adapter`），核心场景经独立工具验证；显式动作优先、无匹配回落、超时告警等既有行为未回归；
- 新发现 **AUD-06**：排序键未按 Bluetooth 库约定归一 RSSI，导致 `None` 崩溃（相对修复前是回归）与 `rssi=0` 静默错路由（症状与原始缺陷同类），建议修复后再交付；
- **AUD-07 / AUD-08** 为版本声明与交付链的记录问题，属维护者范围；
- 固件与 §1–§12 结论不受影响；实机 HA 验证仍待用户环境完成。

## 14. HA 集成 1.1.2 审计（commit `7ca4538`，2026-10-01 补记）

审计对象：HA 集成 **1.1.2**，Build ID `ha-1.1.2-signal-routing-r1`，commit `7ca453873e83a884c97a8f5c10af6fc47c28744c`（分支 `codex/ha-sender-routing`，**未签名**，未进入 `main`），交接包 `ld2401_control-1.1.2.zip` SHA-256 `225034549528cf94384f763e18b1995e81dc8df1a0b33469fa86828893db3100`。本次把自动发送节点选择从「最近认证源 + RSSI」改为「本雷达的新鲜接收 + RSSI 频带 + 迟滞」，并去掉字母序回落。固件与 ESPHome 未改动（该 commit 未触及 `Developer/src`、`Developer/linker`、`esphome/`）。

### 14.1 身份核验

| 对象 | 记录值 | 实测 |
| --- | --- | --- |
| `ld2401_control-1.1.2.zip` | `22503454…3100`，12 文件 | 一致，12 个成员逐一与 commit 内容相同 |
| `manifest.json` 版本 | 1.1.2 | 一致 |
| `firmware_changed` / `esphome_changed` | false / false | 一致（`Developer/src`、`esphome/` 无改动） |
| `git_dirty` | false | 一致 |

### 14.2 新解析器的关键 API 与时钟：独立核实

新代码依赖 `device.scanner.discovered_device_timestamps[self.address]` 与 `time.monotonic()` 可相减。我在三个来源上核实：

- 本机 habluetooth **7.1.2**：`BaseHaScanner.discovered_device_timestamps` 是公开属性（`_discovered_device_timestamps` 已弃用并给出 FutureWarning），返回 `{address: info.time}`，`info.time` 由 `monotonic_time_coarse()` 写入；`bluetooth_data_tools.monotonic_time_coarse` 是 `time.monotonic`（Linux 上为 `CLOCK_MONOTONIC_COARSE`，同一起点），因此与集成里的 `time.monotonic()` 同基准 ✓。
- 上游 habluetooth **5.8.0**（声明的最低 HA 2026.3.0 所配版本）源码：同名公开属性与同一 `monotonic_time_coarse` 时钟已存在，`scanner.adapter` / `scanner.name` 的语义也与 7.1.2 一致（`name = adapter_human_name(adapter, source)`）✓。Developer 关于最低版本可用的声明成立。
- 扫描器缓存的过期阈值为 `CONNECTABLE_FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS = 195` 秒，因此 30 秒新鲜度是实际起作用的约束，时间戳不会先被库清掉。

另外确认 `0 <= now - received` 这个下界是必要且正确的：HA 重启后会从存储恢复上一次开机的单调时间戳，此时 `now - received` 可能为负，该判断会把这类还原条目拒掉而不是误判为新鲜。

### 14.3 行为复核（同一工具、同一场景集，对三个版本对照）

`Auditor/tools/ha_routing_check.py` 已升级到 1.1.2 的 API 表面（每地址时间戳、`adapter`、RSSI），同一组 14 个场景分别跑 1.1.0（`52cfcbc` 副本）、1.1.1（`37d105c` 副本）与 1.1.2：

| 场景 | 1.1.0 | 1.1.1 | 1.1.2 |
| --- | --- | --- | --- |
| 装饰名/MAC 源匹配节点身份 | `a_far` ✗ | `z_near` | `z_near` |
| 同时刻取最强 RSSI | `a_far` ✗ | `m_far` | `m_far` |
| 频带内取更新接收 | `a_far` | `a_far` | `a_far` |
| 频带外不因更新而提升 | `a_far` ✗ | `m_far` | `m_far` |
| 显式动作优先（且不查扫描器 API） | `a_far` | `a_far` | `a_far`，lookups=0 |
| 无接收端 | 回落 `a_far` | 回落 `a_far` | **拒绝**并给可操作错误 |
| 接收超过 30 秒 | 回落 `a_far` | 忽略时间戳选 `z_near` | **拒绝** |
| 缺少每地址时间戳 | 回落 `a_far` | 忽略时间戳选 `z_near` | **拒绝** |
| 迟滞：保留上一发送端 | — | `a_far`（无迟滞） | `m_far`（保留） |
| 迟滞释放：上一发送端明显落后 | — | `a_far` | `a_far` |
| 无 `adapter` 属性时按裸名匹配 | `z_near` | `z_near` | `z_near` |
| 两个接收端其一 `rssi=None` | `a_far` | **TypeError 崩溃** | `m_far`（跳过该端） |
| 唯一接收端 `rssi=None` | `a_far` | `z_near` | **拒绝** |
| `rssi=0` 对 `rssi=-40` | `a_far` | `a_far` | **`a_far`（仍未修）** |

1.1.2 的 11 个断言场景全部通过，评分规则（先取最强、再取 3 dB 带内、带内按接收时间、带内且滞后 ≤5 秒则保留上一发送端、完全并列按动作名稳定排序）经代码审查与场景核对一致；`close` 先按动作名排序再 `max`，因此并列结果确定；`chosen.received - previous.received` 恒为非负（chosen 是带内最新），迟滞判断不会反向。显式动作仍然完全绕过扫描器查询（lookups=0）✓。

### 14.4 AUD-06 的处置状态：一半已修，`rssi=0` 仍然错

- **已修**：`None`（以及 NaN、非数值）现在被 `isinstance`/`math.isfinite` 过滤，不再进入比较，1.1.1 的 `TypeError` 崩溃消失。两个接收端其一为 `None` 时选另一个；唯一接收端为 `None` 时拒绝（fail-closed）。
- **未修**（仍是 AUD-06 的第二半）：`rssi = 0` 通过 `isinstance` 与 `isfinite` 校验，`strongest = max(...)` 取到 0，3 dB 带变成 `rssi >= -3`，于是报告 0 的节点独占了候选带并被选中，比真正收到 -40 的节点优先。实测 `zero_rssi_ranks_best → a_far`。HA/habluetooth 自身在所有 RSSI 比较处把 0 与 `None` 一并归一到 `NO_RSSI_VALUE`(-127)（v5.8.0 与 7.1.2 的 `_score_connection_paths` 都是 `... .rssi or NO_RSSI_VALUE`），因为 0 dBm 不是可达信号而是“未知”。后果与本次要修的症状同类：命令被发给并非真正听到雷达的节点，选中项在结算窗口后回弹。
- 建议：把校验改成 `rssi = device.advertisement.rssi or NO_RSSI_VALUE` 后再判 `isfinite`，即与库约定一致；`None`/`0`/NaN 统一视为无信号。

### 14.5 设计取舍（记录，不作为缺陷）

1. **fail-closed 取代字母序回落**：无新鲜接收端时改为报错，含单发送端安装。这消除了“静默发错节点”的可能，但代价是某些能工作的拓扑（例如 ESPHome 节点在雷达附近、而雷达的广播只被本地 USB 适配器收到、该适配器不提供 ESPHome 动作）会从“可能成功”变成“明确失败”。错误信息指向 Reconfigure 设置显式动作，可操作 ✓，且 `docs/home-assistant.md`、CHANGELOG 与验证文档都已如实描述该行为，属有意取舍。
2. **RSSI 带优先于新鲜度**：比最强信号弱 3 dB 以上的接收端无论多新都不会被选中；一个强 3 dB 以上但已 29 秒未听到雷达的节点仍会被选中。配合 30 秒上限，可以接受。
3. **`_last_source` 不再参与选路**：1.1.2 的解析器未再引用它（仍由 `_accepted_frame` 维护）。当前它只影响日志/旧语义，属无害的残留状态；若要清理需同时确认没有外部依赖。

### 14.6 测试与整体回归

| 检查 | 结果 |
| --- | --- |
| Developer 46 项测试 × {bthome-ble 3.9.1, 3.24.0} × {HA 2026.3.0, 2026.9.4} | 四组合各 46 passed（本机 habluetooth 7.1.2），与声明一致 |
| 我的路由工具（1.1.2） | 11 项断言通过，3 项 RSSI 边界记录；显式动作 0 次扫描器查询 |
| 我的 HA 反馈矩阵（`ha_feedback_check.py`，1.1.2 + HA 2026.9.4） | 7 ok / 0 failed：BTHome/共享解析路径未回归 |
| 仓库协议检查 | PASS，87 个公开文件 |
| 固件 | 该 commit 未改动固件源码；1.1.2 交接记录 `firmware_sha256` 与冻结候选一致 |

Developer 未在测试中覆盖 `rssi=0`（参数化只含 `-40`、`None`、NaN），这与我的实测结果一致：该分支确实没被验证。

### 14.7 1.1.2 结论

- 自动选路的重做方向正确：以本雷达的**新鲜接收**为主、RSSI 为频带、加迟滞，比 1.1.1 的“聚合源优先”更贴近“谁能听见雷达”；关键 API 与时钟在 7.1.2 与最低版本 5.8.0 上都成立，30 秒上限与越界保护也正确；
- **AUD-06 的 `None` 崩溃已消除**，但 **`rssi=0` 归一缺失仍未修**（AUD-06 保留为未关闭项），建议按库约定一行修正后再交付；
- fail-closed 取代字母序回落是有意取舍且已如实文档化，不再计入问题；
- **AUD-07 / AUD-08 仍然有效**：HA 版本声明（`AGENTS.md`、`metadata/firmware-26092431.json`）尚未同步到 1.1.2，`7ca4538` 依旧未签名且未在 `main` 上；
- 固件与 §1–§13 结论不受影响；1.1.2 的实机安装与物理 OUT 验证仍待用户环境完成。

## 15. HA 集成 1.1.3 审计（commit `67ea6ac`，2026-10-01 补记）

审计对象：HA 集成 **1.1.3**，Build ID `ha-1.1.3-rssi-correction-r1`，commit `67ea6ac7413f261efe235dfde860736040b1599b`（分支 `codex/ha-sender-routing`，**未签名**，未进入 `main`），交接包 `ld2401_control-1.1.3.zip` SHA-256 `a34a65c8446284db98b4c05d2c9e465c345eeba949252db93ad2b5aae03fecf9`。本次只针对 AUD-06 的第二半（未知的 `rssi=0`）。固件与 ESPHome 未改动。

### 15.1 身份核验

| 对象 | 记录值 | 实测 |
| --- | --- | --- |
| `ld2401_control-1.1.3.zip` | `a34a65c8…ecf9`，12 文件 | 一致，12 个成员逐一与 commit 内容相同 |
| `manifest.json` 版本 | 1.1.3 | 一致 |
| `firmware_changed` / `esphome_changed` | false / false | 一致（`Developer/src`、`esphome/` 无改动） |
| `git_dirty` | false | 一致 |

### 15.2 修复内容与复核

改动是在 1.1.2 的候选过滤条件上追加 `or rssi == 0`，并把错误信息改为 “No ESPHome sender has **usable RSSI** for this radar within the last 30 seconds”。这与我 §14.4 的建议（按库约定把 0 视为无信号）在排序结果上等价：0 既不进入最强信号带，也不能作为唯一候选，更不能经由迟滞被保留（`close` 是已过滤集合的子集，零 RSSI 的旧发送端不在其中）。

`ha_routing_check.py` 已把两个零 RSSI 形态从“记录”升级为断言，同一场景集对 1.1.2 与 1.1.3 的对照：

| 场景 | 1.1.2 | 1.1.3 |
| --- | --- | --- |
| `rssi=0` 与 `rssi=-40` 竞争 | `a_far`（0 胜出） | **`m_far`** ✓ |
| 唯一接收端 `rssi=0` | `z_near`（仍被选中） | **拒绝**并提示设置显式动作 ✓ |

1.1.3 的 13 个断言场景全部通过（含 `None` 分支、频带、新鲜度、迟滞、显式动作 0 次扫描器查询）。Developer 另加了测试覆盖“零 RSSI 的旧发送端不能靠迟滞存活”与“单发送端零 RSSI 报错”，补上了我之前指出的覆盖缺口；其排除集合与 HA 自身的假值约定一致（`None`、`0`、非有限值），其余数值（例如不可物理达到的 +1 dBm）仍按有效信号对待——这与 habluetooth 的 `rssi or NO_RSSI_VALUE` 语义完全相同，不构成额外问题。

一行差异值得记录（非缺陷）：库约定是把 0 归一到 `NO_RSSI_VALUE`(-127) 继续参与排序，而本实现选择**排除**。当零 RSSI 节点是唯一候选时，前者会选中它，后者报错。后者符合 1.1.2 起“宁可明确失败也不猜节点”的整体取舍，且 `docs/home-assistant.md` 已如实写明该行为与显式动作仍然可用，我按有意设计接受。

### 15.3 AUD-06 关闭

- 1.1.2 修复了 `None`/NaN 造成的崩溃；1.1.3 修复了 `rssi=0` 抢占最强带与作为唯一候选的问题；两条路径均由我的独立工具断言通过，且 1.1.2 在同组断言上表现为失败，形成清晰的前后对照；
- **AUD-06 关闭**。

### 15.4 测试与整体回归

| 检查 | 结果 |
| --- | --- |
| Developer 52 项测试 × {bthome-ble 3.9.1, 3.24.0} × {HA 2026.3.0, 2026.9.4} | 四组合各 52 passed（本机 habluetooth 7.1.2） |
| 我的路由工具（1.1.3） | 13 项断言通过，2 项 `None` 边界记录 |
| 我的 HA 反馈矩阵 | 见 §14.6；1.1.3 未触及 BTHome/共享解析路径 |
| 仓库协议检查 | PASS |
| 固件 | 未改动，交接记录 `firmware_sha256` 与冻结候选一致 |

### 15.5 1.1.3 结论

- AUD-06 已完整修复并经独立复核，自动选路现在与 HA/habluetooth 对“未知 RSSI”的约定一致；
- 未发现新的实现缺陷；
- **AUD-07 仍然有效且差距扩大**：`AGENTS.md` 与 `metadata/firmware-26092431.json` 的 HA 版本仍是 **1.1.0**，而 `manifest.json`、README、docs、CHANGELOG 已到 1.1.3；
- **AUD-08 仍然有效**：`67ea6ac` 未签名、未进入 `main`；1.1.1 / 1.1.2 / 1.1.3 三个候选都只有本地未签名提交，若要交付需按固件同一流程处理（合并、签名、从干净提交出报告）；
- 固件与 §1–§14 结论不受影响；1.1.3 的实机安装与物理 OUT 验证仍待用户环境完成。
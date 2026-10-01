# Auditor

独立审计报告及工具放在本目录。报告指明完整 commit、固件 Build ID、输入和输出 SHA-256，并列出结论、证据与未解决问题。按 CONTRIBUTING 的职责边界工作。

现有 26092430 的身份与用户确认测试记录见 [固件身份](../metadata/firmware-26092430.json)。本目录是新仓库的后续报告入口。

## 报告

| 报告 | 对象 |
| --- | --- |
| [26092431-mode-feedback-r1](reports/26092431-mode-feedback-r1.md) | 固件 commit `343a0d2` / Build ID `26092431-mode-feedback-r1` / UFW `367df6fd…`；HA 侧发送节点选择复核见该报告 §13（1.1.1，`969de8f`）、§14（1.1.2，`8ae3932`）与 §15（1.1.3，`f854165`） |

## 专用工具

| 工具 | 用途 |
| --- | --- |
| `tools/fw_audit.py` | 读取候选包、原厂包和构建报告，核对封装 CRC、两份镜像、Flash 布局、声明补丁、执行上限、版本与 ELF 字节 |
| `tools/reproduce_candidate.py` | 不经过 Developer 构建器，用固定工具链自行编译、链接候选源码，并把每段已分配节绑定到候选包字节；同时导出地址立即数引用点 |
| `tools/ha_feedback_check.py` | 用真实 `bthome-ble` 和指定 HA 版本的 passive processor 源码，独立构造帧并核对模式解码、重放/篡改拒绝、共享解析与实体选项映射 |
| `tools/ha_routing_check.py` | 用真实 `bluetooth_adapters.adapter_human_name` 与每地址 `discovered_device_timestamps` 构造扫描器夹具，驱动指定目录（含更早版本副本）的发送节点选择逻辑，核对节点身份匹配、RSSI 频带、接收新鲜度、迟滞、显式动作优先与 fail-closed 行为，并报告 RSSI 边界形态 |
| `tools/q32s_xref.py` | 从 Q32S 反汇编查询直接调用、调用链、立即数引用和跳转表；`refs` 同时识别十进制与十六进制操作数 |
| `tools/audit_ld2401_ufw.py` | Auditor 固定的只读 UFW/JLFS 解析库 |
| `tools/selftest.py` | 用合成数据检查本目录的导入、CRC、调用目标解析和命令入口 |

所有工具仅使用 Python 标准库（`ha_feedback_check.py` 另需被测环境中的 `bthome-ble`，`ha_routing_check.py` 另需 `bluetooth_adapters` 与 `cryptography`）。输入路径显式指定，相对路径按调用者的当前目录解释；不会自动选择候选包或从其他目录更新工具。`reproduce_candidate.py` 的工具链目录默认 `C:/JL/pi32/bin`，可用环境变量 `JL_Q32S_BIN` 覆盖（与 Developer 构建器同名）。示例在仓库根目录运行：

```text
python -B Auditor/tools/selftest.py
python -B Auditor/tools/fw_audit.py --package build/26092430/LD2401_2.50_26092430.ufw --stock vendor/LD2401_2.50.24110415.ufw --report build/26092430/build-report.json --elf build/26092430/tail_plain.elf --asm build/26092430/tail_plain.asm --json local/audit-26092430.json
python -B Auditor/tools/reproduce_candidate.py --package build/26092431-mode-feedback-r1/LD2401_2.50_26092431.ufw --out local/auditor-repro-26092431 --version 26092431 --elf build/26092431-mode-feedback-r1/tail_plain.elf --ref 0x4514
python -B Auditor/tools/ha_feedback_check.py --ha-processor local/ha-runtime/2026.9.3/bluetooth/passive_update_processor.py
python -B Auditor/tools/ha_routing_check.py --expect-fixed --json local/audit-routing.json
python -B Auditor/tools/q32s_xref.py --asm local/stock-q32s.asm callers 0x1e04c82
```

先创建本地报告目录。`fw_audit.py` 的解析断言需要正常 Python 模式，不能加 `-O`。未指定 `--report` 时读取候选包同目录的 `build-report.json`；`--no-report` 仅用于缩小核验范围，相关证据项会跳过。原厂输入固定为上述 LD2401 固件及其已记录 SHA-256。

`reproduce_candidate.py` 的输出目录必须是空目录，且不会写入公开源码目录。`ha_feedback_check.py` 的 `--ha-processor` 与 `--bthome-path` 指向本地保存的 HA 版本源码和备用 `bthome-ble` 副本；不指定时使用调用环境中的库与内含的最小边界替身。`ha_routing_check.py` 的 `--integration-dir` 指向要检查的集成目录，因此可以先对从旧 commit 抽出的副本运行同一组场景，比较修复前后的选择结果；`--expect-fixed` 打开断言。

## 独立性与覆盖

Auditor 的审计入口、ELF 读取与交叉引用逻辑保存在本目录，运行时不导入 Developer 构建工具。只读格式解析库是项目现有实现的独立保存副本，与 Developer 解析库同源；它能隔离后续修改，仍存在同源实现的共同错误风险。需要进一步确认格式时，应另用上游解包器或手工证据交叉验证。复制来源及当前文件哈希见 [工具来源](../metadata/role-tool-sources.json)。

`fw_audit.py` 输出每项 `ok`、`FAIL` 或 `skip`，存在失败时退出码为 1。退出码为 0 仅表示已执行的静态检查通过，跳过项和覆盖范围仍须由 Auditor 阅读。广播版本核验只比对反汇编中的立即数，不证明空口数据；Hook 检查识别修改位置，完整目标与 ABI 要结合 ELF 和交叉引用复核。间接调用、任务上下文、随机数强度、掉电持久化、BLE 时序与实机行为需要额外证据。

`reproduce_candidate.py` 证明“该 commit 的源码 + 固定工具链”与候选包字节一致，但它与 Developer 构建器共用同一链接脚本与工具链，两者有同源错误的风险；它不重算封装 CRC（由 `fw_audit.py` 覆盖），也不产生 UFW 容器。

`q32s_xref.py refs` 把寄存器加载操作数的十进制与十六进制写法都算作候选引用；低位地址也可能与普通常量（对象长度、掩码）相等，因此输出是待判定的候选而非已证实的指针。它只匹配操作数本身：`llvm-objdump` 附在分支后的 `<… : 地址 >` 注解是跳转目标，不计入引用。

`ha_routing_check.py` 只覆盖节点选择逻辑：扫描器 API、服务注册表与配置项查询都是替身，不打开适配器、不启动 Home Assistant，也不证明真实部署里哪个节点离雷达更近。RSSI 边界场景（`None`、`0`）只报告不判定，由 Auditor 在报告中给出结论。

审计报告应绑定候选 commit / Build ID / UFW SHA-256，并注明工具版本、解析库身份、全部跳过项和结论。工具自检不构成某份固件的审计结论。

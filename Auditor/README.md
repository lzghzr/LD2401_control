# Auditor

独立审计报告及工具放在本目录。报告指明完整 commit、固件 Build ID、输入和输出 SHA-256，并列出结论、证据与未解决问题。按 CONTRIBUTING 的职责边界工作。

现有 26092430 的身份与用户确认测试记录见 [固件身份](../metadata/firmware-26092430.json)。本目录是新仓库的后续报告入口。

## 专用工具

| 工具 | 用途 |
| --- | --- |
| `tools/fw_audit.py` | 读取候选包、原厂包和构建报告，核对封装 CRC、两份镜像、Flash 布局、声明补丁、执行上限、版本与 ELF 字节 |
| `tools/q32s_xref.py` | 从 Q32S 反汇编查询直接调用、调用链、立即数引用和跳转表 |
| `tools/audit_ld2401_ufw.py` | Auditor 固定的只读 UFW/JLFS 解析库 |
| `tools/selftest.py` | 用合成数据检查本目录的导入、CRC、调用目标解析和命令入口 |

所有工具仅使用 Python 标准库。输入路径显式指定，相对路径按调用者的当前目录解释；不会自动选择候选包或从其他目录更新工具。示例在仓库根目录运行：

```text
python -B Auditor/tools/selftest.py
python -B Auditor/tools/fw_audit.py --package build/26092430/LD2401_2.50_26092430.ufw --stock vendor/LD2401_2.50.24110415.ufw --report build/26092430/build-report.json --elf build/26092430/tail_plain.elf --asm build/26092430/tail_plain.asm --json local/audit-26092430.json
python -B Auditor/tools/q32s_xref.py --asm local/stock-q32s.asm callers 0x1e04c82
```

先创建本地报告目录。`fw_audit.py` 的解析断言需要正常 Python 模式，不能加 `-O`。未指定 `--report` 时读取候选包同目录的 `build-report.json`；`--no-report` 仅用于缩小核验范围，相关证据项会跳过。原厂输入固定为上述 LD2401 固件及其已记录 SHA-256。

## 独立性与覆盖

Auditor 的审计入口、ELF 读取与交叉引用逻辑保存在本目录，运行时不导入 Developer 构建工具。只读格式解析库是项目现有实现的独立保存副本，与 Developer 解析库同源；它能隔离后续修改，仍存在同源实现的共同错误风险。需要进一步确认格式时，应另用上游解包器或手工证据交叉验证。复制来源及当前文件哈希见 [工具来源](../metadata/role-tool-sources.json)。

`fw_audit.py` 输出每项 `ok`、`FAIL` 或 `skip`，存在失败时退出码为 1。退出码为 0 仅表示已执行的静态检查通过，跳过项和覆盖范围仍须由 Auditor 阅读。广播版本核验只比对反汇编中的立即数，不证明空口数据；Hook 检查识别修改位置，完整目标与 ABI 要结合 ELF 和交叉引用复核。间接调用、任务上下文、随机数强度、掉电持久化、BLE 时序与实机行为需要额外证据。

审计报告应绑定候选 commit / Build ID / UFW SHA-256，并注明工具版本、解析库身份、全部跳过项和结论。工具自检不构成某份固件的审计结论。

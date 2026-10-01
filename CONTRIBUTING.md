# 开发与交接约束

## Git 与构建身份

本仓库使用 Git。正式交接的身份为 **完整 commit + Build ID + UFW SHA-256**，集成发布同时记录 `manifest.json` 的语义版本。首次导入的 26092430 参考记录保留原固件 SHA-256，首次提交后才有仓库 commit；不得替参考记录编造历史 commit。

正式候选必须从干净且已提交的工作树构建，使用 `Developer/tools/build.py --release`。构建报告记录 commit、源码哈希、工具链哈希、输入哈希、镜像布局与输出哈希。源文件已变更时，先提交再构建。普通本地复现可使用默认开发模式，报告保留 dirty 状态。

同一 Build ID 的已交接 ELF、UFW、报告保持不可覆盖。构建器只接受空输出目录。实现、参数或工具链发生变化时使用新 Build ID、新 commit 和独立输出目录；复现同一输入也用独立目录。26092430 构建器强制匹配已测试参考 SHA-256，新的功能开发应建立独立候选并更新自己的身份记录。

## 角色

| 角色 | 所有权与职责 |
| --- | --- |
| Developer | `Developer/`、`custom_components/`、`esphome/` 的实现和修复；内置构建断言及交付路径检查 |
| Auditor | `Auditor/` 中的独立审计工具、问题和报告；对指定 commit 与 UFW SHA-256 给出结论 |
| Tester | `Tester/` 中的串口、PC OTA 等设备操作工具、协议测试、设备记录和测试报告；记录同一候选的串口 A0、广播版本与测试覆盖 |
| 维护者 | 根目录交付工具、CI、统一文档、元数据与许可；决定发布，核对候选身份、独立报告和未解决问题 |

未分配角色的会话默认 Developer。Auditor、Tester 发现实现问题时提交问题供 Developer 修复。用户对角色和任务范围的明确授权优先。多代理实施仍属于 Developer；本规范本身不授权启动代理、发送消息或刷写设备。

固件生成、UFW 封装和内置构建断言由 Developer 维护。串口通信、PC OTA 刷写、设备配置与采集工具由 Tester 维护；工具维护角色与具体一次设备操作的授权分别确定。

公共文件的角色归属见 [metadata/file-ownership.json](metadata/file-ownership.json)，目录说明见 [docs/file-layout.md](docs/file-layout.md)。根目录 `tools/check_repository.py` 负责跨角色的交付检查，调用 Auditor 的合成工具自检和 Tester 的协议 / 广播离线自检；CI 执行同一入口。专用工具及依赖关系见 [Auditor](Auditor/README.md) 和 [Tester](Tester/README.md)。

源代码可继续在新的候选分支开发；已交接候选的 commit 与二进制保持冻结。其他角色原始结论通过后续记录更正，保留原始证据。报告写明审查/测试对象，不以“最新版”指代文件。

## 固件边界

- 目标模块 LD2401，目标平台 JieLi Q32S；目标原厂固件固定为 `LD2401_2.50.24110415.ufw`，交付固件版本为 2.50.26092431，身份见 `metadata/firmware-26092431.json`；26092430 保留为构建器强制匹配的固定哈希复现基线，身份见 `metadata/firmware-26092430.json`。
- 原厂输入只读。当前方法在应用尾部追加，保留 Boot/Key、OTA 路径、未公开命令和原厂雷达功能。两份 Flash 镜像一起封装，应用内容一致，分别重算 CRC。
- UART A0 和广播中的版本同步更新。八位版本 `260924NN` 按 BCD 编码；中间 `24` 与厂商字段共用，尾号为十进制字符。
- Hook 前像、ABI、返回地址、栈、寄存器活性及指令宽度依据当前原厂镜像和 Q32S 工具链。新增地址、RAM、VM 边界调整需要独立证据和布局记录。
- Bindkey 与 counter 作为完整状态保存；先持久预留 counter 区间再使用。认证、目标地址、新鲜度与防重放检查完成之后才改变 OUT。
- 使用现有 Q32S `clang.exe`、`q32s-ld.exe`、`llvm-objdump.exe`；工具链准备详见构建说明。

## 提交与发布

提交前运行 `python -B tools/check_repository.py --protocol`。固件开发在 Windows 使用固定工具链复现；CI 运行跨平台文本、模块路径和主机协议检查。CI 通过仅表示这些检查完成。

强约束落实分两层：仓库内构建器执行干净 Git 和哈希约束；维护者在 GitHub 设置默认分支保护/Ruleset，要求 PR、至少一名审核者和 `repository-check` 状态检查，禁止强推与删除，按需要约束绕过权限。服务器规则需仓库建成后配置，文件中的规则不能自动改变 GitHub 权限。

发布前按 [发布清单](docs/publishing.md) 核对元数据与授权。版本标签指向已审计和实测的同一 commit。设备 MAC、Bindkey、Wi-Fi/API 密钥、抓包和本机路径保存在被忽略的 `local/` 等目录。仅 Git 跟踪的公共文件进入源码交付，优先用 `git archive` 导出。

所有路径变更同时更新工具、导入、例子、文档和元数据；从另一个工作目录运行入口，并复现目标 UFW 检查路径迁移。旧工程保留，当前仓库内 `Developer/` 为正式实现。

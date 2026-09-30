# 文件职责与目录

| 目录 / 文件 | 角色 | 内容 |
| --- | --- | --- |
| `Developer/src/`、`Developer/linker/` | Developer | 追加固件实现、共享协议算法和目标地址布局 |
| `Developer/tools/` | Developer | 固件构建入口、UFW 格式解析、Flash 布局、封装与 ELF 读取 |
| `custom_components/ld2401_control/` | Developer | HA 安装需要的 Python、manifest、字符串与翻译 |
| `esphome/` | Developer | 部署到发送节点的运行代码和通用配置示例 |
| `Tester/tools/`、`Tester/requirements.txt` | Tester | 串口、PC OTA、广播采集 / 解密、控制帧生成、软件自检及其依赖 |
| `Auditor/` | Auditor | 专用封装核验、Q32S 交叉引用、固定解析库、证据与报告 |
| 根目录 `tools/`、`.github/` | Maintainer | 跨角色交付检查、CI 与 PR 规则 |
| `docs/`、根 README / CHANGELOG | Maintainer | 面向使用者与贡献者的统一文档 |
| `metadata/` | Maintainer | 固件身份、源码来源和文件职责清单 |
| `third_party/licenses/`、LICENSE / NOTICE | Maintainer | 许可证与来源声明 |
| 本地 `build/`、`vendor/`、`local/` | 操作者 | 构建输出、外部输入、密钥与设备日志；Git 忽略 |

UFW 解包、CRC 检查和镜像布局是构建流程的组成部分，由 Developer 维护。独立审计的结论及工具由 Auditor 维护。ESPHome 的发送程序属于部署产品实现，由 Developer 维护；串口和 PC OTA 是设备操作工具，由 Tester 维护。

工具入口和共享关系分别见 [Auditor](../Auditor/README.md) 与 [Tester](../Tester/README.md)。Auditor 使用本目录固定的解析库副本，Tester 控制帧生成器复用 Developer 的正式协议 codec。仓库交付检查只运行合成自检和帮助入口。

路径和所有权依据 [file-ownership.json](../metadata/file-ownership.json)，仓库检查会要求每个公共文件都具有归属。新的工具按职责放入相应目录，再更新引用和检查入口。`.github/CODEOWNERS` 使用真实 GitHub 维护者账号；角色规则见 [CONTRIBUTING](../CONTRIBUTING.md)。

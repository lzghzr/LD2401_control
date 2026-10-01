# LD2401 Control

为 **HLK LD2401 原厂固件** 添加加密 BTHome 传感器广播和通过 ESPHome 广播控制 OUT 的 Home Assistant 自定义集成。目标平台为 **JieLi Q32S**，原厂基线为 `LD2401_2.50.24110415.ufw`。

本仓库提供固件 **2.50.26092431** 的追加源码与构建工具，以及 HA 集成 **1.1.3**。传感器由 HA 内置 BTHome 集成提供；本集成提供“自动／保持低电平／保持高电平”模式下拉选择。模式由加密广播中的手动保持标志和 OUT 实际电平共同反馈。该固件已通过独立审计与实机测试，身份与覆盖见 [版本身份](metadata/firmware-26092431.json)。

## 安装与配置

1. 让 LD2401 运行 26092431 固件，按 [构建与刷写说明](docs/firmware-build.md) 获取固件及 BTHome Bindkey。
2. 将 [ESPHome 示例](esphome/ld2401_sender.example.yaml)、发送包和头文件复制到同一个 ESPHome 配置目录。创建本地 `secrets.yaml`，设置 Wi-Fi 与 API 加密密钥，安装节点并接入 HA。
3. 在 HA 内置 **BTHome** 集成中添加模块，填入模块的 Bindkey。确认传感器持续更新。
4. 将本仓库添加到 HACS 的自定义仓库，类型选择 **Integration**，安装 **HLK LD2401 OUT Control** 并重启 HA。也可将 `custom_components/ld2401_control/` 整个目录复制到 HA 配置目录的 `custom_components/` 下。
5. 控制条目会从已配置的 LD2401 BTHome 条目自动创建，也可在“添加集成”中选择本集成。选择节点的广播动作后，通过模式下拉选择控制 OUT。

详细行为见 [HA 集成说明](docs/home-assistant.md)。集成自动选择提供 `ld2401_control_broadcast` 动作且能听到模块的 ESPHome 节点；需要指定节点时，在“重新配置”中填写动作名。

## 功能与环境

| 部分 | 当前行为 |
| --- | --- |
| 固件广播 | 500 ms 更新，加密 BTHome v2；照度、手动保持、OUT 电平、运动、占用；电压与距离交替 |
| 控制 | 利用刚收到且认证成功的 BTHome counter 构造带 CMAC 的广播，ESPHome 发送 1 秒；选择立即显示，并与反馈同步 |
| 解析 | 优先复用内置 BTHome 的认证与解析；运行时接口不可用时自动回退 |
| 密钥 | 模块生成并持久保存 128-bit Bindkey；A603 读取，A604 换钥 |
| 设备复位 | 恢复出厂会换钥；刷写后重新读取 Bindkey，并更新 HA 的 BTHome 配对 |
| 使用环境 | 项目使用 HA 2026.9.3、ESPHome 2026.9.0；最低配置版本暂设为 2026.3.0 |
| 固件构建 | Windows + 杰理 Q32S 工具链；Python 构建工具支持 3.10+；保留 26092430 固定哈希复现入口 |

26092430 参考固件已由用户确认实机测试，并在目录整理后复现出同一 SHA-256；它是构建器的固定哈希复现基线，身份见 [参考记录](metadata/firmware-26092430.json)。交付固件 26092431 的独立审计与实机覆盖分别见 [审计报告](Auditor/reports/26092431-mode-feedback-r1.md) 与 [测试报告](Tester/reports/26092431-mode-feedback-r1.md)；这里的工具检查用于验证交付路径与复现，不代替独立审计或硬件测试。

## 仓库结构

```text
custom_components/ld2401_control/  HA 集成，HACS 安装内容
esphome/                          通用发送配置与头文件
Developer/src/                    固件追加 C/汇编、主机协议编解码
Developer/linker/                 Q32S 地址映射与链接断言
Developer/tools/                  固件构建与 UFW 帮助函数
docs/                             安装、协议、平台移植、发布说明
metadata/                         固定基线与参考固件身份
tools/                            仓库结构、路径与协议一致性检查
Auditor/                          专用静态核验、交叉引用工具与审计记录
Tester/                           设备操作、广播采集 / 解密、协议自检与实测记录
```

参与开发前读取 [AGENTS.md](AGENTS.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。目录内工具使用相对定位或显式参数，可将整个仓库复制到其他位置运行。完整文件职责见 [目录职责](docs/file-layout.md)。此次交付验证记录见 [路径验证](docs/packaging-verification.md)。

## 第三方资源与授权

本项目代码按 [MIT](LICENSE) 许可提供。原厂 UFW、HLKRadarTool、杰理 SDK/工具链按其提供方的授权获取，获取途径见 [构建说明](docs/firmware-build.md) 和 [第三方说明](NOTICE.md)。仓库提供追加源码，构建需自行提供匹配 SHA-256 的原厂 UFW。

HACS 只安装 HA 集成。它不会刷写雷达或 ESPHome 节点。官方布局要求见 [HACS 集成文档](https://www.hacs.dev/docs/publish/integration/)。

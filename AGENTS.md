# LD2401 agent instructions

开始工作先读 [CONTRIBUTING.md](CONTRIBUTING.md)、[固件身份](metadata/firmware-26092431.json) 和任务相关文档。

1. 目标模块 LD2401，目标平台 JieLi Q32S；目标原厂固件 `LD2401_2.50.24110415.ufw`；当前交付固件 2.50.26092431，HA 集成 1.1.0。
2. 按用户指定的 Developer、Auditor、Tester 角色工作；缺省 Developer。实现与审计/实测结论的所有权见 CONTRIBUTING。
3. 本仓库内 `Developer/src`、`Developer/linker`、`Developer/tools` 为固件正式源码入口；HA 和 ESPHome 正式实现各在同名目录。串口、PC OTA 设备工具及协议测试在 `Tester/tools`，由 Tester 维护。其他公共文件的归属见 `metadata/file-ownership.json`。
4. 正式交接从干净 Git commit 构建，用完整 commit、Build ID、UFW SHA-256 绑定；每个候选使用独立输出目录，已交接产物不可覆盖。
5. 原厂输入只读；Hook、镜像、VM、RAM 与版本字段遵守固件边界。当前版本复现必须满足构建器固定哈希。
6. 目录调整后更新所有引用，从不同 cwd 检查入口与构建，保留原始来源身份。
7. 公共文件使用相对路径与通用示例。真实设备标识、密钥、网络配置与日志保存在本地忽略目录。
8. 当前交付固件 26092431 的硬件测试由用户确认已完成，覆盖与未覆盖项见 [测试报告](Tester/reports/26092431-mode-feedback-r1.md)；26092430 参考的详细覆盖未记录。工具自检、构建断言不构成独立审计或硬件测试结论。
9. 任务授权决定设备操作和代理委派范围。本规范不额外授权刷写、强制升级、消息发送或发布。

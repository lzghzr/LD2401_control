# GitHub 发布

目标仓库：[lzghzr/ld2401_control](https://github.com/lzghzr/ld2401_control)，许可证 MIT。当前目录是待推送的仓库工作树，仓库创建和推送由维护者执行。

1. 运行 `python -B tools/check_repository.py --protocol`。
2. 配置 Git 作者，在仓库根目录检查文件后创建首次 commit。参考固件记录中的空 commit 表示首次导入来源，不是新的候选交接记录。
3. 在 GitHub 创建公开仓库，推送源码，设置说明与 topics（例如 `home-assistant`、`hacs`、`bthome`、`esphome`、`ld2401`）。
4. 配置 CONTRIBUTING 中的分支保护、PR 和 `repository-check` 必需检查。
5. 如要发布固件附件，另行确认原厂固件衍生包的分发许可。源码交付可从 commit 用 `git archive` 导出，避免把本地构建和设备日志打包。
6. 对集成发布版本，保持 GitHub Release、标签和 `custom_components/ld2401_control/manifest.json` 一致（当前 1.1.4）。固件交付身份为 Build ID `26092431-mode-feedback-r1`，其 commit 与 UFW SHA-256 由该提交的 release 构建报告绑定；26092430 保留为构建器强制匹配的固定哈希复现基线。

HACS 的仓库布局与 manifest 必需字段已配置。正式 HACS 收录还需核对 [HACS 发布要求](https://www.hacs.dev/docs/publish/integration/)，包括 Home Assistant Brands 的品牌资源；该外部资源与服务器分支规则不由本地文件自动完成。

提交产品变更时附上：问题与行为变化、commit/Build ID、构建输出 SHA-256、Developer 检查、Auditor 报告、Tester 实机覆盖，以及未解决问题。仅修改文档和交付路径时可声明对应验证范围。

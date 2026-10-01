# 固件构建与设备工具

## 准备

构建环境：Windows 10/11、Python 3.10+、杰理 Q32S 工具链。构建器使用 Python 标准库。设备工具由 Tester 维护，运行时安装：

```shell
python -m pip install -r Tester/requirements.txt
```

运行主机协议编解码或仓库的 `--protocol` 检查时，另行安装 `cryptography>=42`。

资源获取：

- 原厂固件：通过 [海凌科 LD2401 产品支持](https://www.hlktech.net/index.php?id=1290) 或 [HLKRadarTool](https://www.hlktech.com/Mobile/App/12.html) 的官方固件渠道获取 `LD2401_2.50.24110415.ufw`。渠道可用性由提供方决定，构建器只接受下述精确哈希。
- 杰理工具链：参考 [AC63 环境准备](https://doc.zh-jieli.com/AC63/zh-cn/master/getting_started/preparation/index.html) 与 [Jieli-Tech SDK](https://gitee.com/Jieli-Tech/fw-AC63_BT_SDK)。确认取得支持 `-target q32s` 的工具；本项目已使用 `C:/JL/pi32/bin` 下的三个可执行文件成功复现。

原厂 UFW SHA-256：

```text
3e518750921f9392eb71da0becc641915d4204376f7eb571c54ed4f586bab9a7
```

把它放到仓库本地 `vendor/LD2401_2.50.24110415.ufw`，或用 `--stock` 指定任意实际路径。通过 `--toolchain` 或环境变量 `JL_Q32S_BIN` 指定包含 `clang.exe`、`q32s-ld.exe`、`llvm-objdump.exe` 的目录。

## 构建

```shell
python -B Developer/tools/build.py --check-inputs
python -B Developer/tools/build.py
```

默认构建 26092431 候选并输出到 `build/26092431/`，含 UFW、ELF、反汇编、目标文件和 `build-report.json`。再次构建选择新的空目录：

```shell
python -B Developer/tools/build.py --version 26092430 --output-dir build/reproduce-26092430
```

正式交接先提交源码并确认工作树干净，再增加 `--release`。所有相对参数按当前 cwd 解释；默认输入、源码和输出相对脚本定位的仓库根目录，因此也能从其他目录调用脚本的完整路径。不得用 `python -O` 关闭断言。

26092430 参考 UFW 为 **607840 字节**，SHA-256：

```text
7e74ed708e109bbd721371a2b74244ea52743be85e9b251198cecdf1f23add7d
```

`--version 26092430` 强制此哈希，确认源码与工具链生成已测试的精确参考文件。26092431 交付固件也固定其 SHA-256，身份见 [交付记录](../metadata/firmware-26092431.json)。工具链三个可执行文件均校验已验证哈希。正式交接使用独立 Build ID 与独立输出目录，例如 `--build-id 26092431-mode-feedback-r1 --output-dir build/26092431-mode-feedback-r1 --release`；交付固件与工具链字节未变、仅从新的干净 commit 复现时沿用同一 Build ID，并用新的空输出目录重建 release 报告以绑定该 commit。构建输出与本机路径报告保存在本地，不放入公开源码归档。

## 刷写与读取密钥

可在 HLKRadarTool 中选择生成的 UFW。PC BLE OTA 工具保留为显式设备操作入口：

```shell
python -B Tester/tools/jl_ota_pc.py --mac <模块地址> --file build/26092431/LD2401_2.50_26092431.ufw --trace local/ota-trace.json
```

该工具执行升级，日志包含设备通信。当前任务的权限由操作者明确指定。普通 USB 转串口板用于串口配置，强制恢复需要单独验证的硬件通路。

串口工具默认 256000 波特率，设备操作必须指定实际串口；Linux/macOS 串口路径也可作为参数：

```shell
python -B Tester/tools/a6.py --self-test
python -B Tester/tools/a6.py --port <串口> --version
python -B Tester/tools/a6.py --port <串口> --read-key
python -B Tester/tools/a6.py --port <串口> --rotate-key
```

读出的密钥填入 HA 内置 BTHome。`--rotate-key` 执行 A604 并返回新密钥，现有配对需更新。工具自动打开配置会话并在退出时关闭，除非显式使用 `--keep-session`。

OTA 后重新读 A0 和 A603，核对两个版本字段，并根据当前密钥更新 HA；必要时重载 BTHome 集成处理 counter 重置。A2 恢复出厂会应用原厂默认配置并更换密钥。

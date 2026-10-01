# Tester

实机测试报告及工具放在本目录。记录候选 commit、UFW SHA-256、串口 A0、广播版本、测试环境、覆盖和结果；真实设备地址与密钥置于本地配置，公开报告做脱敏。按 CONTRIBUTING 的职责边界工作。

Tester 维护 `tools/a6.py`（串口配置、版本与密钥读写）、`tools/jl_ota_pc.py`（PC BLE OTA）以及一组经 ESPHome 代理与真实 HA 实例做端到端验证的工具。依赖安装使用 `python -m pip install -r Tester/requirements.txt`。入口及操作说明见 [构建与设备工具](../docs/firmware-build.md)。

纯软件协议检查入口为 `python -B Tester/tools/check_protocol.py`，使用合成公开数据验证主机与 HA 编解码一致性。该检查不会连接硬件。

## 工具覆盖

| 工具 | 用途 | 依赖 |
| --- | --- | --- |
| `tools/a6.py` | UART 版本、OUT、读取 / 重置 Bindkey | pyserial；自检只需标准库 |
| `tools/jl_ota_pc.py` | PC BLE OTA，操作前核对候选身份 | bleak |
| `tools/capture_ble.py` | 主动扫描指定 MAC，保存带时间戳的原始广播字段 | bleak |
| `tools/capture_ble_proxy.py` | 经 ESPHome BLE 代理采集广播；保留原始 AD 字节，可测空口帧长 | aioesphomeapi |
| `tools/decode_capture.py` | 离线验证 AES-CCM，解码照度、运动、占用、手动保持、OUT、电压和距离，统计 counter 速率 | cryptography |
| `tools/control_frame.py` | 用近期认证广播的 counter 生成 30 字节控制帧 | cryptography、Developer 的协议 codec |
| `tools/send_control.py` | 把已签名控制帧交给已部署的 ESPHome 动作广播，并回报结果 | aioesphomeapi |
| `tools/ha_probe.py` | 只读盘点真实 HA 实例：集成版本、条目、实体、设备、ESPHome 动作 | aiohttp |
| `tools/ha_deploy.py` | 经 `ha_file_explorer` 拉取 / 推送 / 校验集成源码（部署与回滚） | aiohttp |
| `tools/ha_out_test.py` | 经 HA 选择实体做端到端往返，并用解密广播核对空口是否真的改变 | aiohttp、aioesphomeapi、cryptography |
| `tools/check_protocol.py`、`tools/check_capture.py` | 合成协议对比、各代明文布局解码、错误 MIC 与时效检查 | cryptography |

主机适配器可能只交付 500 ms 广播流的一部分，因此 `decode_capture.py` 另报 `timeline`：由首个与末个认证 counter 的差与时间跨度算出真实节拍（主机漏报不影响该值），并检查 counter 单调。`capture_ble_proxy.py` 用 ESPHome 代理后端补足覆盖率，其 `raw`/`ad_bytes` 字段给出空口 AD 长度。

扫描模式决定代理能看到什么：ESPHome `bluetooth_proxy` 默认是**被动**扫描（`active: false`），不发 SCAN_REQ，因此代理看不到模块的扫描响应（设备名与版本厂商段都在其中），`ad_bytes` 只覆盖广播本身；节点若配成主动扫描，代理会把扫描响应并入同一条原始数据，此时 `ad_bytes` 覆盖两段。需要设备名或只测广播长度时用 `capture_ble.py` 的主动扫描。

Tester 的软件自检由工具维护者运行，硬件操作按测试任务授权执行。`control_frame.py` 调用正式协议 codec 来生成输入；`decode_capture.py` 自行读取和认证广播，作为测试观测工具。Auditor 的静态核验入口见 [Auditor](../Auditor/README.md)。

## 广播与控制测试

先用 `a6.py --port <串口> --read-key` 获取当前 Bindkey，在本地 `local/bindkey.txt` 保存一行 32 位十六进制密钥。下列 MAC 是通用示例，操作时换成目标模块地址。工具按显示顺序使用 MAC，BLE 平台需要提供真实设备地址。

```text
python -B Tester/tools/capture_ble.py --mac 02:00:00:00:00:01 --seconds 10 --output local/capture-001.json
python -B Tester/tools/decode_capture.py --capture local/capture-001.json --key-file local/bindkey.txt --output local/decoded-001.json
python -B Tester/tools/control_frame.py --mac 02:00:00:00:00:01 --key-file local/bindkey.txt --capture local/capture-001.json --mode 1
```

需要代理后端时，采集与发送改为（节点地址与 API 密钥只放在本地忽略文件）：

```text
python -B Tester/tools/capture_ble_proxy.py --host <节点> --apikey-file local/esphome.key --mac 02:00:00:00:00:01 --seconds 30 --output local/capture-002.json
python -B Tester/tools/send_control.py --host <节点> --apikey-file local/esphome.key --payload <60 位 HEX>
```

把生成的十六进制数据交给已部署的 ESPHome `ld2401_control_broadcast` 动作，参数为 `payload`，调用方式见 [HA 使用文档](../docs/home-assistant.md)。生成工具只打印数据，不发送广播。模式 `0/1/2` 对应低、高、自动。工具采用最近 50 秒内认证成功的广播 counter，给模块 120 拍的窗口留出发送时间；仍须及时发送，且一个 counter 只能执行一次。再次控制前采集新广播。专家测试可显式传 `--counter 8192`，由操作者检查其有效性。

对照下一帧解密后的 `out_high` 和实际 OUT 电平，记录手动低 / 高 / 自动、重发同 counter、错误认证、错误目标和过期 counter 的结果。广播采集得到的是操作系统交付的字段，可能合并扫描响应或过滤重复报告；counter 统计表示主机观测速率，不能代替空口射频测量。日志包含设备标识，解密日志还包含遥测信息，都保存在 Git 忽略的本地目录，公开报告须脱敏。OTA 或恢复出厂后重新确认密钥。

## 真实 HA 实例测试

集成侧的端到端行为只能在真实实例上验证：`select` 实体、可用性、经 HA 的发送端选择、以及 HA → ESPHome → 空口 → 反馈 → 实体状态的闭环。下列工具不代替离线检查，而是补上这一段。

凭证只放本地忽略文件：`local/ha-token.txt` 两行，第一行基址、第二行长时访问令牌；集成源码的推送经 `ha_file_explorer` 的 `/ha_file_explorer-api`（路径相对 HA 配置目录），因此需要该集成已装并可访问。

```text
# 只读盘点：集成版本、条目、实体、可用性、ESPHome 发送端
python -B Tester/tools/ha_probe.py --token-file local/ha-token.txt --insecure

# 部署闭环：先 pull 备份（push 要求已有备份目录），push 后重启 HA，再 verify
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure --dir local/ha-installed pull
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure --dir local/ha-installed push
python -B Tester/tools/ha_deploy.py --token-file local/ha-token.txt --insecure verify

# 端到端往返：每次选择后同时记录 HA 状态与解密广播里的 hold / out_high
python -B Tester/tools/ha_out_test.py --token-file local/ha-token.txt --insecure \
    --entity select.ld2401_<末4位>_out_mode --mac 02:00:00:00:00:01 --key-file local/bindkey.txt \
    --proxy-host <代理节点> --apikey-file local/esphome.key
```

判读要点：

- **命令是否真的改变了 OUT**：只看实体状态不够——广播里的 `0x0F`/`0x10` 是状态**报告**，恰好一致不能证明是广播驱动的。用「雷达报告占用时命令保持低」这类与自动控制期望相反的对照，或用 `ha_out_test.py` 同时比对空口。
- **HTTP 500 不等于集成缺陷**：HA 对服务调用中的 `HomeAssistantError` 一并以 500 返回（对 HA 自身的标准校验错误也一样），可操作信息在 HA 日志里；失败尝试要按「未发送」与「已发送但无效」分开统计，后者才是发送端选择问题。
- **HA 的认证接收率可能远低于发送节拍**：集成要求选择后出现更新的 counter，等待窗口有限。主机或代理的交付率低会让部分命令以「等不到新 counter」失败，这是环境问题，与路由无关；实测时先记录接收率再解释失败比例。
- **自定义组件改动需重启 HA** 才会加载；`ha_deploy.py push` 只覆盖本仓库的文件，不删除任何东西，回滚用备份目录重新 push。
- ESPHome 节点若未使用 `api.respond`，动作是 fire-and-forget：节点拒绝或未连接不会变成失败调用。

工具的 Python 路径从自身文件定位，支持仓库整体迁移以及从其他当前目录调用；设备后端可用性按系统分别验证。离线自检：

```text
python -B Tester/tools/check_capture.py
```

26092430 已由用户确认测试，详细覆盖未在本仓库导入记录。26092431 的实机测试记录见 [reports/26092431-mode-feedback-r1.md](reports/26092431-mode-feedback-r1.md)。

# 复现 APK 和表盘分析

## APK 样本

历史分析使用小米运动健康 3.59.2，Android 包名 `com.mi.health`。样本来自[小米官方入口](https://hlth.io.mi.com/download?appId=mifitness)，该入口可能提供新版。相同版本可在本仓库的 [v0.1.0 Release](https://github.com/starrythm/Openband/releases/tag/v0.1.0) 下载。

| 文件 | SHA-256 |
| --- | --- |
| `MiFitness-3.59.2.apk` | `112e603b8342cb134402a6dcabdf3ec16fd5171ec65a1d5f7cb7efd83cb0995d` |
| `jadx-headless-mcp-0.7.1-all.jar` | `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75` |

从 [JADX Headless MCP v0.7.1](https://github.com/1013503897/jadx-headless-mcp/releases/tag/v0.7.1) 获取 JAR。把 APK 和 JAR 放到 `inputs/`，执行以下 PowerShell 脚本。它会校验散列，用 REA 6.5.0 检查 APK 并反编译与通信有关的方法，把 JSON 输出写到 `build/apk-analysis/`。Release 另附历史分析中的关键方法摘录。

```powershell
./tools/analyze-apk.ps1
```

| 路径 | 观察点 | 对应实现 |
| --- | --- | --- |
| 绑定模式和账号授权 | `WearBinderV2` 的模式选择，`PSKWearBinderV2` 的公钥、签名、OOB 和绑定提交 | [binding.py](../client/binding.py)、[cloud.py](../client/cloud.py) |
| 传输和正式认证 | `ApiCallFactory` 的 SPP 选择，`SppVersionReader` 的版本协商，`WearAuthV2` 的双向校验 | [spp_transport.py](../client/spp_transport.py)、[authentication.py](../client/authentication.py) |
| 命令收发 | `BlueToothSender` 的通知命令，认证后的封包、序号和响应分发 | [wire.py](../client/wire.py)、[spp_codec.py](../client/spp_codec.py) |

## 从 OTA 提取原厂表盘

下载 [o66nfc 3.1.16 全量 OTA 归档](https://github.com/hrk666666/firmware-archives-public/releases/download/firmware-miwear.watch.o66nfc-v3.1.16-11068792/miwear.watch.o66nfc_v3.1.16_full_435fd32b.bin) 并保存为 `inputs/o66nfc-3.1.16.bin`。它的 SHA-256 是 `435fd32b5a23e4ed81f712a7047fdcd4a4577fdfffa7a9f38e0d8bac7a6470d9`。提取脚本校验归档及表盘分区，把「瓷影」表盘资源写到本地。

先按 [README 的构建步骤](../README.md#自定义和重建) 准备并编译固定版本的 Mi8WfBinTool，再运行以下命令。

```powershell
python tools/extract_watchface.py inputs/o66nfc-3.1.16.bin build/reference/resource.bin
java -cp build/watchface/classes Mi8WfBinTool unpack build/reference/resource.bin build/reference/unpacked o66
```

解包后的 `wfDef.json` 描述表盘元素和资源引用。查看 `images/_lua/smash11/smash.lua`，可以找到原厂的 `lvgl` 对象、`dataman.subscribe` 和 `ScreenStateChangedCB`。本项目以相同的 Lua 入口约定加载自己编写的星图。

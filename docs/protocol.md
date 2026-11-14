# Windows 与小米手环 10 NFC 的通信流程

表中的命令号采用 `类型/子类型`。本项目的实机基线是 M2456B1、固件 3.1.16。

## BLE 绑定

1. Windows 用 GATT 连接已选设备，通过小米 FE95 服务的 `005E` 接收、`005F` 发送。在 V2 会话里发送 `1/17`，查询设备绑定模式。
2. 本机响应是 `verifyMode=1`、`oobMode=3`。按 APK 的 `PSKWearBinderV2` 路径，用户在官方小米账号页面登录。客户端交换 `miothealth` 服务会话并用当前用户的 DPAPI 保存。
3. 经 `bind/hello` 取得服务器公钥、签名与随机数，通过 `1/18` 交给手环。把手环的公钥和签名提交到 `bind/ecdh`，取回绑定用 `device_key` 及 OOB 材料。
4. 经 `1/19` 进行带 OOB 的 HMAC-SHA256 双向确认，并在手环上确认。服务器 `bind/bind` 返回 `ret=1` 后，用绑定密钥对账号与伴侣设备信息做 AES-CCM 封装，通过 `1/25` 让手环提交绑定。

实现见 [登录交换](../client/login_flow.cjs)、[云请求及加密](../client/cloud_crypto.py)、[绑定状态机](../client/binding.py) 和 [BLE V2](../client/wire.py)。

## 经典蓝牙 SPP 和 WearAuthV2

读取绑定后的设备列表与产品配置，校验目标地址、型号、设备 ID 和本机伴侣标识。小米运动健康为 `pd_type=7` 选择经典蓝牙 SPP，正式会话使用设备记录中的 `detail.encrypt_key`。

Windows 建立系统配对，通过 SDP 查询标准串口服务 UUID `00001101-0000-1000-8000-00805f9b34fb` 的 RFCOMM 通道。验证设备实际使用通道 5。客户端先以旧式 `BA DC FE` 帧查询串口协议版本，实测返回 3.1.11，随后切换到 `A5 A5` 的 V2 帧。

WearAuthV2 通过 `1/26` 和 `1/27` 交换随机数，用 `encrypt_key` 经 HKDF-SHA256 派生读写材料，核对双方 HMAC，收到确认后启用会话密钥。V2 普通命令按官方实现用 AES-CTR。每次连接均执行应用层认证；系统配对和账号绑定会保留。

实现见 [Windows 配对与 SDP](../client/windows_spp.py)、[SPP 传输](../client/spp_transport.py)、[帧和序号](../client/spp_codec.py)、[连接材料校验](../client/metadata.py) 和 [WearAuthV2](../client/authentication.py)。

## 表盘安装

| 阶段 | 命令 | 校验 |
| --- | --- | --- |
| 读列表 | `4/0` | 核对当前表盘和包内 ID |
| 申请安装 | `4/4` | 提交 ID、长度和版本，等待设备进入就绪状态 |
| 申请文件传输 | `22/0` | MASS 资源类型 16，核对 MD5 和协商分片长度 |
| 传资源 | MASS 分片 | 资源封装带 CRC32，分片带总数和序号，外层 V2 帧带 CRC16 |
| 核对安装 | `4/5` | 核对安装状态与表盘 ID |
| 切换并读回 | `4/1`、`4/0` | 确认目标表盘在设备列表中且为当前项 |

MASS 分片 ACK 表示该帧已接收，安装验收看设备的应用层回执和列表。实装 Micro Star 2 的 ID 是 `826104732`，历史上传共 4 片，设备返回 `INSTALL_USED`，随后确认显示正常。发布版客户端保留相同的安装和回读流程，设备地址从命令行输入。

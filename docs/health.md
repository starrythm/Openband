# 健康数据

## 从手环读取

按 [README](../README.md#在-windows-上运行) 准备 Windows 蓝牙配对和本机认证资料。下次导出可直接复用现有资料。

```powershell
$bandAddress = Read-Host '手环蓝牙地址'
python client/health.py capture --address $bandAddress
```

默认输出到已被 Git 忽略的 `.state/health/<时间戳>/`，终端会打印目录和记录数。可用 `--out` 指定一个尚不存在的目录。关闭占用同一手环 SPP 连接的程序后再读取。

- `raw/` 保存收到并通过 CRC32 校验的文件。每个文件按手环在内容中提供的 ID 保存。
- `decoded/` 保存已识别字段。尚未识别的文件格式仍保留原始字节。清单记录解析错误和未收到的文件 ID。
- CSV 提供每分钟读数、每日汇总和睡眠阶段。有对应读数时还会生成单独的心率、压力、血氧或手动测量表。设备零值占位在每分钟读数表中留空。时间保留设备时区偏移，异常时钟记录会标注。

可以用 `python client/health.py tables <导出目录>` 重新生成表格。例图可用 `python tools/plot-health-example.py` 重建，需要 Matplotlib 和 CJK 字体。图中数据全部由生成脚本定义。

## 发送到 HTTPS 接收端

```powershell
$snapshot = Read-Host '导出目录'
$receiver = Read-Host '你自己的 HTTPS 接收地址'
python client/health.py upload $snapshot --url $receiver
```

上传只在运行这条命令时发生。接收端应接受带 `Content-Type: application/zip` 的原始 HTTP POST 请求体，成功时返回 HTTP 2xx。如果需要 Bearer token，通过当前进程的 `OPENBAND_HEALTH_TOKEN` 环境变量提供。客户端使用系统的 HTTPS 证书校验，拒绝重定向，并只输出 HTTP 状态码。归档包含健康记录，请使用自己控制的私有接收端。

## 协议与覆盖范围

客户端建立已认证的 Windows SPP V2 会话，用 FITNESS `8/1` 和 `8/2` 获取今日及历史文件清单，再通过 `8/3` 请求文件。设备通过数据通道 5 返回分片，其中也可能包含清单以外的记录。客户端按分片顺序组装、校验 CRC32 并读回落盘文件。会话继续确认传输帧，导出不会发送会把文件标为已同步的 `8/5`。

小米手环 10 NFC（M2456B1，固件 3.1.16）实测读取了心率、压力、睡眠阶段和日常活动。这个入口只能读取手环当前返回的数据。完整云端历史、未测量的指标或仅在小米运动健康 App 内计算的结果需要从对应来源取得。

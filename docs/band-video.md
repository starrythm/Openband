# 手环视频 · 《灯与翅膀》

一只提灯机器人在停电的港城出发，途中用最后一盏灯救起落水的纸鸟。纸鸟带着鸟群回来点亮灯塔，故事在黎明结束。[观看完整 MP4](../apps/lampwings/lampwings.mp4)

## 从故事到手环

1. [渲染源码](../apps/lampwings/render_film.py)用 Pillow 绘制七个连续镜头，包括人物、鸟群、光线、雨和水面。程序以每秒 30 帧输出画面，合成原声配乐，生成 424×1040 的 MP4。手环版播放本地画面，配乐保留在 MP4 中。
2. [编码与打包脚本](../apps/lampwings/pack_movie.py)把同一条时间线转成 212×520 的 MJPEG AVI，共 900 帧。它逐项检查 AVI 帧索引与 JPEG 边界，然后将数据切成 48 KiB 的块，分别存入 RPK。高清配置会按包大小选定量化参数。小米手环 10 NFC 的 [原生屏幕规格](https://www.mi.com/tw/product/xiaomi-smart-band-10/specs/)为 212×520 像素。
3. [分段读取](../apps/lampwings/watch/src/common/clip-reader.js)通过 `system.file` 读取应用资源，缓存两块文本，只解码当前帧需要的字节。 [AVI 索引解析](../apps/lampwings/watch/src/common/avi.js)负责定位这些字节，开播时读取文件头和索引。
4. [手环页面](../apps/lampwings/watch/src/pages/index/index.ux)把 JPEG 写入本地缓存，由全屏 `image` 组件显示。上一帧显示时预取下一帧，按视频时间线安排显示。若设备来不及显示所有帧，播放器会追赶时间线，片尾列出显示帧率和掉帧数。播放时申请保持亮屏，停播时释放。此处使用的是 [小米 Vela 亮屏接口](https://iot.mi.com/vela/quickapp/zh/features/system/brightness.html)。
5. [安装器](../client/quickapps.py)从既有蓝牙配对建立 SPP V2 会话，经 WearAuthV2 认证后用 MASS 分片传输 RPK，读取安装结果并用应用清单复核版本。

## 构建和播放

按 [README](../README.md#在-windows-上运行) 准备 Windows 电脑、设备配对和 Openband 的本机认证资料。下面的命令在仓库根目录运行。编码器通过 `imageio-ffmpeg` 提供。

```powershell
python -m pip install -r client/requirements.txt -r apps/lampwings/requirements.txt

# 可选。重新合成画面和配乐，覆盖仓库里的示例 MP4
python apps/lampwings/render_film.py

python apps/lampwings/pack_movie.py --profile high
Push-Location apps/lampwings/watch
npm.cmd install
npm.cmd run build
Pop-Location

$bandAddress = Read-Host '手环蓝牙地址'
python client/quickapps.py --address $bandAddress install lampwings
```

在手环上打开「灯与翅膀」并点播放。成片随 RPK 一起存储，播放时可离开电脑。如果同名应用已经存在，升级步骤见 [Quick App 说明](quickapps.md)。

配套 1.1.0 高清版在小米手环 10 NFC 上完成安装与版本读回。主片和手环数据均通过 900 帧解码，逐帧复核了分段读出的 JPEG。30 帧/秒是编码和调度目标。真机实际显示帧率以本次播放的片尾统计为准。

# 参考项目

- [REA](https://github.com/morluto/rea) 和 [JADX Headless MCP](https://github.com/1013503897/jadx-headless-mcp) 用于分析小米运动健康 APK。小米官方 APK 和反编译样本的权利归相应权利人。
- [Freeband](https://github.com/cobanov/freeband) 提供小米 BLE V2 协议参考。`client/activity_ref.py` 复用其 [活动文件解析器](https://github.com/cobanov/freeband/blob/9aa5f58f0aa8d96968052919a513126052d72301/ios/tests/activity/activity_ref.py)，保留原版权并省略上游 CLI 和测试运行器。[MIT 许可](Freeband-MIT.txt)
- [AstroBox NG Core](https://github.com/AstralSightStudios/AstroBox-NG-Module-Core) 和 [AstroBox NG Protobuf](https://github.com/AstralSightStudios/AstroBox-NG-Module-Pb) 用于交叉核对表盘和 MASS 命令及字段。
- [mi-health-mcp](https://github.com/Zhou-Ruichen/mi-health-mcp) 提供小米服务会话交换的参考。
- [Mi8WfBinTool](https://github.com/zhy8388608/Mi8WfBinTool) 用于拆包和打包。`tools/o66-unpack.patch` 记录本项目为原厂嵌套脚本资源及单表盘解包所做的改动。
- [Paul Schlyter 的轨道公式](https://www.stjarnhimlen.se/comp/ppcomp.html) 用于 Lua 星图计算。[Astronomy Engine](https://github.com/cosinekitty/astronomy) 2.1.19 的 JavaScript 代码用于离线对照，MIT 许可见源码头部。

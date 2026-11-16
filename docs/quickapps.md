# Quick App 安装

[安装脚本](../client/quickapps.py)使用 Openband 现有的 Windows 配对及 DPAPI 会话文件。请先按 [仓库首页](../README.md#在-windows-上运行) 完成配对和认证，并关闭正在连接该手环的其他 Openband 进程。

```powershell
$bandAddress = Read-Host '手环蓝牙地址'
python client/quickapps.py --address $bandAddress list
# 选择灯与翅膀，或将 lampwings 换成 codex-quota
python client/quickapps.py --address $bandAddress install lampwings
```

第一次安装会读取 RPK 的包名和版本，通过 MASS 传输。收到安装结果后再读取手环应用清单，确认版本并把包指纹保存到本机 `.state/apps/`。

升级自己此前装的应用时，先为源码中的 `versionCode` 加一，改 `versionName` 并重新构建。如果这是第一次在这个仓库里操作手环上已有的应用，用 `remember` 记录此前的包指纹。然后用 `--update` 显式升级。

```powershell
python client/quickapps.py --address $bandAddress remember lampwings
python client/quickapps.py --address $bandAddress install lampwings --update
```

脚本会对照已保存的设备地址、包名、版本及指纹。只有新版本更高才会提交替换。两个应用的构建目录、调试 RPK 和本机设备资料都由 Git 忽略。

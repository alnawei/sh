# 默认 x-ui

这个文件夹存放 `KEJI.SH` 主菜单 `5. 默认x-ui` 使用的脚本。

入口文件：

```text
x-ui/XUI.sh
```

上传到 GitHub 后，`toolbox.sh` 会从本仓库读取：

```text
https://raw.githubusercontent.com/alnawei/sh/main/x-ui/XUI.sh
```

当前版本默认使用 `vaxilu/x-ui` 官方安装脚本：

```text
https://raw.githubusercontent.com/vaxilu/x-ui/master/install.sh
```

安装、重置用户名密码、设置面板端口时会自动使用以下默认值：

```text
用户名: admin
密码: admin
端口: 54321
```

菜单 `4. 重置用户名密码` 会直接重置为 `admin/admin`。
菜单 `6. 设置面板端口` 会直接重置为 `54321`。

以后需要修改默认 x-ui 功能时，直接编辑本文件夹里的 `XUI.sh`。

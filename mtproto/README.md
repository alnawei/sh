# 默认 MTProto

这个文件夹存放 `KEJI.SH` 主菜单 `1. 默认MTProto` 使用的脚本。

当前版本使用 faketls 模式，伪装域名为 `icloud.com`，监听端口为
`18888`。进入后只展示运行状态；输入 `1. 安装实例` 时才会安装或更新
默认实例。

入口文件：

```text
mtproto/MTP.sh
```

上传到 GitHub 后，`toolbox.sh` 会从本仓库读取：

```text
https://raw.githubusercontent.com/alnawei/sh/main/mtproto/MTP.sh
```

以后需要修改默认 MTProto 功能时，直接编辑本文件夹里的 `MTP.sh`。

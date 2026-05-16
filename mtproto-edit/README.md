# 编辑 MTProto

这个文件夹存放 `KEJI.SH` 主菜单 `2. 编辑MTProto` 使用的脚本。

入口文件：

```text
mtproto-edit/MTP.sh
```

上传到 GitHub 后，`toolbox.sh` 会从本仓库读取：

```text
https://raw.githubusercontent.com/alnawei/sh/main/mtproto-edit/MTP.sh
```

以后需要维护第二套 MTProto 逻辑时，直接编辑本文件夹里的 `MTP.sh`。

当前版本保留多实例管理菜单，并在实例安装完成后自动展示 MTProxy 链接。
管理菜单里也提供 `编辑密钥`，可以直接替换已有实例的密钥。

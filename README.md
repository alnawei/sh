# KEJI.SH

一个可以部署到 GitHub Pages 的 Linux Bash 工具箱模板。

## 文件说明

- `toolbox.sh`: 终端菜单脚本，用户通过 `curl` 远程执行。
- `index.html`: GitHub Pages 展示页，带安装命令和终端预览。
- `mtproto/MTP.sh`: 默认 MTProto 模块，主菜单 `1. 默认MTProto` 会调用它。
- `mtproto-edit/MTP.sh`: 编辑 MTProto 模块，主菜单 `2. 编辑MTProto` 会调用它。
- `.nojekyll`: 让 GitHub Pages 原样发布静态文件。

## 部署到 GitHub

1. 新建一个 GitHub 仓库，例如 `mytool-sh`。
2. 把本目录文件推送到仓库的 `main` 分支。
3. 进入仓库 `Settings` -> `Pages`。
4. `Build and deployment` 选择：
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/root`
5. 保存后等待 Pages 发布。

发布后访问：

```text
https://USERNAME.github.io/REPO/
```

远程执行命令：

```bash
bash <(curl -fsSL https://USERNAME.github.io/REPO/toolbox.sh)
```

把 `USERNAME` 改成你的 GitHub 用户名，把 `REPO` 改成仓库名。

安装 `k` 快捷命令：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/alnawei/sh/main/toolbox.sh) --install-k
```

安装后可以直接运行：

```bash
k
```

## 使用自定义域名

如果你绑定了自定义域名，例如：

```text
https://tool.example.com
```

执行命令可以改成：

```bash
bash <(curl -fsSL https://tool.example.com/toolbox.sh)
```

如果想做到类似：

```bash
bash <(curl -fsSL https://tool.example.com)
```

GitHub Pages 不太适合同一个根路径同时服务网页和 Bash 脚本。推荐用
`/toolbox.sh` 作为脚本地址，或者用 Cloudflare Worker / Nginx 根据路径单独分流。

## 本地测试

检查脚本语法：

```bash
bash -n toolbox.sh
```

本地运行：

```bash
bash toolbox.sh
```

临时预览网页：

```bash
python3 -m http.server 8080
```

然后打开：

```text
http://localhost:8080
```

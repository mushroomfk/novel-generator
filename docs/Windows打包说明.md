# Windows 打包说明

这份说明记录 Windows 安装包的生成方式和验证边界。

## 推荐方式

使用 GitHub Actions 手动触发：

```text
Windows Desktop Release
```

工作流文件在 [windows-release.yml](../.github/workflows/windows-release.yml)。

工作流会在 `windows-latest` 上完成：

1. 安装 Node.js 20、Python 3.12 和 Rust stable
2. 执行 `npm ci --ignore-scripts --no-audit --no-fund`
3. 创建 `.venv`，安装 `backend` 和 `pyinstaller`
4. 执行 `npm run verify:desktop:windows`
5. 上传 Windows 安装包和 sidecar

`npm run verify:desktop:windows` 会先执行 `npm run verify:packaging-static`，检查内置 Embedding 模型文件、前端静态回归、API / local smoke、模型预检、Windows sidecar 打包脚本、Windows 发布验证脚本和 GitHub Actions 工作流关键步骤。macOS 本机也可以执行 `npm run verify:packaging-static` 做同样的静态检查，但它不会生成 Windows 安装包，也不能替代 Windows runner 或 Windows 实机验证。

上传产物包括：

- `src-tauri/target/release/bundle/nsis/*.exe`
- `src-tauri/binaries/novel-backend-x86_64-pc-windows-msvc.exe`

## 测试包整理

`0.1.4` Windows 测试产物已整理到：

```text
release/test-release/windows/稿匣_0.1.4_测试包/
```

目录包含：

- `稿匣_0.1.4_x64-setup.exe`
- `novel-backend-x86_64-pc-windows-msvc.exe`
- `SHA256SUMS.txt`
- `安装说明-先看这个.md`
- `测试反馈清单.md`
- `包信息.txt`

共享给测试用户时优先提供 `稿匣_0.1.4_x64-setup.exe` 和安装说明；sidecar 文件保留给排查打包问题，不需要普通用户手动运行。

截至 2026-06-10，`0.1.3` Windows 测试包已由 GitHub Actions `Windows Desktop Release` run `27259635805` 在分支 `codex/full-verification-windows-20260609` 的提交 `943cd574b2ffa7fc9f8e486377f31b6d400c5d14` 构建完成；本地已整理到 `release/test-release/windows/稿匣_0.1.3_测试包/` 并通过 SHA256 校验。Windows 实机安装、卸载和首次启动仍需人工验收。

截至 2026-06-13，`0.1.4` Windows 测试包已由 GitHub Actions `Windows Desktop Release` run `27428032565` 在分支 `codex/full-verification-windows-20260609` 的提交 `6ae79e4443ec2c92a6f14bc1aacfbb43997fa8df` 构建完成；本地已整理到 `release/test-release/windows/稿匣_0.1.4_测试包/` 并通过 SHA256 校验。安装程序 SHA256 为 `90c0ee2dc5e4290d34ea2ad00be3805d85fe30a803ab7fe93d63b85794950239`，Windows sidecar SHA256 为 `c25ad3c95e79ac684beebc33d4c7c0dff91af974544581f1a523ba5330c66774`。Windows 实机安装、卸载、首次启动和安装后 GUI 操作仍需人工验收。

## 本地 Windows 打包

环境要求：

- Node.js 20+
- npm 10+
- Python 3.12
- Rust stable，目标为 `x86_64-pc-windows-msvc`
- Visual Studio Build Tools 和 Windows SDK

首次准备：

```powershell
npm ci --ignore-scripts --no-audit --no-fund
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e backend pyinstaller
rustup default stable
rustup target add x86_64-pc-windows-msvc
```

执行验证和打包：

```powershell
npm run verify:desktop:windows
```

这条命令会做：

- 检查打包配置静态项
- 运行 Windows backend 单测
- 构建前端
- 用 PyInstaller 打包 Windows sidecar
- 拉起 sidecar，检查 `/api/app/health`、`/api/config/test` 本地 Embedding 和 `/api/app/shutdown`
- 执行 Tauri NSIS release 构建
- 检查 NSIS `setup.exe` 是否生成

## 边界

已经覆盖：

- Windows backend 单测
- 前端生产构建
- Windows sidecar 打包
- sidecar 运行级健康检查和本地 Embedding 加载检查
- Tauri Windows 安装包构建
- GitHub Actions 产物上传

还没覆盖：

- Windows 实机安装、卸载和首次启动
- 代码签名证书和 SmartScreen 信誉
- 安装后 GUI 操作回归
- 自动更新渠道

## 依据

- Tauri Windows installer 文档：[Windows Installer](https://v2.tauri.app/distribute/windows-installer/)
- PyInstaller 文档：[Supporting Multiple Operating Systems](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems)

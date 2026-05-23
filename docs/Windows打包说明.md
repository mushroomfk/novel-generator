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

上传产物包括：

- `src-tauri/target/release/bundle/nsis/*.exe`
- `src-tauri/binaries/novel-backend-x86_64-pc-windows-msvc.exe`

## 测试包整理

从 GitHub Actions 下载的 Windows 测试产物整理到：

```text
release/test-release/windows/稿匣_0.1.1_测试包/
```

目录包含：

- `稿匣_0.1.1_x64-setup.exe`
- `novel-backend-x86_64-pc-windows-msvc.exe`
- `SHA256SUMS.txt`
- `安装说明-先看这个.md`
- `测试反馈清单.md`

共享给测试用户时优先提供 `稿匣_0.1.1_x64-setup.exe` 和安装说明；sidecar 文件保留给排查打包问题，不需要普通用户手动运行。

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

- 运行 Windows backend 单测
- 构建前端
- 用 PyInstaller 打包 Windows sidecar
- 拉起 sidecar，检查 `/api/app/health` 和 `/api/app/shutdown`
- 执行 Tauri NSIS release 构建
- 检查 NSIS `setup.exe` 是否生成

## 边界

已经覆盖：

- Windows backend 单测
- 前端生产构建
- Windows sidecar 打包
- sidecar 运行级健康检查
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

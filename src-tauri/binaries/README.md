将 Python backend 打包为可执行文件后，放入当前目录并按 Tauri 规则补上目标三元组后缀。

示例：
- `novel-backend-aarch64-apple-darwin`
- `novel-backend-x86_64-apple-darwin`
- `novel-backend-x86_64-pc-windows-msvc.exe`

当前仓库已经完成：

- `externalBin` 位置预留
- Tauri 启动时拉起 backend
- 前端读取动态 `backend_url`
- 退出时回收 backend 进程
- macOS / Linux sidecar 打包脚本
- Windows sidecar 打包脚本和 GitHub Actions 打包流程

macOS / Linux 使用：

```bash
npm run backend:bundle
```

这条脚本会自动检测当前目标三元组，并生成对应文件名。

Windows 使用：

```powershell
npm run backend:bundle:windows
```

Windows 默认生成：

```text
src-tauri/binaries/novel-backend-x86_64-pc-windows-msvc.exe
```

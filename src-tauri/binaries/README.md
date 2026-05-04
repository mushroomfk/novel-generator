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

发布版还差的只有 sidecar 打包这一步。

本仓库现在已经提供脚本：

```bash
npm run backend:bundle
```

脚本会自动检测当前目标三元组，并生成对应文件名。

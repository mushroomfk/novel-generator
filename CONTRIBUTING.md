# 贡献说明

感谢你关注 `稿匣`。这个项目仍处于公开预览阶段，欢迎通过 issue 或 pull request 反馈问题、补充文档和改进实现。

## 开发环境

- `Node.js 20+`
- `npm 10+`
- `Python 3.12`

安装依赖：

```bash
npm run deps:install
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e backend
```

## 提交前检查

常规代码改动建议执行：

```bash
npm run backend:test
npm run build
```

涉及主界面、Agent 流程、技能库或工作台交互时，建议加跑：

```bash
npm run verify:ui
```

涉及 Tauri 壳层、sidecar 打包或桌面发布脚本时，建议加跑：

```bash
npm run verify:desktop
```

## Pull Request

- 说明改动目的和影响范围
- 列出实际执行过的验证命令
- 不提交 `.env`、本地作品数据、证书、数据库、日志、打包产物和 API Key
- 不把第三方受版权保护的正文、未授权素材或个人隐私数据放进仓库

## 许可

项目使用自定义许可。提交贡献即表示你同意贡献内容按本仓库的 [LICENSE](./LICENSE) 一并分发。

# 题研 · 本地学习台

面向高中题目整理、错题复习、组卷与英语单词学习的本地应用。正式版使用本地 OCR、布局与公式模型；识别结果可人工校对。FastAPI + SQLite 后端，React + TypeScript 前端。

## 项目结构

```text
subjects-learning-2/   正式本地识别版，端口 8000
subjects-learning-1/   外部 AI 旧版，端口 8001
dependencies/         可提交的依赖锁文件、模型清单、来源及校验值
runtimes/             本地 Python、OCR/公式/笔迹运行库和模型，不提交 Git
scripts/              统一安装、迁移修复、检查和源码打包
docs/                 安装、架构、迁移验收与 GitHub 上传说明
发布包/源码/           最新 GitHub 源码 ZIP 和校验信息，不提交 Git
runtime.json          共享运行目录配置，路径相对仓库根目录
归档/                 本地历史快照，不提交 Git
```

## 使用

本机依赖已迁到当前文件夹，双击根目录 `start-local.cmd`，访问 <http://127.0.0.1:8000/>。停止使用 `stop-local.cmd`。两版独立保存数据。

从 GitHub 克隆后的首次安装（Windows x64、Python 3.12，前端还需 Node.js）：

```powershell
./scripts/setup.ps1 -Formula -Frontend -Renderer
./start-local.cmd
```

安装过程下载依赖和基础模型。高级模型按需恢复，详见 [安装与迁移](docs/INSTALL.md)。普通 OCR 在本机运行；主动请求外部 AI 时自行配置对应项目的 `.env`。

## 开发与上传

- [正式版功能与维护](subjects-learning-2/README.md)
- [依赖分类](dependencies/README.md) · [仓库架构](docs/ARCHITECTURE.md)
- [GitHub 上传步骤](docs/GITHUB.md) · [第三方来源](THIRD_PARTY_NOTICES.md)
- [OCR 依赖迁移验收](docs/MIGRATION-2026-10-24.md)
- [版本说明](docs/版本说明.md)

源码仓库保存代码、依赖规格、模型来源和校验值。个人数据库、原始图片、密钥、历史包、模型权重和已安装运行库由 `.gitignore` 排除。上传前运行 `scripts/package-source.py`，在 `发布包/源码/` 生成纯源码 ZIP 和校验信息；完整数据备份继续使用各版 `scripts/package-project.py`。

本地整理约定：正式工作在两个版本目录内进行；已完成测试与验收输出归入 `归档/验证记录/`，旧完整包保存在 `归档/历史版本包/`。移动清单保存在 `归档/整理记录/2026-10-24-本地目录整理/`。缓存集中到 `runtimes/cache/`，原图、数据库和业务备份分别保留在各版 `data/`。

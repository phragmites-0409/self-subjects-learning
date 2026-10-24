# 仓库与 OCR 依赖架构

```text
subjects-learning/
├─ subjects-learning-3/       当前应用：FastAPI + React + Supabase Auth
│  └─ data/accounts/<id>/    每个账号独立的 SQLite 和对象文件，Git 忽略
├─ subjects-learning-2/       上一版本地识别应用
│  ├─ backend/app/core/      配置、运行目录和便携模型路径解析
│  ├─ backend/app/modules/learning/
│  │                       OCR、布局、笔迹、修复、公式与业务流程
│  ├─ backend/tests/        接口、数据保护、业务与路径迁移测试
│  ├─ frontend/             前端源码及 npm 锁文件
│  ├─ scripts/              模型准备、转换、启停与打印工作进程
│  └─ data/                 正式数据，Git 忽略
├─ subjects-learning-1/       外部 AI 旧版，独立数据和 8001 端口
├─ dependencies/             可版本管理的依赖定义、模型清单和来源
├─ runtimes/                 本地安装的解释器、库、权重，Git 忽略
├─ scripts/                  统一安装、运行配置、检查、源码打包
├─ docs/                     安装、架构和 GitHub 发布说明
├─ 发布包/源码/               GitHub 源码 ZIP 与校验信息，Git 忽略
├─ .github/workflows/        后端回归、前端测试和构建
├─ supabase/                 与 GitHub 集成同步的数据库迁移
├─ runtime.json              唯一共享运行目录配置
└─ 归档/                     历史版本包、验证记录与移动清单，Git 忽略
```

1. 启动脚本读取 `runtime.json`，设置项目数据目录和本地库路径。
2. `core/runtime.py` 将模型清单中的 `runtime:/` 展开成绝对路径，阻止路径越出运行目录；不依赖启动时的当前目录。
3. `local_ocr.py` 使用 RapidOCR 和 RapidLayout，公式任务通过独立 Python 子进程处理，子进程清除主环境 `PYTHONPATH`。
4. GLM-OCR、UVDoc、LaMa、ExamInk 和公式渲染共用运行目录配置；每个模型保留来源和校验信息。
5. 正式服务使用本地权重；联网下载集中在显式执行的安装/准备脚本。

当前启动入口优先使用 -3。`version.json` 负责版本、识别模式与端口，Python 与库位置以根目录 `runtime.json` 为准。Python、PowerShell、Node 三类入口遵循同一配置。主 OCR 与公式、PyTorch 导出工具保持独立环境。

Supabase Auth 管理邮箱与密码；后端校验登录并按用户 ID 选择本地存储目录。`supabase/migrations/` 只保存云端小数据结构；原图、大文件及题库仍在主设备。GitHub Integration 的 Working directory 为 `.`，生产部署开启后自动应用新迁移。

前端保留各自 `package-lock.json`。本机旧安装的共用 `node_modules` 已迁入仓库；干净克隆由 `npm ci` 为各前端安装依赖，无需目录联接。

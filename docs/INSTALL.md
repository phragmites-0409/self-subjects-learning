# 安装与迁移

## 本机启动

在仓库根目录双击 `start-local.cmd`，打开 <http://127.0.0.1:8000/>。AI 旧版使用 `subjects-learning-1/start-local.cmd`，端口 8001。

模型和库已复制到 `runtimes/`，不再依赖原 D 盘运行目录。D 盘原件保留作回退。Python 标准库和原有基础库一起迁移；Node.js 仍使用本机安装。

启动时自动修正公式、笔迹导出环境的 `pyvenv.cfg`，并修正共用前端依赖的目录联接。移动整个文件夹后先执行启动脚本；Python 工具统一使用 `python -m pip`，旧环境中复制的 pip.exe 等入口不适合作为迁移后入口。

## GitHub 克隆后首次安装

支持 Windows x64、Python 3.12。前端与公式打印还需安装 Node.js（版本应满足前端锁文件所用 Vite 的要求；本机验证版本见迁移记录）。Git 仓库不包含数据库、原图和模型权重。

在根目录 PowerShell 执行：

```powershell
# 安装后端/OCR、基础模型、独立公式模型、前端和公式打印库
./scripts/setup.ps1 -Formula -Frontend -Renderer

# 使用指定 Python 3.12
# ./scripts/setup.ps1 -PythonCommand 'C:/Python312/python.exe' -Formula -Frontend -Renderer

./start-local.cmd
```

安装会联网下载依赖与基础模型。各版本分别读取自己的 `.env`。当前 -3 需按 `subjects-learning-3/.env.example` 填写 Supabase Project URL 与 publishable key 才会启用注册登录；切勿放入 secret/service_role key。普通本地 OCR 不需要 API 密钥。各版本的数据目录保持独立。

## 可选高级模型

在根目录执行以下命令，按需选择；已有模型无需重复准备。

```powershell
. ./scripts/runtime.ps1

# GLM-OCR：固定版本权重和 llama.cpp 程序
& $python ./subjects-learning-2/scripts/setup-document-ocr.py

# LaMa 局部修复
& $python ./subjects-learning-2/scripts/setup-diagram-repair.py

# 安装可选转换工具，然后准备 UVDoc 与 ExamInk
./scripts/setup.ps1 -InkTools -SkipModels
& $python ./subjects-learning-2/scripts/setup-document-rectification.py
& $python ./subjects-learning-2/scripts/setup-ink-erase.py --model segment
& (Join-Path $runtimeRoot 'ink-erase/Scripts/python.exe') ./subjects-learning-2/scripts/export-exam-ink-onnx.py
```

GLM-OCR 使用本机回环服务。新权重下载/转换仍须校验，结果供人工校对；原有实验模型的使用限制保留在各自清单中。

## 检查、开发与备份

```powershell
. ./scripts/runtime.ps1
& $python ./scripts/check-runtime.py --hashes --all-models

# 用生成样例验证 OCR、布局、公式打印及独立公式识别
& $python ./scripts/check-runtime.py --inference

# 仅安装基础模型时不加 --all-models
# & $python ./scripts/check-runtime.py --hashes

Push-Location subjects-learning-3
& $python -m pytest -q -p no:cacheprovider --basetemp=data/tmp/pytest-check
Pop-Location

./subjects-learning-3/scripts/build.ps1
& $python ./scripts/package-source.py
```

`check-runtime.py` 检查导入、模型路径、公式环境；`--hashes` 额外对照迁移时权重校验表。重新转换的模型若因工具版本产生不同字节，需要先验证转换结果，再有意识地更新校验表。

`package-source.py` 导出 Git 可见源码到 `发布包/源码/subjects-learning-source.zip`，拒绝数据库、运行目录和过大文件。完整个人数据备份仍使用各版 `scripts/package-project.py`；该备份含私人数据，应在本地保存。恢复时先还原完整源码仓库，再把版本数据快照解压到仓库对应目录，并恢复共享运行环境；单个版本快照不包含根目录的共享配置。源码包与数据备份用途不同。

# 依赖与模型目录

`dependencies/` 保存可提交到 GitHub 的依赖规格和模型来源。已安装的库、解释器和权重位于根目录 `runtimes/`，由 `.gitignore` 排除。

| 目录 | 内容 | 是否提交 |
| --- | --- | --- |
| `requirements/main.txt` | 后端、RapidOCR、RapidLayout、ONNX Runtime 与开发工具的实际安装版本及传递依赖 | 是 |
| `requirements/formula.txt` | RapidLaTeXOCR 独立环境，NumPy 1.26.4 | 是 |
| `requirements/ink-tools.txt` | PyTorch CPU、ExamInk 导出工具及依赖 | 是 |
| `requirements/model-tools.txt` | 可选 ONNX 转换工具 | 是 |
| `renderer/` | MathJax、KaTeX、resvg 的 npm 清单与锁文件 | 是 |
| `models/` | 模型来源、版本、用途、便携路径与 SHA-256 | 是 |
| `../runtimes/python/` | 本机 Python 3.12.10、标准库和基础库 | 否 |
| `../runtimes/local-ocr-packages/` | OCR 和后端附加库 | 否 |
| `../runtimes/formula/` | 独立公式环境 | 否 |
| `../runtimes/ink-erase/` | 笔迹模型导出环境 | 否 |
| `../runtimes/models/` | ONNX、GGUF、Safetensors 等实际权重 | 否 |
| `../runtimes/document-ocr/` | llama.cpp 本地程序与运行状态 | 否 |
| `../runtimes/document-renderer/` | 公式打印运行库 | 否 |
| `../runtimes/node_modules/` | 当前与历史版本共用的前端依赖 | 否 |
| `../runtimes/cache/`、`tmp/` | 可再生缓存、下载缓存与临时文件 | 否 |

模型清单使用 `runtime:/models/...`，由 `subjects-learning-3/backend/app/core/runtime.py` 展开。它与网络 URL 无关，只表示 `runtime.json` 配置目录内的文件。切换运行目录可设置绝对路径环境变量 `SUBJECTS_LEARNING_RUNTIME`。

`main.txt` 和 `formula.txt` 来自当前已安装依赖的闭包；`ink-tools.txt` 来自现有导出环境并补充 ONNX。新机器恢复步骤见 [安装说明](../docs/INSTALL.md)。模型的运行与转换环境独立，避免公式模型与主 OCR 使用不同 NumPy 版本产生冲突。

`models/handwriting-layout`、`models/ink-erase` 是保留的实验模型，不因此自动启用。应用运行使用 ExamInk 的 ONNX 导出，只有重新转换才需要完整 PyTorch 环境。

第三方声明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。运行库迁移原件逐文件核验记录位于被忽略的 `runtimes/migration-report.json`；模型长期校验表为 `models/checksums.json`。

# 第三方依赖与模型来源

本仓库仅提交依赖定义、来源和少量配置。第三方运行库、程序与权重保存在被 Git 忽略的 `runtimes/`；各自许可证仍然适用。以下信息来自迁移前已有模型清单，未改变原有授权或使用限制。

| 组件 | 项目中记录的来源 | 已有许可/说明 |
| --- | --- | --- |
| RapidOCR、RapidLayout | Python 安装包元数据与锁文件 | 以对应版本包内许可证为准 |
| RapidLaTeXOCR | `rapid-latex-ocr==0.0.9` | 以安装包及模型原许可为准 |
| GLM-OCR | zai-org/GLM-OCR、ggml-org/GLM-OCR-GGUF | 模型清单记录 MIT，固定 revision |
| llama.cpp | ggml-org/llama.cpp，b11429 Windows Vulkan 构建 | 保留发行包内许可 |
| UVDoc ONNX | PaddlePaddle/UVDoc_onnx | 原清单记录 Apache-2.0 |
| LaMa ONNX | Carve/LaMa-ONNX、advimman/lama | 原清单记录 Apache-2.0 |
| ExamInk-Seg、InkErase | ynyg/ExamInk-Seg、ynyg/InkErase | 元数据 Apache-2.0，config/README MIT；原清单要求保留来源、个人评估，未扩大用途 |
| handwriting-layout 实验模型 | onnx-community/rt-detrv2-heron-101-rukopys-ONNX | 原清单记录 Apache-2.0；中文试卷效果需另行验证 |
| MathJax、KaTeX、resvg | `dependencies/renderer/package-lock.json` | 以对应 npm 包内许可证为准 |
| Python 与其余 Python/npm 库 | 解释器 LICENSE.txt、包元数据与锁文件 | 原许可证保留在本机运行目录及上游发行物中 |

具体模型 URL、revision、SHA-256、用途标记见 `dependencies/models/`。实验模型没有因为目录整理而自动启用。本文件是来源索引，不替代第三方许可证全文，也不为项目自身代码选择许可证。

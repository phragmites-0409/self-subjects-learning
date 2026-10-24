---
license: apache-2.0
language:
- zh
- en
base_model:
- microsoft/resnet-50
pipeline_tag: image-to-image
datasets:
- ynyg/InkEraser
---
# ink-eraser-latest（手写墨迹擦除模型）

本目录是一个用于“手写墨迹擦除 / 文档去涂写”的模型导出包（Hugging Face 兼容格式）。模型输入为带墨迹的 RGB 图像，输出为去除墨迹后的 RGB 图像。

## 模型信息

- 架构：U-Net++（`segmentation-models-pytorch`）+ ResNet50 编码器
- 任务：图像到图像（去除手写笔迹/墨迹）
- 输入：RGB，形状 `[B, 3, H, W]`，数值范围 `[0, 1]`
- 输出：RGB，形状 `[B, 3, H, W]`，数值范围 `[0, 1]`（末端 `sigmoid`）

## 文件说明

- `config.json`：模型结构与训练超参数（导出时写入）
- `model.safetensors`：推理用权重（推荐）
- `best.ckpt`：原始 PyTorch Lightning checkpoint（用于继续训练/复现实验）
- `configuration.json`：简要元数据（framework/task）

## 快速推理（SafeTensors，推荐）

依赖：`torch`、`torchvision`、`segmentation-models-pytorch`、`safetensors`，以及 `Pillow`（读写图片可选）。

```bash
pip install torch torchvision segmentation-models-pytorch safetensors pillow
```

```python
import json
from pathlib import Path

import torch
import segmentation_models_pytorch as smp
from safetensors.torch import load_file
from PIL import Image
import torchvision.transforms.functional as TF

device = "cuda" if torch.cuda.is_available() else "cpu"

# 1) 读取配置
cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

# 2) 构建网络（与导出配置保持一致）
model = smp.UnetPlusPlus(
    encoder_name=cfg["encoder_name"],
    encoder_weights=None,  # 权重来自 model.safetensors
    in_channels=cfg["in_channels"],
    classes=cfg["classes"],
    decoder_attention_type=cfg.get("decoder_attention_type"),
    activation=cfg.get("activation"),  # 通常为 "sigmoid"
).to(device)

# 3) 加载权重
# 说明：导出时可能混入非网络权重（例如 `edge_loss.kx/ky`），推理只需要 Unet++ 本体参数，过滤掉即可。
state_dict = load_file("model.safetensors")
model_keys = set(model.state_dict().keys())
state_dict = {k: v for k, v in state_dict.items() if k in model_keys}
model.load_state_dict(state_dict, strict=True)
model.eval()

# 4) 准备输入（训练时仅做 0~1 归一化；如需更贴近训练分布可 resize 到 512x512）
img = Image.open("input.png").convert("RGB")
x = TF.to_tensor(img).unsqueeze(0).to(device)  # [1,3,H,W] in [0,1]

with torch.no_grad():
    y = model(x).clamp(0, 1)  # [1,3,H,W]

out = TF.to_pil_image(y.squeeze(0).cpu())
out.save("output.png")
```

提示：若输入尺寸不是 32 的倍数，部分编码器结构可能要求先 `pad/resize` 到合适尺寸（例如 `512x512`）。

也可以直接使用本项目提供的高清切块推理脚本（自动对大图切块并融合回原图），从项目根目录运行：

```bash
python infer_hd.py --model-dir assets/InkErase --input input.png --output output.png
```

## 使用 `best.ckpt`（继续训练/复现实验）

`best.ckpt` 是 PyTorch Lightning checkpoint，通常需要配合本项目的 `InkEraserModel` 代码使用，并提供 ResNet50 预训练权重文件（例如 `pretrained_weights/resnet50-0676ba61.pth`）。

```python
import torch
from model import InkEraserModel

model = InkEraserModel.load_from_checkpoint(
    "best.ckpt",
    weight="pretrained_weights/resnet50-0676ba61.pth",
)
model.eval()

with torch.no_grad():
    y = model(x)
```

## 训练超参数（来自 `config.json`）

以下参数主要用于训练/复现，推理不必关心：

```json
{
  "lr": 0.0001,
  "weight_decay": 0.01,
  "loss_w_charb": 0.78,
  "loss_w_ssim": 0.16,
  "loss_w_edge": 0.06,
  "use_mask_loss": true,
  "loss_mask_weight": 10.0,
  "charbonnier_eps": 0.001
}
```

## 许可证

MIT
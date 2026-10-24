---
license: apache-2.0
datasets:
- ynyg/ExamInk-Seg
language:
- zh
- en
base_model:
- microsoft/resnet-50
pipeline_tag: image-to-image
---
# ExamInk-Seg

基于 PyTorch Lightning 的墨迹二值分割模型。输入 RGB 图像，输出 1 通道墨迹掩码。

## 模型信息

- **架构**：U-Net++ (segmentation_models_pytorch) + ResNet50 编码器 (ImageNet 预训练)
- **任务**：手写/试卷墨迹二值分割
- **框架**：PyTorch Lightning
- **输入**：3 通道 RGB，按 ImageNet 均值/方差归一化
- **输出**：1 通道 logits 掩码；对 logits 取 sigmoid 得到概率

## 训练概要

- **Loss**：0.8 * Dice (from logits) + 0.2 * BCEWithLogits (pos_weight=2.0)
- **指标**：IoU 与 F1（阈值 0.3 和 0.5）
- **训练裁剪**：1024，随机裁剪 / 有墨迹优先裁剪，水平翻转
- **优化器**：AdamW (lr 3e-5, weight_decay 1e-5)
- **学习率调度**：ReduceLROnPlateau，监控 val_iou_05（mode=max, factor=0.5, patience=2, min_lr=1e-7）

## 文件

- `config.json`：模型结构与训练超参数
- `model.safetensors`：导出权重
- `best.ckpt`：PyTorch Lightning checkpoint

## 推理说明

- 归一化：mean=(0.485, 0.456, 0.406)，std=(0.229, 0.224, 0.225)
- 对 logits 取 `sigmoid` 得到二值掩码概率
- 验证/推理使用滑窗：tile=1024，stride=768，可选水平翻转 TTA

## 许可证

MIT
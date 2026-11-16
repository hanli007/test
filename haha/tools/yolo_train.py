"""
YOLO 训练与导出工具（可选模块，仅在模板匹配识别怪物效果不好时使用）。

完整流程：
    1. 采集截图：python tools/capture.py 账号名 --count 500 --interval 3 --out dataset/raw
    2. 标注：用 X-AnyLabeling / Label Studio 画框，导出 YOLO 格式，目录结构：
           dataset/
             images/train/*.png   images/val/*.png
             labels/train/*.txt   labels/val/*.txt
    3. 训练并导出：python tools/yolo_train.py --data tools/dataset.example.yaml --epochs 100
    4. 把导出的 monster.onnx 放到 resource/base/model/detect/，
       并把 farm.json 中 FarmLoop 的 monster_node 改为 "挂机_识别怪物_YOLO"

依赖：pip install ultralytics（会自动安装 PyTorch，较大；有 NVIDIA 显卡训练快很多）
MAA 官方说明支持 YOLOv8 / YOLO11 导出的 ONNX，因此默认使用 yolo11n；
更新的 YOLO26 输出格式不同（无 NMS 头），MAA 未声明支持，需要自行验证后再使用。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """命令行入口：训练 → 验证 → 导出 ONNX → 复制到资源目录。"""
    ap = argparse.ArgumentParser(description="训练 YOLO 怪物检测模型并导出 ONNX")
    ap.add_argument("--data", required=True, help="数据集 yaml，参考 tools/dataset.example.yaml")
    ap.add_argument("--model", default="yolo11n.pt", help="预训练权重，默认 yolo11n.pt（最小最快）")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640, help="训练分辨率")
    ap.add_argument("--device", default="", help="'0' 用第一块显卡，'cpu' 用 CPU，留空自动")
    ap.add_argument("--name", default="monster", help="导出的模型文件名（不含扩展名）")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("请先安装：pip install ultralytics") from None

    model = YOLO(args.model)
    model.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, device=args.device or None,
                project=str(ROOT / "runs"), name=args.name, exist_ok=True)
    metrics = model.val()
    print(f"验证集 mAP50-95 = {metrics.box.map:.3f}，mAP50 = {metrics.box.map50:.3f}")

    # 导出 ONNX（opset 12 兼容性最好），MAA 用 onnxruntime 推理
    onnx_path = Path(model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=True))
    dest = ROOT / "resource" / "base" / "model" / "detect" / f"{args.name}.onnx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(onnx_path, dest)
    print(f"已导出 → {dest}")


if __name__ == "__main__":
    main()

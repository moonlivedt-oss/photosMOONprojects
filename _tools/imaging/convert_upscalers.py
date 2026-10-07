"""Real-ESRGAN (SRVGGNetCompact) из .pth в .onnx. Нужен torch - только для этого шага, окно работает без него.
Запускает get_models.py; вручную: py -3.14 -m imaging.convert_upscalers из папки _tools."""

import os

# имя файла: (число свёрток, масштаб) - как в inference_realesrgan.py
NETS = {"realesr-animevideov3": (16, 4), "realesr-general-x4v3": (32, 4)}


def convert(pth, onnx_path, num_conv, scale):
    import torch
    from torch import nn
    from torch.nn import functional as F

    class SRVGGNetCompact(nn.Module):
        def __init__(self):
            super().__init__()
            self.scale = scale
            body = [nn.Conv2d(3, 64, 3, 1, 1), nn.PReLU(64)]
            for _ in range(num_conv):
                body += [nn.Conv2d(64, 64, 3, 1, 1), nn.PReLU(64)]
            body.append(nn.Conv2d(64, 3 * scale * scale, 3, 1, 1))
            self.body = nn.ModuleList(body)
            self.upsampler = nn.PixelShuffle(scale)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            return self.upsampler(out) + F.interpolate(x, scale_factor=self.scale, mode="nearest")

    state = torch.load(pth, map_location="cpu", weights_only=True)
    state = state.get("params_ema") or state.get("params") or state
    net = SRVGGNetCompact()
    net.load_state_dict(state, strict=True)
    net.eval()
    x = torch.rand(1, 3, 64, 64)
    torch.onnx.export(
        net,
        x,
        onnx_path,
        input_names=["image"],
        output_names=["upscaled"],
        dynamic_axes={"image": {2: "h", 3: "w"}, "upscaled": {2: "H", 3: "W"}},
        opset_version=17,
        dynamo=False,
    )


def main(folder):
    for name, (num_conv, scale) in NETS.items():
        pth, out = os.path.join(folder, name + ".pth"), os.path.join(folder, name + ".onnx")
        if os.path.exists(pth) and not os.path.exists(out):
            convert(pth, out, num_conv, scale)
            print("onnx:", out)


if __name__ == "__main__":
    main(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_models", "upscale"))

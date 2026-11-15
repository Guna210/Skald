"""Tensor verification check for the CUDA smoke pack."""

import json
import torch

assert torch.backends.cuda.is_built(), "CUDA support is missing in this PyTorch build"
device = "cuda:0" if torch.cuda.is_available() else "cpu"
x = torch.tensor([1.0, 2.0], device=device)
assert float(x.sum()) == 3.0
print(json.dumps({"adapter": "torch-cu12-smoke", "torch": torch.__version__, "device": device}))

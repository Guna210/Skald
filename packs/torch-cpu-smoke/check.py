"""One-line tensor verification check for the CPU smoke pack."""

import json
import torch

x = torch.tensor([1.0, 2.0])
assert float(x.sum()) == 3.0
print(json.dumps({"adapter": "torch-cpu-smoke", "torch": torch.__version__, "device": "cpu"}))

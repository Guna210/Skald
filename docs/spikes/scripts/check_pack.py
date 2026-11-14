"""Spike T03.4: import check run inside a pack (stands in for `skald_worker --check`). Prints one JSON line."""

import json
import sys
import time

t0 = time.perf_counter()
import numpy
import torch

import_s = round(time.perf_counter() - t0, 2)
try:
    import skald_spike_dummy

    dummy = skald_spike_dummy.VERSION
except ImportError:
    dummy = None

built = torch.backends.cuda.is_built()
print(
    json.dumps(
        {
            "python": sys.version.split()[0],
            "prefix": sys.prefix,
            "torch": torch.__version__,
            "numpy": numpy.__version__,
            "dummy_wheel": dummy,
            "import_s": import_s,
            "cuda_built": built,
            "cuda_version": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            # get_arch_list() returns [] without a GPU; the private call reads the compiled flags directly.
            "cuda_arch_list": torch._C._cuda_getArchFlags().split() if built else [],
            "cudnn": torch.backends.cudnn.version() if built else None,
        }
    )
)

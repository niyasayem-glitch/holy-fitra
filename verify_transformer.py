#!/usr/bin/env python3
from __future__ import annotations
import ctypes
import json
import math
import sys
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from hyperc_transformer import reference_identity_attention

lib = ctypes.CDLL(str(Path(sys.argv[1]).resolve()))
fn = lib.hyperc_attention_2x2
fn.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
fn.restype = None

x = np.asarray([1.0, 0.5, -0.5, 2.0], dtype=np.float32).reshape(1, 2, 2)
ref = reference_identity_attention(x).reshape(-1)
out = np.zeros(4, dtype=np.float32)
fn(x.reshape(-1).ctypes.data_as(ctypes.POINTER(ctypes.c_float)), out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
err = float(np.max(np.abs(ref - out)))
result = {"reference": ref.tolist(), "llvm": out.tolist(), "max_abs_error": err, "pass": bool(err < 1e-5)}
print(json.dumps(result, indent=2, sort_keys=True))
if not result["pass"]:
    raise SystemExit(1)

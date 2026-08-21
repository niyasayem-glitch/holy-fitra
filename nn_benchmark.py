#!/usr/bin/env python3
from __future__ import annotations
import ctypes
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from hyperc_nn import HyperTensorError, Tensor, TensorSpec, demo_model

model = demo_model()
x = Tensor.f32([1.5, -2.0])
target = Tensor.f32([1.0])
shape_rejected = False
try:
    model.forward(Tensor.f32([1.0, 2.0, 3.0]))
except HyperTensorError:
    shape_rejected = True

initial = float(np.mean((model.forward(x).data - target.data) ** 2))
losses = []
start_train = time.perf_counter()
for _ in range(1000):
    losses.append(model.train_step_mse(x, target, learning_rate=0.02))
train_ms = (time.perf_counter() - start_train) * 1000
final = float(np.mean((model.forward(x).data - target.data) ** 2))

start_cpu = time.perf_counter()
for _ in range(10000):
    model.forward(x)
cpu_ms = (time.perf_counter() - start_cpu) * 1000

lib_path = Path(sys.argv[1])
lib = ctypes.CDLL(str(lib_path.resolve()))
fn = lib.hyperc_model
fn.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
fn.restype = None
x_array = np.asarray([1.5, -2.0], dtype=np.float32)
out = np.zeros(1, dtype=np.float32)
start_native = time.perf_counter()
for _ in range(10000):
    fn(x_array.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
native_ms = (time.perf_counter() - start_native) * 1000

print(json.dumps({
    "shape_error_rejected": shape_rejected,
    "initial_mse": initial,
    "final_mse": final,
    "loss_decreased": final < initial,
    "training_steps": 1000,
    "training_elapsed_ms": train_ms,
    "cpu_10000_inferences_ms": cpu_ms,
    "llvm_native_10000_inferences_ms": native_ms,
    "native_output": out.tolist(),
}, indent=2, sort_keys=True))

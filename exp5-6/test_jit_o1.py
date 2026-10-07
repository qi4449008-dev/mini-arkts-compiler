# -*- coding: utf-8 -*-
"""实验六补充: 新 API jit_config jit_level=O1 对照实测"""
import time
import numpy as np
import mindspore as ms
from mindspore import ops, Tensor

ms.set_context(mode=ms.GRAPH_MODE,
               jit_config={"jit_level": "O1"})
x = Tensor(np.random.randn(256, 1024).astype(np.float32))
w = Tensor(np.random.randn(1024, 2048).astype(np.float32))
b = Tensor(np.random.randn(2048).astype(np.float32))
matmul, add, relu = ops.MatMul(), ops.Add(), ops.ReLU()


def forward(x, w, b):
    return relu(add(matmul(x, w), b))


out = forward(x, w, b)
print("jit O1 shape:", out.shape)
_ = forward(x, w, b)                     # 预热
t0 = time.perf_counter()
for _ in range(50):
    forward(x, w, b)
t1 = time.perf_counter()
print("jit O1: %.3f ms/iter" % ((t1 - t0) * 1000 / 50))
print("JIT-O1-DONE")

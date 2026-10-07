# -*- coding: utf-8 -*-
"""实验六: MindSpore 图模式 + 算子融合对照实测 (CPU 后端)
Y = ReLU(MatMul(X, W) + b), enable_graph_kernel 开关各计时对比。
"""
import time
import numpy as np
import mindspore as ms
from mindspore import ops, Tensor, context

print("MindSpore:", ms.__version__)
context.set_context(mode=context.GRAPH_MODE, device_target="CPU")
print("mode: GRAPH_MODE | target: CPU")

x = Tensor(np.random.randn(256, 1024).astype(np.float32))
w = Tensor(np.random.randn(1024, 2048).astype(np.float32))
b = Tensor(np.random.randn(2048).astype(np.float32))
matmul, add, relu = ops.MatMul(), ops.Add(), ops.ReLU()


def forward(x, w, b):
    y = matmul(x, w)          # [256,1024]x[1024,2048]
    y = add(y, b)             # + b
    y = relu(y)               # ReLU
    return y


out = forward(x, w, b)
print("Output shape:", out.shape, "(expect (256, 2048))")


def bench(n):
    t0 = time.perf_counter()
    for _ in range(n):
        forward(x, w, b)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000 / n


_ = forward(x, w, b)                        # 预热(触发图编译)

context.set_context(enable_graph_kernel=False)
t_off = min(bench(50) for _ in range(3))
context.set_context(enable_graph_kernel=True)
t_on = min(bench(50) for _ in range(3))

print(f"fusion OFF: {t_off:.3f} ms/iter")
print(f"fusion ON : {t_on:.3f} ms/iter")
print(f"speedup   : {t_off / t_on:.2f}x")
print("FUSION-TEST-DONE")

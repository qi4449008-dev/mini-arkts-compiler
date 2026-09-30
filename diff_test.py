#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差分测试: 独立参考解释器 vs 编译器生成代码 (对应实验四大纲要求)
用例: 30 个循环/算术程序(3 模板 x 10 参数)
参考: Python 直接模拟 Mini-ArkTS 语义
被测: 编译器生成的 Mock-C 代码
"""
import io
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "diff_out")
os.makedirs(OUT, exist_ok=True)

TEMPLATES = [
    "s = s + i * 2 - 1;",
    "s = s + i * i % 97;",
    "s = (s + i) * 2 % 100003;",
]
PARAMS = [50, 500, 5000, 50000, 500000, 300000, 1234, 999, 77, 4321]


def arkts_src(tpl, n):
    return (f"function compute(n: number): number {{\n"
            f"  let s: number = 0;\n"
            f"  let i: number = 0;\n"
            f"  while (i < n) {{ {tpl} i++; }}\n"
            f"  return s;\n"
            f"}}\n"
            f"let r: number = compute({n});\n"
            f"print(r);\n")


def reference(tpl, n):
    """独立参考解释器: Python 直接模拟 Mini-ArkTS 语义"""
    s = 0.0
    for i in range(n):
        if tpl == TEMPLATES[0]:
            s = s + i * 2 - 1
        elif tpl == TEMPLATES[1]:
            s = s + i * i % 97
        else:
            s = (s + i) * 2 % 100003
    return f"{s:g}"


def compiler_c(tpl, n, idx, use_opt):
    from parser import parse
    from semantic import check
    from ir_gen import generate_ir
    from codegen import generate_c
    if use_opt:
        from optimizer import optimize
    src = arkts_src(tpl, n)
    ast, le, pe = parse(src)
    assert not pe and not check(ast)
    funcs = generate_ir(ast)
    if use_opt:
        optimize(funcs)
    return generate_c(funcs)


def main():
    sys.path.insert(0, BASE)
    n_total, n_match = 0, 0
    results = []
    for ti, tpl in enumerate(TEMPLATES):
        for n in PARAMS:
            idx = n_total
            ref = reference(tpl, n)
            cb = compiler_c(tpl, n, idx, use_opt=False)
            ca = compiler_c(tpl, n, idx, use_opt=True)
            fb = os.path.join(OUT, f"d{idx}_b.c")
            fa = os.path.join(OUT, f"d{idx}_a.c")
            io.open(fb, "w", encoding="utf-8").write(cb)
            io.open(fa, "w", encoding="utf-8").write(ca)
            results.append((idx, ref, fb, fa))
            n_total += 1
    print("variants:", n_total)

    script = ["set -e",
              f"cd /mnt/c/Users/38329/.zcode/workspace/default/submit/"
              f"mini-arkts-compiler/diff_out"]
    for idx, _, fb, fa in results:
        b = os.path.basename(fb)
        a = os.path.basename(fa)
        script.append(f"gcc -O0 {b} -o d{idx}b -lm 2>/dev/null")
        script.append(f"gcc -O0 {a} -o d{idx}a -lm 2>/dev/null")
    script.append("match=0; total=0")
    for idx, ref, _, _ in results:
        script.append(
            f'b1=$(./d{idx}b | head -1); a1=$(./d{idx}a | head -1); '
            f'total=$((total+1)); '
            f'if [ "$b1" = "$a1" ] && [ "$b1" = "{ref}" ]; '
            f'then match=$((match+1)); '
            f'else echo "DIFF d{idx}: ref={ref} b=$b1 a=$a1"; fi')
    script.append('echo "DIFF-RESULT $match/$total"')

    shp = os.path.join(OUT, "run.sh")
    io.open(shp, "w", encoding="utf-8", newline="\n").write("\n".join(script))
    wsl_sh = ("/mnt/c/Users/38329/.zcode/workspace/default/submit/"
              "mini-arkts-compiler/diff_out/run.sh")
    r = subprocess.run(["wsl", "-d", "Ubuntu-2404", "-u", "root", "--",
                        "bash", wsl_sh],
                       capture_output=True, text=True, timeout=900)
    for ln in (r.stdout + r.stderr).splitlines():
        if "DIFF" in ln or "error" in ln.lower():
            print(ln)
    m = re.search(r"DIFF-RESULT (\d+)/(\d+)", r.stdout + r.stderr)
    if m:
        print(f"差分对拍(三方一致: 参考=优化前=优化后): "
              f"{m.group(1)}/{m.group(2)}")
        return 0 if m.group(1) == m.group(2) else 1
    print("差分脚本执行异常")
    return 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Mini-ArkTS 编译器前端模糊测试器 (实验四 · Fuzzing)
对 词法->语法->语义->IR 全前端做变异模糊测试:
1. 种子: 3 段合法 ArkTS 代码。
2. 变异算子: 随机字符插入/删除/替换/交换 + 关键词注入。
3. 分类: LEX_REJECT / PARSE_REJECT / SEM_REJECT (预期拒绝) /
         ACCEPTED (合法变异) / CRASH (意外异常 = 编译器 bug)。
4. 固定随机种子保证可复现; CRASH 按签名去重。
"""
from __future__ import annotations
import random
import string

from lexer import tokenize
from parser import parse
from semantic import check
from ir_gen import generate_ir

SEEDS = [
    "let a: number = 2 + 3 * 4;\nprint(a);",
    "function add(x: number, y: number): number { return x + y; }\n"
    "let r: number = add(1, 2);",
    "if (true) { let s: string = \"hi\"; } else { let n: number = 0; }",
    "@Component\nstruct A {\n  @State v: number = 0\n  build() { }\n}",
]

KEYWORDS = ["let", "const", "if", "else", "while", "function", "return",
            "struct", "@State", "@Component", "@CrossDevice", "number"]


def mutate(src: str, rng: random.Random) -> str:
    """对源码做一次随机变异"""
    if not src:
        return rng.choice(KEYWORDS)
    op = rng.randrange(5)
    i = rng.randrange(len(src))
    if op == 0:                                   # 插入随机字符
        return src[:i] + rng.choice(string.printable[:94]) + src[i:]
    if op == 1:                                   # 删除字符
        return src[:i] + src[i + 1:]
    if op == 2:                                   # 替换字符
        return src[:i] + rng.choice(string.printable[:94]) + src[i + 1:]
    if op == 3 and len(src) > 2:                  # 交换两字符
        j = rng.randrange(len(src))
        lst = list(src)
        lst[i], lst[j] = lst[j], lst[i]
        return "".join(lst)
    return src[:i] + rng.choice(KEYWORDS) + src[i:]   # 关键词注入


def run_frontend(src: str):
    """跑完整前端, 返回 (分类, 签名)"""
    try:
        toks, lex_errs = tokenize(src)
        if lex_errs:
            return "LEX_REJECT", f"lex:{lex_errs[0].msg}"
        ast, _, parse_errs = parse(src)
        if parse_errs:
            return "PARSE_REJECT", f"parse:{parse_errs[0].msg[:40]}"
        sem_errs = check(ast)
        if sem_errs:
            return "SEM_REJECT", f"sem:{sem_errs[0].msg[:40]}"
        generate_ir(ast)
        return "ACCEPTED", "ok"
    except Exception as e:                        # 编译器自身 bug
        return "CRASH", f"{type(e).__name__}:{str(e)[:60]}"


def fuzz(n: int = 300, seed: int = 42):
    rng = random.Random(seed)
    counts = {"LEX_REJECT": 0, "PARSE_REJECT": 0, "SEM_REJECT": 0,
              "ACCEPTED": 0, "CRASH": 0}
    crashes: dict[str, str] = {}                  # 签名去重 -> 样例
    for k in range(n):
        src = rng.choice(SEEDS)
        for _ in range(rng.randrange(1, 4)):      # 1~3 次叠加变异
            src = mutate(src, rng)
        kind, sig = run_frontend(src)
        counts[kind] += 1
        if kind == "CRASH" and sig not in crashes:
            crashes[sig] = src
    return counts, crashes


if __name__ == "__main__":
    N = 300
    counts, crashes = fuzz(N)
    total_reject = counts["LEX_REJECT"] + counts["PARSE_REJECT"] \
        + counts["SEM_REJECT"]
    print(f"变异用例总数: {N}")
    print(f"  词法拒绝 : {counts['LEX_REJECT']}")
    print(f"  语法拒绝 : {counts['PARSE_REJECT']}")
    print(f"  语义拒绝 : {counts['SEM_REJECT']}")
    print(f"  合法接受 : {counts['ACCEPTED']}")
    print(f"  崩溃 BUG : {counts['CRASH']}")
    print(f"健壮性: 预期拒绝率 {total_reject / N * 100:.1f}%  "
          f"(拒绝但未崩溃 = 编译器前端正确处理了非法输入)")
    if crashes:
        print(f"\n发现 {len(crashes)} 个去重后的崩溃签名:")
        for sig, src in crashes.items():
            print(f"  [{sig}]  样例: {src[:50]!r}")
    else:
        print("未发现崩溃: 编译器前端对全部变异输入均安全拒绝, 无异常退出。")

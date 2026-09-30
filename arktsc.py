#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mini-ArkTS 编译器命令行入口 —— 黑盒测试接口

用法:
    python arktsc.py <命令> <源文件>

命令:
    tokens   输出词法分析 Token 序列
    ast      输出抽象语法树(缩进格式)
    check    只做词法/语法/语义检查, 不生成代码
    ir       输出三地址码 IR
    emit-c   输出 Mock-C 代码(未优化)
    opt-c    输出 Mock-C 代码(经常量折叠 + 死代码消除)

退出码(黑盒测试约定):
    0  成功
    1  词法错误
    2  语法错误
    3  语义错误
    4  用法错误 / 文件不存在
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USAGE = __doc__


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(USAGE)
        return 4
    cmd, path = argv[1], argv[2]
    if not os.path.exists(path):
        sys.stderr.write(f"文件不存在: {path}\n")
        return 4

    with open(path, encoding="utf-8") as f:
        src = f.read()

    from lexer import tokenize
    from parser import parse
    from semantic import check

    # ---- 词法 ----
    toks, lex_errs = tokenize(src)
    if cmd == "tokens":
        for t in toks:
            if t.type != "EOF":
                print(f"{t.type}\t{t.value!r}\t{t.line}:{t.col}")
    if lex_errs:
        for e in lex_errs:
            print(e, file=sys.stderr)
        return 1
    if cmd == "tokens":
        return 0

    # ---- 语法 ----
    ast, _, parse_errs = parse(src)
    if parse_errs:
        for e in parse_errs:
            print(e, file=sys.stderr)
        return 2
    if cmd == "ast":
        from parser import ast_to_text
        print(ast_to_text(ast))
        return 0

    # ---- 语义 ----
    sem_errs = check(ast)
    if sem_errs:
        for e in sem_errs:
            print(e, file=sys.stderr)
        return 3
    if cmd == "check":
        print("OK: 词法/语法/语义检查通过")
        return 0

    # ---- IR / 代码生成 ----
    from ir_gen import generate_ir, render_ir
    from codegen import generate_c
    funcs = generate_ir(ast)
    if cmd == "ir":
        print(render_ir(funcs))
        return 0
    if cmd == "emit-c":
        print(generate_c(funcs))
        return 0
    if cmd == "opt-c":
        from optimizer import optimize
        optimize(funcs)
        print(generate_c(funcs))
        return 0

    sys.stderr.write(f"未知命令: {cmd}\n{USAGE}")
    return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))

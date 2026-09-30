# -*- coding: utf-8 -*-
"""Mini-ArkTS IR 优化器 (实验四 · AOT 优化)
两个经典 IR 级 Pass, 直接作用于 ir_gen 的三地址码:
1. 常量折叠 + 常量传播:
   - bin(t, c1 op c2) 编译期直接算出 -> copy(t, 结果)
   - 利用 ir_gen 的 SSA 版本化 (x.0/x.1 每版本只赋值一次), 常量可安全传播
   - phi 两输入同为同一字面量时折叠为 copy; 否则该版本标记为非常量
   - 除法/取模除数为 0 不折叠 (保留运行时行为)
2. 死代码消除 (DCE) + 不可达代码删除:
   - dst 根名字(root, 去掉 SSA 版本)从未被任何指令引用 -> 删除
     (保守: 任何版本被用即保护同名所有版本, 绝不改变语义)
   - goto/ret 之后到下一个 label 之前的指令不可达 -> 删除
迭代到不动点, 输出优化前后 IR 与量化统计。
"""
from __future__ import annotations

NUM_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">="}


def _is_num(s):
    if not isinstance(s, str):
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _calc(op, a, b):
    x, y = float(a), float(b)
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op in ("/", "%") and y == 0:
        return None                       # 除零不折叠
    if op == "/":
        return x / y
    if op == "%":
        return x % y if (x == int(x) and y == int(y)) else None
    if op == "==":
        return 1.0 if x == y else 0.0
    if op == "!=":
        return 1.0 if x != y else 0.0
    if op == "<":
        return 1.0 if x < y else 0.0
    if op == ">":
        return 1.0 if x > y else 0.0
    if op == "<=":
        return 1.0 if x <= y else 0.0
    if op == ">=":
        return 1.0 if x >= y else 0.0
    return None


def _roots(func):
    """收集所有被引用的操作数根名字"""
    used = set()
    for i in func.instrs:
        if i.op == "bin":
            used.add(i.a.split(".")[0]); used.add(i.b.split(".")[0])
        elif i.op == "unary":
            used.add(i.a.split(".")[0])
        elif i.op in ("copy", "phi"):
            if i.a:
                used.add(i.a.split(".")[0])
            if i.op == "phi" and i.b:
                used.add(i.b.split(".")[0])
        elif i.op == "if_goto":
            used.add(i.a.split(".")[0])
        elif i.op in ("print", "ret"):
            if i.a:
                used.add(i.a.split(".")[0])
        elif i.op == "call" and i.b:
            for arg in i.b.split(","):
                arg = arg.strip()
                if arg and not _is_num(arg) and not arg.startswith('"'):
                    used.add(arg.split(".")[0])
    return used


def loop_regions(func):
    """回边检测: goto 目标 label 位于其之前 -> [label, goto] 为循环体。
    循环体内的指令不做折叠/传播/删除 (伪 SSA 跨回边不安全)。"""
    label_at = {}
    for idx, i in enumerate(func.instrs):
        if i.op == "label":
            label_at.setdefault(i.a, idx)
    loops = set()
    for idx, i in enumerate(func.instrs):
        if i.op == "goto" and i.a in label_at and label_at[i.a] < idx:
            loops.update(range(label_at[i.a], idx + 1))
    return loops


def fold_consts(func, loop_idx=None):
    """常量折叠 + 传播, 返回折叠次数 (原地修改)。循环体内跳过。"""
    loop_idx = loop_idx or set()
    n = 0
    consts = {}                            # SSA 版本名 -> 字面量
    for idx, i in enumerate(func.instrs):
        if idx in loop_idx:                # 循环体内: 不折叠不传播
            consts.clear()
            continue
        # 传播: 操作数若是已知常量版本 -> 替换为字面量
        if i.op in ("bin", "unary", "copy", "phi", "if_goto", "print", "ret"):
            if i.a in consts:
                i.a = consts[i.a]
            if i.op in ("bin", "phi") and i.b in consts:
                i.b = consts[i.b]
        if i.op == "copy":
            if _is_num(i.a):
                consts[i.dst] = i.a
            elif i.a in consts:
                consts[i.dst] = consts[i.a]
                n += 1                     # copy 链传播也算一次折叠
            else:
                consts.pop(i.dst, None)
        elif i.op == "bin":
            if _is_num(i.a) and _is_num(i.b) and i.opd in NUM_OPS:
                r = _calc(i.opd, i.a, i.b)
                if r is not None:
                    i.op, i.opd, i.b = "copy", "", ""
                    i.a = _fmt(r)
                    consts[i.dst] = i.a
                    n += 1
                    continue
            consts.pop(i.dst, None)
        elif i.op == "unary":
            if _is_num(i.a) and i.opd == "-":
                i.op, i.opd = "copy", ""
                i.a = _fmt(-float(i.a))
                consts[i.dst] = i.a
                n += 1
            else:
                consts.pop(i.dst, None)
        elif i.op == "phi":
            if i.a == i.b and _is_num(i.a):
                i.op, i.b = "copy", ""     # 两分支同值, phi 退化
                consts[i.dst] = i.a
                n += 1
            else:
                consts.pop(i.dst, None)
        elif i.op == "call":
            consts.pop(i.dst, None) if i.dst else None
    return n


def dce(func, loop_idx=None):
    """死代码 + 不可达代码消除, 返回删除条数 (原地修改)"""
    removed = 0
    changed = True
    while changed:
        changed = False
        loop_idx = loop_regions(func)      # 索引随删除变化, 每轮重算
        used = _roots(func)
        keep = []
        unreachable = False
        for idx, i in enumerate(func.instrs):
            if i.op in ("goto", "ret"):
                keep.append(i)
                unreachable = True
                continue
            if i.op == "label":
                unreachable = False
                keep.append(i)
                continue
            if unreachable:
                removed += 1                # goto/ret 后的不可达指令
                changed = True
                continue
            # 纯计算且结果从未被用 -> 死代码 (循环体内保留)
            pure = i.op in ("copy", "bin", "unary")
            if pure and i.dst and idx not in loop_idx \
                    and i.dst.split(".")[0] not in used:
                removed += 1
                changed = True
                continue
            keep.append(i)
        func.instrs[:] = keep
    return removed


def optimize(funcs):
    """返回 (统计 dict); 原地优化所有函数"""
    st = {"before": 0, "after": 0, "folded": 0, "dce": 0}
    for f in funcs:
        st["before"] += len(f.instrs)
        loop = loop_regions(f)
        st["folded"] += fold_consts(f, loop)
        st["dce"] += dce(f)
        st["after"] += len(f.instrs)
    return st


def stats_text(st) -> str:
    rate = (1 - st["after"] / st["before"]) * 100 if st["before"] else 0
    return (f"优化前指令数: {st['before']}\n"
            f"常量折叠/传播次数: {st['folded']}\n"
            f"死代码/不可达删除条数: {st['dce']}\n"
            f"优化后指令数: {st['after']}\n"
            f"指令削减率: {rate:.1f}%")


if __name__ == "__main__":
    from parser import parse
    from ir_gen import generate_ir, render_ir

    demo = '''
    let a: number = 2 + 3 * 4;      // 折叠: 3*4=12, 2+12=14
    let b: number = a * 0;          // 折叠为 0, 且 b 未使用 -> 死代码
    let c: number = 10 + 20;        // 折叠为 30
    let unused: number = 99;        // 从未使用 -> 死代码
    if (1 < 2) { a = c; } else { a = 0; }   // 条件可折叠
    print(a);
    print(c);
    '''
    ast, le, pe = parse(demo)
    if pe:
        print("PARSE FAIL:", pe[0])
    else:
        funcs = generate_ir(ast)
        print("======== 优化前 IR ========")
        print(render_ir(funcs))
        st = optimize(funcs)
        print("======== 优化后 IR ========")
        print(render_ir(funcs))
        print("======== 统计 ========")
        print(stats_text(st))

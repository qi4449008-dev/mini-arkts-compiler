# -*- coding: utf-8 -*-
"""Mini-ArkTS Mock-C 代码生成 (实验三)
IR -> C 代码。约定:
- 数值统一用 double, 变量版本号 x.1 -> 纯名字 x (SSA 版本仅用于优化分析)
- print 内建 -> ark_print(double)  (模拟鸿蒙 ArkRuntime API)
- @CrossDevice 函数 -> 生成 RPC Stub(客户端打包) 与 Skeleton(服务端解包),
  模拟鸿蒙分布式软总线的跨设备调用。
"""
from __future__ import annotations
import re

HEADER = """/* Mini-ArkTS 生成的 Mock-C 代码 (Mini-ArkTS Compiler 自动生成) */
#include <stdio.h>
#include <string.h>
#include <math.h>

/* ---- 鸿蒙分布式软总线 mock ---- */
static double ark_bus_rtt_ms = 0.0;      /* 累计跨设备通信时延 */
static void ark_bus_send(const char *device, const char *func) {
    ark_bus_rtt_ms += 0.5;               /* 每次跨设备调用 +0.5ms */
    printf("[ARK_BUS] %s <- %s\\n", device, func);
}
static void ark_print(double v) { printf("%g\\n", v); }
"""


def plain(name: str) -> str:
    """t3 / a.2 -> t3 / a   (去掉 SSA 版本后缀)"""
    return name.split(".")[0]


def c_ident(name: str) -> str:
    """标识符净化: 非法字符 -> 下划线"""
    return re.sub(r"[^A-Za-z0-9_]", "_", plain(name))


class CGen:
    def __init__(self, funcs):
        self.funcs = funcs

    def operand(self, s: str) -> str:
        s = s.strip()
        if s == "undef" or s == "":
            return "0"
        if s == "true":
            return "1"
        if s == "false":
            return "0"
        if s == "null":
            return "0"
        # 字符串字面量 "xxx" -> 数值 0 (教学子集仅支持数值运算)
        if s.startswith('"'):
            return "0"
        # 含 '.' 的成员访问 a.b -> ark_get(a, "b") (模拟对象属性读取)
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$",
                     s)
        if m:
            return f'ark_get({c_ident(m.group(1))}, "{m.group(2)}")'
        return c_ident(s)

    def bin_line(self, d, a, opd, b):
        """二元运算行; % 在 C 里不支持 double, 用 fmod"""
        aa, bb = self.operand(a), self.operand(b)
        if opd == "%":
            return f"    {d} = fmod({aa}, {bb});"
        return f"    {d} = {aa} {opd} {bb};"

    def gen_function(self, f):
        name = c_ident(f.name)
        params = ", ".join(f"double {c_ident(p)}" for p in f.params)
        if params == "":
            params = "void"
        lines = [f"double ark_{name}({params}) {{"]
        emitted_labels = set()
        for i in f.instrs:
            if i.op == "label":
                emitted_labels.add(plain(i.a))
        declared = set()
        for ins in f.instrs:
            if ins.op == "label":
                lines.append(f"{plain(ins.a)}:")
                lines.append("    ;")   # label 后必须跟语句, 空语句占位
            elif ins.op == "copy":
                d = c_ident(ins.dst)
                if d not in declared:
                    lines.append(f"    double {d};")
                    declared.add(d)
                lines.append(f"    {d} = {self.operand(ins.a)};")
            elif ins.op == "bin":
                d = c_ident(ins.dst)
                if d not in declared:
                    lines.append(f"    double {d};")
                    declared.add(d)
                lines.append(self.bin_line(
                    d, ins.a, ins.opd, ins.b))
            elif ins.op == "unary":
                d = c_ident(ins.dst)
                if d not in declared:
                    lines.append(f"    double {d};")
                    declared.add(d)
                opd = "-" if ins.opd == "-" else "!"
                lines.append(f"    {d} = {opd}{self.operand(ins.a)};")
            elif ins.op == "if_goto":
                lines.append(f"    if ({self.operand(ins.a)}) "
                             f"goto {plain(ins.b)};")
            elif ins.op == "goto":
                lines.append(f"    goto {plain(ins.a)};")
            elif ins.op == "call":
                callee = plain(ins.a)
                if ins.dst:
                    d = c_ident(ins.dst)
                    if d not in declared:
                        lines.append(f"    double {d};")
                        declared.add(d)
                    lines.append(f"    {d} = ark_{c_ident(callee)}"
                                 f"({self.args(ins.b)});")
                else:
                    lines.append(f"    ark_{c_ident(callee)}"
                                 f"({self.args(ins.b)});")
            elif ins.op == "print":
                lines.append(f"    ark_print({self.operand(ins.a)});")
            elif ins.op == "phi":
                # SSA 汇合: C 中由控制流自然覆盖, 仅保留注释
                lines.append(f"    /* phi: {c_ident(ins.dst)} = "
                             f"merge({plain(ins.a)}, {plain(ins.b)}) */")
            elif ins.op == "ret":
                if ins.a:
                    lines.append(f"    return {self.operand(ins.a)};")
                else:
                    lines.append("    return 0;")
        # 确保 label 之后的空函数体也有 return
        if not f.instrs or f.instrs[-1].op != "ret":
            lines.append("    return 0;")
        lines.append("}")
        return "\n".join(lines)

    def args(self, s: str) -> str:
        s = s.strip()
        if not s:
            return ""
        parts = [a.strip() for a in s.split(",")]
        return ", ".join(self.operand(a) for a in parts)

    # ---------- @CrossDevice 函数的 RPC 桩 ----------
    def gen_rpc(self, f):
        """跨设备函数 -> Stub(打包发送) + Skeleton(解包执行), 模拟软总线"""
        name = c_ident(f.name)
        params = ", ".join(f"double {c_ident(p)}" for p in f.params)
        if params == "":
            params = "void"
        stub = [f"/* RPC Stub: 客户端打包参数, 经分布式软总线发送 */",
                f"double ark_{name}_stub({params}) {{"]
        args = ", ".join(c_ident(p) for p in f.params)
        if f.params:
            stub.append(f'    ark_bus_send("remote", "{name}");')
        stub.append(f"    return ark_{name}({args});")
        stub.append("}")
        skel = [f"/* RPC Skeleton: 服务端解包并调用本地实现 */",
                f"double ark_{name}_skeleton({params}) {{"]
        skel.append(f'    ark_bus_send("local", "{name}");')
        skel.append(f"    return ark_{name}({args});")
        skel.append("}")
        return "\n".join(stub) + "\n\n" + "\n".join(skel)

    def generate(self) -> str:
        out = [HEADER, ""]
        # 前置声明
        for f in self.funcs:
            if f.name != "__main__":
                params = ", ".join(f"double {c_ident(p)}" for p in f.params) \
                    or "void"
                out.append(f"double ark_{c_ident(f.name)}({params});")
        out.append("")
        for f in self.funcs:
            if f.name == "__main__":
                out.append("void ark_main(void) {")
                declared = set()
                for ins in f.instrs:
                    if ins.op == "label":
                        out.append(f"{plain(ins.a)}:")
                    elif ins.op == "copy":
                        d = c_ident(ins.dst)
                        if d not in declared:
                            out.append(f"    double {d};")
                            declared.add(d)
                        out.append(f"    {d} = {self.operand(ins.a)};")
                    elif ins.op == "bin":
                        d = c_ident(ins.dst)
                        if d not in declared:
                            out.append(f"    double {d};")
                            declared.add(d)
                        out.append(self.bin_line(
                            d, ins.a, ins.opd, ins.b))
                    elif ins.op == "unary":
                        d = c_ident(ins.dst)
                        if d not in declared:
                            out.append(f"    double {d};")
                            declared.add(d)
                        opd = "-" if ins.opd == "-" else "!"
                        out.append(f"    {d} = {opd}{self.operand(ins.a)};")
                    elif ins.op == "if_goto":
                        out.append(f"    if ({self.operand(ins.a)}) "
                                   f"goto {plain(ins.b)};")
                    elif ins.op == "goto":
                        out.append(f"    goto {plain(ins.a)};")
                    elif ins.op == "call":
                        callee = plain(ins.a)
                        if ins.dst:
                            d = c_ident(ins.dst)
                            if d not in declared:
                                out.append(f"    double {d};")
                                declared.add(d)
                            out.append(f"    {d} = ark_{c_ident(callee)}"
                                       f"({self.args(ins.b)});")
                        else:
                            out.append(f"    ark_{c_ident(callee)}"
                                       f"({self.args(ins.b)});")
                    elif ins.op == "print":
                        out.append(f"    ark_print({self.operand(ins.a)});")
                    elif ins.op == "phi":
                        out.append(f"    /* phi: {c_ident(ins.dst)} */")
                    elif ins.op == "ret":
                        pass
                out.append("}")
                out.append("")
            else:
                out.append(self.gen_function(f))
                out.append("")
                if f.cross_device:
                    out.append(self.gen_rpc(f))
                    out.append("")
        out.append("int main(void) {")
        out.append("    ark_main();")
        out.append('    printf("[bus rtt] %g ms\\n", ark_bus_rtt_ms);')
        out.append("    return 0;")
        out.append("}")
        return "\n".join(out)


def generate_c(funcs) -> str:
    return CGen(funcs).generate()


if __name__ == "__main__":
    from parser import parse
    from ir_gen import generate_ir, render_ir
    demo = '''
    function compute(n: number): number {
      let i: number = 0;
      let s: number = 0;
      while (i < n) { s = s + i; i++; }
      return s;
    }
    @CrossDevice
    function remoteAdd(a: number, b: number): number {
      return a + b;
    }
    let total: number = compute(10);
    print(total);
    '''
    ast, le, pe = parse(demo)
    if pe:
        print(pe[0])
    else:
        funcs = generate_ir(ast)
        print(generate_c(funcs))

# -*- coding: utf-8 -*-
"""Mini-ArkTS 中间表示(IR)生成 (实验三)
三地址码 + SSA 基础模拟(变量版本化 x.0/x.1, 分支汇合处生成 phi)
+ DeviceID 维度(@CrossDevice 函数标记为可跨设备执行)。
指令集: copy / bin / unary / if_goto / goto / label / call / ret / print / phi
"""
from __future__ import annotations


class Instr:
    def __init__(self, op, dst="", a="", b="", opd="", comment=""):
        self.op = op            # copy/bin/unary/if_goto/goto/label/call/ret/print/phi
        self.dst = dst
        self.a = a
        self.b = b
        self.opd = opd          # bin 的运算符 / unary 的一元符
        self.comment = comment

    def __str__(self):
        c = f"    ; {self.comment}" if self.comment else ""
        if self.op == "label":
            return f"{self.a}:{c}"
        if self.op == "goto":
            return f"goto {self.a}{c}"
        if self.op == "if_goto":
            return f"if {self.a} goto {self.b}{c}"
        if self.op == "copy":
            return f"{self.dst} = {self.a}{c}"
        if self.op == "bin":
            return f"{self.dst} = {self.a} {self.opd} {self.b}{c}"
        if self.op == "unary":
            return f"{self.dst} = {self.opd}{self.a}{c}"
        if self.op == "call":
            head = f"{self.dst} = " if self.dst else ""
            return f"{head}call {self.a}({self.b}){c}"
        if self.op == "ret":
            return f"ret {self.a}{c}" if self.a else f"ret{c}"
        if self.op == "print":
            return f"print {self.a}{c}"
        if self.op == "phi":
            return f"{self.dst} = phi({self.a}, {self.b}){c}"
        return f"{self.op} {self.dst}{c}"


class FuncIR:
    def __init__(self, name, params, ret_type, cross_device=False):
        self.name = name
        self.params = params
        self.ret_type = ret_type
        self.cross_device = cross_device   # DeviceID 维度: 可跨设备执行
        self.instrs = []

    def render(self):
        dev = "  @CrossDevice" if self.cross_device else ""
        lines = [f"function {self.name}({', '.join(self.params)}) -> "
                 f"{self.ret_type}{dev}"]
        for i in self.instrs:
            lines.append("  " + str(i))
        return "\n".join(lines)


class IRGen:
    def __init__(self, ast):
        self.ast = ast
        self.funcs: list[FuncIR] = []
        self.cur: FuncIR | None = None
        self.tmp_n = 0
        self.label_n = 0
        self.var_ver: dict = {}      # 变量版本计数 (SSA 模拟)

    # ---------- 工具 ----------
    def emit(self, op, dst="", a="", b="", opd="", comment="") -> Instr:
        ins = Instr(op, dst, a, b, opd, comment)
        self.cur.instrs.append(ins)
        return ins

    def new_tmp(self):
        self.tmp_n += 1
        return f"t{self.tmp_n}"

    def new_label(self, hint="L"):
        self.label_n += 1
        return f"{hint}{self.label_n}"

    def ver(self, name):
        """读取变量 -> 当前版本名 (SSA 模拟)"""
        v = self.var_ver.get(name, 0)
        return f"{name}.{v}"

    def bump(self, name):
        """变量重新赋值 -> 版本+1"""
        self.var_ver[name] = self.var_ver.get(name, 0) + 1
        return f"{name}.{self.var_ver[name]}"

    # ---------- 顶层 ----------
    def generate(self):
        top_stmts = []
        for node in self.ast["body"]:
            if node["kind"] == "FuncDecl":
                self.gen_function(node)
            elif node["kind"] == "ComponentDecl":
                self.gen_component(node)
            elif node["kind"] == "VarDecl":
                top_stmts.append(node)
            else:
                top_stmts.append(node)
        if top_stmts:
            self.gen_main(top_stmts)
        return self.funcs

    def gen_main(self, stmts):
        self.cur = FuncIR("__main__", [], "void")
        self.var_ver = {}
        for st in stmts:
            self.stmt(st)
        if not self.cur.instrs or self.cur.instrs[-1].op != "ret":
            self.emit("ret")
        self.funcs.append(self.cur)

    def gen_function(self, node):
        cross = "@CrossDevice" in node.get("decorators", [])
        self.cur = FuncIR(node["name"], [p["name"] for p in node["params"]],
                          node["returnType"] or "void",
                          cross_device=cross)
        self.var_ver = {}
        for p in node["params"]:
            self.var_ver[p["name"]] = 0
        for st in node["body"]:
            self.stmt(st)
        if not self.cur.instrs or self.cur.instrs[-1].op != "ret":
            self.emit("ret")
        self.funcs.append(self.cur)

    def gen_component(self, node):
        for m in node["members"]:
            if m["kind"] == "MethodDecl":
                cross = "@CrossDevice" in m.get("decorators", [])
                self.cur = FuncIR(f"{node['name']}.{m['name']}",
                                  [p["name"] for p in m["params"]],
                                  m["returnType"] or "void",
                                  cross_device=cross)
                self.var_ver = {}
                for p in m["params"]:
                    self.var_ver[p["name"]] = 0
                for st in m["body"]:
                    self.stmt(st)
                if not self.cur.instrs or self.cur.instrs[-1].op != "ret":
                    self.emit("ret")
                self.funcs.append(self.cur)
            # @State 变量与 build() 为声明式 UI, 不生成 IR

    # ---------- 语句 -> IR ----------
    def stmt(self, node):
        k = node["kind"]
        if k == "VarDecl":
            if node["init"]:
                v = self.expr(node["init"])
                self.var_ver[node["name"]] = 0
                self.emit("copy", self.ver(node["name"]), v,
                          comment=f"{node['name']} 初始化")
            else:
                self.var_ver[node["name"]] = 0
                self.emit("copy", self.ver(node["name"]), "undef")
        elif k == "ExprStmt":
            self.expr(node["expr"])
        elif k == "If":
            self.gen_if(node)
        elif k == "While":
            self.gen_while(node)
        elif k == "Return":
            v = self.expr(node["value"]) if node["value"] else ""
            self.emit("ret", a=v)
        elif k == "Block":
            for st in node["body"]:
                self.stmt(st)
        elif k == "UIElement":
            for a in node["args"]:
                self.expr(a)
            for c in node["chain"]:
                for a in c["args"]:
                    self.expr(a)
            for ch in node["children"]:
                self.stmt(ch)

    def gen_if(self, node):
        cond = self.expr(node["cond"])
        Ltrue = self.new_label("Ltrue")
        has_else = node["else"] is not None
        if has_else:
            Lfalse = self.new_label("Lfalse")
            Lend = self.new_label("Lend")
            self.emit("if_goto", "", cond, Ltrue)
            self.emit("goto", "", Lfalse)
            self.emit("label", "", Ltrue)
            ver_then = dict(self.var_ver)
            self.stmt(node["then"])
            ver_then = dict(self.var_ver)
            self.emit("goto", "", Lend)
            self.emit("label", "", Lfalse)
            self.var_ver = dict(ver_then)
            self.stmt(node["else"])
            ver_else = dict(self.var_ver)
            self.emit("label", "", Lend)
            # phi 合并两分支中版本不同的变量 (SSA 汇合点模拟)
            for name, v1 in ver_then.items():
                v2 = ver_else.get(name, v1)
                if v2 != v1:
                    self.var_ver[name] = max(v1, v2)
                    self.emit("phi", self.ver(name),
                              f"{name}.{v1}", f"{name}.{v2}",
                              comment=f"phi 合并 {name}")
        else:
            Lend = self.new_label("Lend")
            self.emit("if_goto", "", cond, Ltrue)
            self.emit("goto", "", Lend)
            self.emit("label", "", Ltrue)
            ver_then = dict(self.var_ver)
            self.stmt(node["then"])
            self.emit("label", "", Lend)
            self.var_ver = ver_then

    def gen_while(self, node):
        Lcond = self.new_label("Lcond")
        Lbody = self.new_label("Lbody")
        Lend = self.new_label("Lend")
        self.emit("label", "", Lcond)
        cond = self.expr(node["cond"])
        self.emit("if_goto", "", cond, Lbody)
        self.emit("goto", "", Lend)
        self.emit("label", "", Lbody)
        self.stmt(node["body"])
        self.emit("goto", "", Lcond)
        self.emit("label", "", Lend)

    # ---------- 表达式 -> IR ----------
    def expr(self, node):
        k = node["kind"]
        if k == "Literal":
            if node["litType"] == "string":
                return f'"{node["value"]}"'
            if node["litType"] == "boolean":
                return "1" if node["value"] else "0"
            if node["litType"] == "null":
                return "null"
            return str(node["value"])
        if k == "Ident":
            return self.ver(node["name"])
        if k == "This":
            return "this"
        if k == "Member":
            base = self.expr(node["object"])
            return f"{base}.{node['property']}"
        if k == "Assign":
            v = self.expr(node["value"])
            name = self.lhs_name(node["target"])
            self.emit("copy", self.bump(name), v)
            return self.ver(name)
        if k == "Binary":
            op = node["op"]
            if op == "===":
                op = "=="
            if op == "!==":
                op = "!="
            l = self.expr(node["left"])
            r = self.expr(node["right"])
            t = self.new_tmp()
            self.emit("bin", t, l, r, opd=op)
            return t
        if k == "Unary":
            v = self.expr(node["operand"])
            t = self.new_tmp()
            self.emit("unary", t, v, opd=node["op"])
            return t
        if k == "Update":
            name = self.lhs_name(node["target"])
            cur = self.ver(name)
            t = self.new_tmp()
            opd = "+" if node["op"] == "++" else "-"
            self.emit("bin", t, cur, "1", opd=opd,
                      comment=f"{name}{node['op']}")
            self.emit("copy", self.bump(name), t)
            return cur if node["prefix"] else t
        if k == "Call":
            args = [self.expr(a) for a in node["args"]]
            callee = node["callee"]
            name = callee["name"] if callee["kind"] == "Ident" else "?"
            if name in ("print", "log", "consoleLog"):
                for a in args:
                    self.emit("print", a=a)
                return ""
            t = self.new_tmp()
            self.emit("call", t, name, ", ".join(args))
            return t
        if k == "MethodCall":
            for a in node["args"]:
                self.expr(a)
            return ""
        if k == "Lambda":
            return "lambda"
        return "undef"

    def lhs_name(self, target):
        if target["kind"] == "Ident":
            return target["name"]
        if target["kind"] == "Member":
            return f"{self.lhs_name(target['object'])}_{target['property']}"
        return "tmp"


def generate_ir(ast):
    return IRGen(ast).generate()


def render_ir(funcs):
    return "\n\n".join(f.render() for f in funcs)


if __name__ == "__main__":
    from parser import parse
    demo = '''
    let a: number = 2 + 3 * 4;      // 可被常量折叠
    let b: number = a * 0;          // 可被死代码消除
    function compute(n: number): number {
      let i: number = 0;
      let s: number = 0;
      while (i < n) { s = s + i; i++; }
      return s;
    }
    if (1 < 2) { a = compute(a); } else { a = 0; }
    print(a);
    '''
    ast, le, pe = parse(demo)
    if pe:
        print(pe[0])
    else:
        funcs = generate_ir(ast)
        print(render_ir(funcs))

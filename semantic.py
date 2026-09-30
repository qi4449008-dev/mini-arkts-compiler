"""Mini-ArkTS 语义分析与类型系统 (实验二)
核心设计:
1. 符号表: "组件-状态-方法"三级作用域 (全局 -> 组件/函数 -> 块), 作用域链嵌套。
2. 类型系统: number/string/boolean/void 严格静态类型, 禁止隐式转换
   (体现方舟编译器"去动态化"思想)。
3. 装饰器语义校验: @State 必须定义在 @Component 组件中;
   @Entry 只能修饰组件且全局唯一; build() 内不能声明状态变量。
4. 语义检查: 使用前声明、赋值/运算/传参类型匹配、重复声明、调用未定义函数。
"""
from __future__ import annotations
from dataclasses import dataclass, field

# ArkTS 严格模式: 禁止 number<->string 隐式转换, 条件必须为 boolean
ARITH_TYPES = {"number"}
EQ_TYPES = {"number", "string", "boolean"}


@dataclass
class SemError(Exception):
    msg: str
    line: int = 0
    col: int = 0

    def __str__(self):
        loc = f"第{self.line}行 " if self.line else ""
        return f"[语义错误] {loc}{self.msg}"


@dataclass
class Symbol:
    name: str
    kind: str          # var / param / func / state / component
    type: str
    line: int = 0
    decorators: list = field(default_factory=list)


class Scope:
    """作用域链符号表"""
    def __init__(self, parent=None, name="global"):
        self.parent = parent
        self.name = name
        self.symbols: dict[str, Symbol] = {}
        self.children: list[Scope] = []

    def declare(self, sym: Symbol):
        if sym.name in self.symbols:
            raise SemError(f"标识符 '{sym.name}' 在当前作用域重复声明",
                           sym.line)
        self.symbols[sym.name] = sym

    def lookup(self, name):
        s = self
        while s:
            if name in s.symbols:
                return s.symbols[name]
            s = s.parent
        return None

    def child(self, name):
        c = Scope(self, name)
        self.children.append(c)
        return c


class TypeChecker:
    def __init__(self, ast):
        self.ast = ast
        self.errors: list[SemError] = []
        self.global_scope = Scope(None, "global")
        # 内建函数预声明 (print/log), 避免误报"未定义函数"
        for _fn in ("print", "log", "consoleLog"):
            self.global_scope.declare(Symbol(_fn, "func", "void"))
        self.cur_component = None       # 当前组件(含 decorators)
        self.in_build = False

    def error(self, msg, node=None):
        line = node.get("line", 0) if isinstance(node, dict) else 0
        self.errors.append(SemError(msg, line))

    # ---------------- 主入口 ----------------
    def check(self):
        for node in self.ast["body"]:
            try:
                self.decl(node)
            except SemError as e:
                self.errors.append(e)
        return self.errors

    def decl(self, node):
        k = node["kind"]
        if k == "VarDecl":
            self.check_var_decl(node, self.global_scope)
        elif k == "FuncDecl":
            self.check_func(node)
        elif k == "ComponentDecl":
            self.check_component(node)
        else:
            self.stmt(node, self.global_scope)

    # ---------------- 变量声明 + 类型推断 ----------------
    def check_var_decl(self, node, scope):
        decs = node.get("decorators", [])
        if decs:
            self.check_decorators_on_var(node, decs)
        declared = node["varType"]
        init_t = self.expr_type(node["init"], scope) if node["init"] else None
        if declared and declared not in ("number", "string", "boolean",
                                         "any", "void"):
            raise SemError(f"未知类型 '{declared}'",
                           {"line": 0})
        if declared and declared != "any" and init_t and init_t != "void" \
                and init_t != declared:
            raise SemError(
                f"类型不匹配: 不能将 {init_t} 赋值给 {declared} 类型的 "
                f"'{node['name']}' (ArkTS 严格模式禁止隐式转换)")
        if not declared and init_t:
            declared = init_t                # 类型推断: let x = 10 -> number
        if not declared:
            declared = "any"
        kind = "state" if "@State" in decs else "var"
        scope.declare(Symbol(node["name"], kind, declared,
                             decorators=decs))
        return declared

    def check_decorators_on_var(self, node, decs):
        for d in decs:
            if d == "@State":
                comp = self.cur_component
                if comp is None:
                    raise SemError(
                        "@State 变量必须定义在 @Component 组件内 "
                        f"('{node['name']}' 定义在组件外)")
                if "@Component" not in comp.get("decorators", []):
                    raise SemError(
                        f"@State 变量 '{node['name']}' 所在组件 "
                        f"'{comp['name']}' 缺少 @Component 装饰器")
                if self.in_build:
                    raise SemError(
                        f"@State 变量 '{node['name']}' 不能声明在 build() 内")
            elif d in ("@Entry", "@Component"):
                raise SemError(f"装饰器 {d} 不能修饰变量, 只能修饰组件")
            else:
                raise SemError(f"状态变量不支持装饰器 {d}")

    # ---------------- 函数 ----------------
    def check_func(self, node):
        scope = self.global_scope
        params = {p["name"]: p["type"] or "any" for p in node["params"]}
        try:
            scope.declare(Symbol(node["name"], "func",
                                 node["returnType"] or "void",
                                 ))
        except SemError as e:
            self.errors.append(e)
            return
        fscope = scope.child(f"func:{node['name']}")
        for p in node["params"]:
            fscope.declare(Symbol(p["name"], "param", p["type"] or "any"))
        saved = self.in_build
        self.in_build = False
        for st in node["body"]:
            try:
                self.stmt(st, fscope, ret_type=node["returnType"])
            except SemError as e:
                self.errors.append(e)
        self.in_build = saved

    # ---------------- 组件 ----------------
    def check_component(self, node):
        decs = node.get("decorators", [])
        comp_scope = self.global_scope.child(f"component:{node['name']}")
        saved_comp, saved_build = self.cur_component, self.in_build
        self.cur_component = node
        self.in_build = False
        try:
            self.global_scope.declare(
                Symbol(node["name"], "component", "any", decorators=decs))
            if not decs:
                self.errors.append(SemError(
                    f"组件 '{node['name']}' 缺少 @Component 装饰器"))
            for d in decs:
                if d not in ("@Entry", "@Component", "@Reusable", "@Observed"):
                    self.errors.append(SemError(
                        f"组件不支持的装饰器 {d}"))
        except SemError as e:
            self.errors.append(e)
        for m in node["members"]:
            k = m["kind"]
            try:
                if k == "VarDecl":
                    self.check_var_decl(m, comp_scope)
                elif k == "MethodDecl":
                    self.check_method(m, comp_scope)
                elif k == "BuildFunc":
                    self.in_build = True
                    bscope = comp_scope.child("build")
                    for st in m["body"]:
                        self.stmt(st, bscope)
                    self.in_build = False
            except SemError as e:
                self.errors.append(e)
        self.cur_component, self.in_build = saved_comp, saved_build

    def check_method(self, node, comp_scope):
        mscope = comp_scope.child(f"method:{node['name']}")
        for p in node["params"]:
            mscope.declare(Symbol(p["name"], "param", p["type"] or "any"))
        saved = self.in_build
        self.in_build = False
        for st in node["body"]:
            try:
                self.stmt(st, mscope, ret_type=node["returnType"])
            except SemError as e:
                self.errors.append(e)
        self.in_build = saved

    # ---------------- 语句 ----------------
    def stmt(self, node, scope, ret_type=None):
        k = node["kind"]
        if k == "VarDecl":
            self.check_var_decl(node, scope)
        elif k == "ExprStmt":
            self.expr_type(node["expr"], scope)
        elif k == "If":
            ct = self.expr_type(node["cond"], scope)
            if ct != "boolean" and ct != "any":
                raise SemError(
                    f"if 条件必须是 boolean, 不能是 {ct} "
                    "(ArkTS 禁止 number 当条件值)")
            self.stmt(node["then"], scope, ret_type)
            if node["else"]:
                self.stmt(node["else"], scope, ret_type)
        elif k == "While":
            ct = self.expr_type(node["cond"], scope)
            if ct != "boolean" and ct != "any":
                raise SemError(f"while 条件必须是 boolean, 不能是 {ct}")
            self.stmt(node["body"], scope, ret_type)
        elif k == "For":
            self.stmt(node["init"], scope, ret_type)
            if node["cond"]:
                self.expr_type(node["cond"], scope)
            if node["update"]:
                self.expr_type(node["update"], scope)
            self.stmt(node["body"], scope, ret_type)
        elif k == "Block":
            bscope = scope.child("block")
            for st in node["body"]:
                self.stmt(st, bscope, ret_type)
        elif k == "Return":
            vt = self.expr_type(node["value"], scope) if node["value"] else "void"
            if ret_type and ret_type != "any" and vt != "void" \
                    and ret_type != "void" and vt != ret_type:
                raise SemError(
                    f"return 类型不匹配: 函数声明返回 {ret_type}, 实际返回 {vt}")
        elif k == "Break" or k == "Continue":
            pass
        elif k == "UIElement":
            for a in node["args"]:
                self.expr_type(a, scope)
            for c in node["chain"]:
                for a in c["args"]:
                    self.expr_type(a, scope)
            for ch in node["children"]:
                self.stmt(ch, scope, ret_type)
        elif k == "FuncDecl":
            self.check_func(node)

    # ---------------- 表达式类型计算 ----------------
    def expr_type(self, node, scope):
        if node is None:
            return "void"
        k = node["kind"]
        if k == "Literal":
            return node["litType"]
        if k == "Ident":
            sym = scope.lookup(node["name"])
            if sym is None:
                raise SemError(f"标识符 '{node['name']}' 使用前未声明")
            return sym.type
        if k == "This":
            return "this"
        if k == "Member":
            ot = self.expr_type(node["object"], scope)
            # this.x -> 组件内 @State/@Prop 状态变量类型; 其余成员 any
            if ot == "this":
                sym = scope.lookup(node["property"])
                if sym is not None and sym.kind == "state":
                    return sym.type
            return "any"            # 其他成员属性类型不展开
        if k == "Assign":
            tt = self.expr_type(node["target"], scope)
            vt = self.expr_type(node["value"], scope)
            if tt in ("this",) or vt == "this":
                return tt
            if tt != "any" and vt != "any" and tt != vt:
                raise SemError(
                    f"赋值类型不匹配: 不能将 {vt} 赋值给 {tt} "
                    "(ArkTS 禁止 number<->string 隐式转换)")
            return tt
        if k == "Binary":
            op = node["op"]
            lt = self.expr_type(node["left"], scope)
            rt = self.expr_type(node["right"], scope)
            if op in ("+",):
                # number+number=number, string 拼接需要 string+string
                if lt == "string" and rt == "string":
                    return "string"
                if lt == "number" and rt == "number":
                    return "number"
                raise SemError(
                    f"运算符 '+' 两边类型不匹配: {lt} 与 {rt} "
                    "(禁止 string 与 number 隐式拼接, 请显式使用 toString())")
            if op in ("-", "*", "/", "%"):
                if lt == "number" and rt == "number":
                    return "number"
                raise SemError(
                    f"运算符 '{op}' 要求两边均为 number, 实际为 {lt} 与 {rt}")
            if op in ("==", "!=", "===", "!=="):
                if lt != rt and lt != "any" and rt != "any":
                    raise SemError(
                        f"比较运算两边类型不同: {lt} 与 {rt}")
                return "boolean"
            if op in ("<", ">", "<=", ">="):
                if lt != "number" or rt != "number":
                    raise SemError(f"关系运算要求 number: {lt} 与 {rt}")
                return "boolean"
            if op in ("&&", "||"):
                if lt != "boolean" or rt != "boolean":
                    raise SemError(f"逻辑运算要求 boolean: {lt} 与 {rt}")
                return "boolean"
        if k == "Unary":
            t = self.expr_type(node["operand"], scope)
            if node["op"] == "!":
                if t != "boolean":
                    raise SemError(f"'!' 要求 boolean, 实际 {t}")
                return "boolean"
            if node["op"] == "-":
                if t != "number":
                    raise SemError(f"一元 '-' 要求 number, 实际 {t}")
                return "number"
        if k == "Update":
            t = self.expr_type(node["target"], scope)
            if t != "number":
                raise SemError(f"'{node['op']}' 要求 number 变量, 实际 {t}")
            return "number"
        if k == "Call":
            callee = node["callee"]
            if callee["kind"] != "Ident":
                self.expr_type(callee, scope)
                return "any"
            sym = scope.lookup(callee["name"])
            if sym is None:
                raise SemError(f"调用了未定义的函数 '{callee['name']}'")
            if sym.kind != "func":
                raise SemError(f"'{callee['name']}' 不是函数, 不能调用")
            if callee["name"] in ("print", "log", "consoleLog"):
                for a in node["args"]:
                    self.expr_type(a, scope)
                return "void"
                for a in node["args"]:
                    self.expr_type(a, scope)
                return "void"
            if len(node["args"]) != len([p for p in self.func_params(callee["name"], scope)]):
                # 参数个数检查
                n_decl = len(self.func_params(callee["name"], scope))
                if len(node["args"]) != n_decl:
                    raise SemError(
                        f"函数 '{callee['name']}' 需要 {n_decl} 个参数, "
                        f"实际传入 {len(node['args'])} 个")
            for i, (a, p) in enumerate(zip(node["args"],
                                           self.func_params(callee["name"], scope))):
                at = self.expr_type(a, scope)
                if p != "any" and at != "any" and at != p:
                    raise SemError(
                        f"函数 '{callee['name']}' 第{i+1}个参数类型不匹配: "
                        f"需要 {p}, 实际 {at}")
            return sym.type
        if k == "MethodCall":
            for a in node["args"]:
                self.expr_type(a, scope)
            return "any"
        if k == "Lambda":
            return "function"
        if k == "New":
            return "any"
        return "any"

    def func_params(self, name, scope):
        """从 AST 提取函数参数类型(供调用检查)"""
        for n in self.ast["body"]:
            if n.get("kind") == "FuncDecl" and n["name"] == name:
                return [p["type"] or "any" for p in n["params"]]
        # 组件方法
        for n in self.ast["body"]:
            if n.get("kind") == "ComponentDecl":
                for m in n["members"]:
                    if m.get("kind") == "MethodDecl" and m["name"] == name:
                        return [p["type"] or "any" for p in m["params"]]
        return []


def check(ast):
    """返回错误列表"""
    return TypeChecker(ast).check()


if __name__ == "__main__":
    from parser import parse
    bad = '''
    let a: number = 10;
    let s: string = 42;           // 错误: number -> string
    let b = a + "hello";          // 错误: 隐式拼接
    if (a) { }                    // 错误: number 当条件
    undefined_fn(1, 2);           // 错误: 未定义函数
    @State let x: number = 0;     // 错误: @State 在组件外
    '''
    ast, le, pe = parse(bad)
    if pe:
        print(pe[0])
    else:
        for e in check(ast):
            print(e)

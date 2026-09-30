"""Mini-ArkTS 语法分析器 (实验一)
递归下降分析法: Token 序列 -> 抽象语法树(AST), 支持导出 JSON。
文法(Ellim-EBNF, 已消除左递归):
  program     := (componentDecl | funcDecl | varDecl)* EOF
  componentDecl := decorator* 'struct' IDENT '{' member* '}'
  member      := stateVar | methodDecl | buildFunc
  stateVar    := decorator ('let'|'const') IDENT (':' type)? ('=' expr)? ';'? 
  methodDecl  := IDENT '(' params? ')' (':' type)? block
  buildFunc   := 'build' '(' ')' uiBlock
  funcDecl    := 'function' IDENT '(' params? ')' (':' type)? block
  varDecl     := ('let'|'const') IDENT (':' type)? ('=' expr)? ';'
  stmt        := varDecl | ifStmt | whileStmt | forStmt | returnStmt
               | block | exprStmt
  ifStmt      := 'if' '(' expr ')' stmt ('else' stmt)?
  whileStmt   := 'while' '(' expr ')' stmt
  forStmt     := 'for' '(' varDeclNoSemi expr ';' expr? ')' stmt
  expr        := logicOr ( ('=' ) logicOr )?          // 赋值右结合
  logicOr     := logicAnd ( '||' logicAnd )*
  logicAnd    := equality ( '&&' equality )*
  equality    := comparison ( ('=='|'!='|'==='|'!==') comparison )*
  comparison  := additive ( ('<'|'>'|'<='|'>=') additive )*
  additive    := multiplicative ( ('+'|'-') multiplicative )*
  multiplicative := unary ( ('*'|'/'|'%') unary )*
  unary       := ('!'|'-') unary | postfix
  postfix     := primary ( '(' args? ')' | '.' IDENT ( '(' args? ')' )? )*
  primary     := INT | FLOAT | STRING | 'true' | 'false' | 'null' | IDENT
               | 'this' '.' IDENT | '(' expr ')' | lambda
"""
from __future__ import annotations
import json
from lexer import tokenize, Token, LexError


class ParseError(Exception):
    def __init__(self, msg, tok: Token):
        super().__init__(f"[语法错误] 第{tok.line}行 第{tok.col}列: {msg}")
        self.msg = msg
        self.line, self.col = tok.line, tok.col


TYPES = {"number", "string", "boolean", "void", "any"}
UI_TAGS = {"Column", "Row", "Text", "Button", "Image", "Stack", "Flex",
           "List", "ForEach", "Grid", "TextInput", "Toggle", "Scroll"}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0

    # ---------- 基础 ----------
    def peek(self, k=0) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def next(self) -> Token:
        t = self.toks[self.i]
        if t.type != "EOF":
            self.i += 1
        return t

    def at(self, type_, value=None):
        t = self.peek()
        return t.type == type_ and (value is None or t.value == value)

    def at_sep(self, v):   return self.at("SEP", v)
    def at_op(self, v):    return self.at("OP", v)
    def at_kw(self, v):    return self.at("KEYWORD", v)

    def expect(self, type_, value=None, what="") -> Token:
        if not self.at(type_, value):
            t = self.peek()
            want = what or (value or type_)
            raise ParseError(f"期望 '{want}'，实际为 '{t.value}'", t)
        return self.next()

    def expect_sep(self, v): return self.expect("SEP", v)
    def expect_op(self, v):  return self.expect("OP", v)

    def match_kw(self, v):
        if self.at_kw(v):
            return self.next()
        return None

    def eat_optional_semi(self):
        if self.at_sep(";"):
            self.next()

    # ---------- 顶层 ----------
    def parse_program(self):
        decls = []
        while not self.at("EOF"):
            decls.append(self.top_level())
        return {"kind": "Program", "body": decls}

    def top_level(self):
        decs = self.decorators()
        if decs:
            if self.at_kw("function"):
                return self.func_decl(decs)
            if self.at_kw("let") or self.at_kw("const"):
                return self.var_decl(decs, in_class=True)
            return self.component_decl(decs)
        if self.at_kw("struct"):
            return self.component_decl(decs)
        if self.at_kw("function"):
            return self.func_decl()
        if self.at_kw("class"):
            return self.component_decl(decs, kw="class")
        if self.at_kw("let") or self.at_kw("const"):
            return self.var_decl()
        return self.stmt()          # 顶层也允许普通语句(脚本模式)

    def decorators(self):
        decs = []
        while self.at("DECORATOR"):
            decs.append(self.next().value)
        return decs

    def component_decl(self, decs, kw="struct"):
        self.expect("KEYWORD", kw, kw)
        name = self.expect("IDENT", what="组件名").value
        self.expect_sep("{")
        members = []
        while not self.at_sep("}"):
            if self.at("EOF"):
                raise ParseError("组件声明缺少 '}'", self.peek())
            members.append(self.member())
        self.expect_sep("}")
        self.eat_optional_semi()
        return {"kind": "ComponentDecl", "decorators": decs, "name": name,
                "members": members}

    def member(self):
        decs = self.decorators()
        # build() 声明式 UI 入口 (build 不是关键字, 按 IDENT + '(' 识别)
        if self.at("IDENT") and self.peek().value == "build" \
                and self.peek(1).type == "SEP" and self.peek(1).value == "(":
            t = self.next()
            if decs:
                raise ParseError("build() 不能加装饰器", t)
            self.expect_sep("(")
            self.expect_sep(")")
            return {"kind": "BuildFunc", "body": self.ui_block()}
        if self.at_kw("let") or self.at_kw("const"):
            return self.var_decl(decs, in_class=True)
        # ArkTS 状态变量标准写法: @State v: number = 0 (不带 let/const)
        if decs and self.at("IDENT") and self.peek(1).type == "OP" \
                and self.peek(1).value in (":", "="):
            return self.state_var(decs)
        if self.at("IDENT"):
            return self.method_decl(decs)
        raise ParseError(f"组件成员不合法", self.peek())

    def state_var(self, decs):
        """@State/@Link 等修饰的状态变量(ArkTS 标准写法, 不带 let/const)"""
        name = self.expect("IDENT", what="状态变量名").value
        vtype = None
        if self.at_op(":"):
            self.next()
            vtype = self.expect("IDENT", what="类型").value
        init = None
        if self.at_op("="):
            self.next()
            init = self.expr()
        self.eat_optional_semi()
        return {"kind": "VarDecl", "declType": "let", "name": name,
                "varType": vtype, "init": init, "decorators": decs}

    def lambda_body(self, depth):
        """lambda 体: 表达式 或 块语句 { ... }"""
        if self.at_sep("{"):
            return self.block()
        return self.expr(depth + 1)

    def method_decl(self, decs):
        name = self.next().value
        self.expect_sep("(")
        params = self.params()
        self.expect_sep(")")
        ret = None
        if self.at_op(":"):
            self.next()
            ret = self.next().value
        body = self.block()
        return {"kind": "MethodDecl", "decorators": decs, "name": name,
                "params": params, "returnType": ret, "body": body["body"]}

    def params(self):
        ps = []
        while not self.at_sep(")"):
            pname = self.expect("IDENT", what="参数名").value
            ptype = None
            if self.at_op(":"):
                self.next()
                ptype = self.next().value
            ps.append({"name": pname, "type": ptype})
            if self.at_sep(","):
                self.next()
        return ps

    # ---------- 声明 ----------
    def var_decl(self, decs=None, in_class=False):
        kw = self.next().value          # let / const
        name = self.expect("IDENT", what="变量名").value
        vtype = None
        if self.at_op(":"):
            self.next()
            vtype = self.expect("IDENT", what="类型").value
        init = None
        if self.at_op("="):
            self.next()
            init = self.expr()
        if not in_class:
            self.expect_sep(";")
        else:
            self.eat_optional_semi()
        node = {"kind": "VarDecl", "declType": kw, "name": name,
                "varType": vtype, "init": init}
        if decs:
            node["decorators"] = decs
        return node

    def func_decl(self, decs=None):
        self.expect("KEYWORD", "function")
        name = self.expect("IDENT", what="函数名").value
        self.expect_sep("(")
        params = self.params()
        self.expect_sep(")")
        ret = None
        if self.at_op(":"):
            self.next()
            ret = self.next().value
        body = self.block()
        return {"kind": "FuncDecl", "decorators": decs or [], "name": name, "params": params,
                "returnType": ret, "body": body["body"]}

    # ---------- 语句 ----------
    def block(self):
        self.expect_sep("{")
        body = []
        while not self.at_sep("}"):
            if self.at("EOF"):
                raise ParseError("缺少 '}'（括号不匹配）", self.peek())
            body.append(self.stmt())
        self.expect_sep("}")
        return {"kind": "Block", "body": body}

    def ui_block(self):
        self.expect_sep("{")
        body = []
        while not self.at_sep("}"):
            if self.at("EOF"):
                raise ParseError("build() 缺少 '}'", self.peek())
            body.append(self.ui_stmt())
        self.expect_sep("}")
        return body

    def ui_stmt(self):
        """UI 组件标签语句: Text("hi").fontSize(30) / Column() { ... }"""
        tag = self.expect("IDENT", what="UI组件名").value
        self.expect_sep("(")
        args = self.call_args()
        self.expect_sep(")")
        chain = self.member_chain()
        children = []
        if self.at_sep("{"):
            children = self.ui_block()
        self.eat_optional_semi()
        return {"kind": "UIElement", "tag": tag, "args": args,
                "chain": chain, "children": children}

    def call_args(self):
        """'(' 已消费; 解析实参。特例: () => expr / () => {block} 空参 lambda"""
        if self.at_sep(")") and self.peek(1).type == "OP" \
                and self.peek(1).value == "=>":
            self.next()                      # )
            self.next()                      # =>
            body = self.lambda_body(0)
            return [{"kind": "Lambda", "params": [], "body": body}]
        return self.arguments()

    def arguments(self):
        args = []
        while not self.at_sep(")"):
            if self.at("IDENT") and self.peek(1).type == "OP" and self.peek(1).value == ":":
                pass  # 具名参数按普通表达式处理
            args.append(self.expr())
            if self.at_sep(","):
                self.next()
            elif not self.at_sep(")"):
                raise ParseError("参数列表缺少 ',' 或 ')'", self.peek())
        return args

    def member_chain(self):
        """链式调用: .fontSize(30).onClick(()=>{...})"""
        calls = []
        while self.at_sep("."):
            self.next()
            name = self.expect("IDENT", what="方法名").value
            args = []
            if self.at_sep("("):
                self.next()
                args = self.call_args()
                self.expect_sep(")")
            calls.append({"name": name, "args": args})
        return calls

    def stmt(self):
        if self.at_kw("let") or self.at_kw("const"):
            return self.var_decl()
        if self.at_kw("if"):
            return self.if_stmt()
        if self.at_kw("while"):
            return self.while_stmt()
        if self.at_kw("for"):
            return self.for_stmt()
        if self.at_kw("return"):
            self.next()
            value = None if self.at_sep(";") or self.at_sep("}") else self.expr()
            self.eat_optional_semi()
            return {"kind": "Return", "value": value}
        if self.at_kw("break"):
            self.next(); self.eat_optional_semi()
            return {"kind": "Break"}
        if self.at_kw("continue"):
            self.next(); self.eat_optional_semi()
            return {"kind": "Continue"}
        if self.at_sep("{"):
            return self.block()
        # 表达式语句 / 赋值 (ArkTS 遵循 ASI, 分号可省略)
        e = self.expr()
        self.eat_optional_semi()
        return {"kind": "ExprStmt", "expr": e}

    def if_stmt(self):
        self.expect("KEYWORD", "if")
        self.expect_sep("(")
        cond = self.expr()
        self.expect_sep(")")
        then = self.stmt()
        els = None
        if self.match_kw("else"):
            els = self.stmt()
        return {"kind": "If", "cond": cond, "then": then, "else": els}

    def while_stmt(self):
        self.expect("KEYWORD", "while")
        self.expect_sep("(")
        cond = self.expr()
        self.expect_sep(")")
        body = self.stmt()
        return {"kind": "While", "cond": cond, "body": body}

    def for_stmt(self):
        self.expect("KEYWORD", "for")
        self.expect_sep("(")
        init = self.var_decl(in_class=True)   # 不带分号版本
        cond = self.expr()
        self.expect_sep(";")
        update = None if self.at_sep(")") else self.expr()
        self.expect_sep(")")
        body = self.stmt()
        return {"kind": "For", "init": init, "cond": cond,
                "update": update, "body": body}

    # ---------- 表达式 (优先级爬升) ----------
    def expr(self, depth=0):
        if depth > 200:
            raise ParseError("表达式嵌套过深", self.peek())
        if self.at("IDENT") and self.peek(1).type == "OP" and self.peek(1).value == "=>":
            name = self.next().value
            self.next()                      # =>
            body = self.lambda_body(depth)
            return {"kind": "Lambda", "params": [name], "body": body}
        if self.at_sep("("):
            save = self.i
            self.next()
            if self.at_sep(")"):             # ()=>expr 或 ()=>{...}
                self.next()
                if self.at_op("=>"):
                    self.next()
                    return {"kind": "Lambda", "params": [],
                            "body": self.lambda_body(depth)}
                raise ParseError("空参数 lambda 缺少 '=>'", self.peek())
            if self.at("IDENT") and self.peek(1).type == "OP" and self.peek(1).value == "=>":
                name = self.next().value
                self.next()
                return {"kind": "Lambda", "params": [name],
                        "body": self.lambda_body(depth)}
            self.i = save                    # 回溯, 按普通括号表达式解析
        left = self.logic_or()
        if self.at_op("="):                  # 赋值, 右结合
            self.next()
            right = self.expr(depth + 1)
            return {"kind": "Assign", "target": left, "value": right}
        return left

    def _binary(self, sub, ops):
        node = sub()
        while self.peek().type == "OP" and self.peek().value in ops:
            op = self.next().value
            node = {"kind": "Binary", "op": op, "left": node, "right": sub()}
        return node

    def logic_or(self):   return self._binary(self.logic_and, {"||"})
    def logic_and(self):  return self._binary(self.equality, {"&&"})
    def equality(self):   return self._binary(self.comparison, {"==", "!=", "===", "!=="})
    def comparison(self): return self._binary(self.additive, {"<", ">", "<=", ">="})
    def additive(self):   return self._binary(self.multiplicative, {"+", "-"})
    def multiplicative(self): return self._binary(self.unary, {"*", "/", "%"})

    def unary(self):
        if self.at_op("!") or self.at_op("-"):
            op = self.next().value
            return {"kind": "Unary", "op": op, "operand": self.unary()}
        if self.at_op("++") or self.at_op("--"):
            op = self.next().value
            return {"kind": "Update", "op": op, "target": self.unary(), "prefix": True}
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while True:
            if self.at_sep("."):
                self.next()
                name = self.expect("IDENT", what="属性/方法名").value
                if self.at_sep("("):
                    self.next()
                    node = {"kind": "MethodCall", "object": node,
                            "method": name, "args": self.call_args()}
                    self.expect_sep(")")
                else:
                    node = {"kind": "Member", "object": node, "property": name}
            elif self.at_sep("("):
                self.next()
                node = {"kind": "Call", "callee": node, "args": self.call_args()}
                self.expect_sep(")")
            elif self.at_op("++") or self.at_op("--"):
                op = self.next().value
                node = {"kind": "Update", "op": op, "target": node, "prefix": False}
            else:
                return node

    def primary(self):
        t = self.peek()
        if t.type in ("INT", "FLOAT"):
            self.next()
            return {"kind": "Literal", "litType": "number", "value": t.value}
        if t.type == "STRING":
            self.next()
            return {"kind": "Literal", "litType": "string", "value": t.value}
        if self.at_kw("true") or self.at_kw("false"):
            self.next()
            return {"kind": "Literal", "litType": "boolean",
                    "value": t.value == "true"}
        if self.at_kw("null"):
            self.next()
            return {"kind": "Literal", "litType": "null", "value": None}
        if self.at_kw("this"):
            self.next()
            self.expect_sep(".")
            prop = self.expect("IDENT", what="属性名").value
            return {"kind": "Member",
                    "object": {"kind": "This"}, "property": prop}
        if self.at_kw("new"):
            self.next()
            callee = self.expect("IDENT", what="类名").value
            self.expect_sep("(")
            args = self.call_args()
            self.expect_sep(")")
            return {"kind": "New", "callee": callee, "args": args}
        if t.type == "IDENT":
            self.next()
            return {"kind": "Ident", "name": t.value}
        if self.at_sep("("):
            self.next()
            e = self.expr()
            self.expect_sep(")")
            return e
        raise ParseError(f"意外的记号 '{t.value}'", t)


def parse(src: str):
    """返回 (ast, lex_errors, parse_errors)"""
    toks, lex_errs = tokenize(src)
    p = Parser(toks)
    try:
        ast = p.parse_program()
        return ast, lex_errs, []
    except ParseError as e:
        return None, lex_errs, [e]


# ---------- AST -> JSON 导出 ----------
def ast_to_json(ast, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ast, f, ensure_ascii=False, indent=2)


# ---------- AST 缩进打印 ----------
def ast_to_text(node, indent=0):
    pad = "  " * indent
    if isinstance(node, dict):
        kind = node.get("kind", "?")
        extra = []
        for k, v in node.items():
            if k in ("kind",):
                continue
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                continue
            extra.append(f"{k}={v!r}")
        lines = [pad + kind + ("  " + " ".join(extra) if extra else "")]
        for k, v in node.items():
            if isinstance(v, dict):
                lines.append(pad + "." + k + ":")
                lines.append(ast_to_text(v, indent + 1))
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                lines.append(pad + "." + k + ": [")
                for item in v:
                    lines.append(ast_to_text(item, indent + 2))
                lines.append(pad + "]")
        return "\n".join(lines)
    if isinstance(node, list):
        return "\n".join(ast_to_text(n, indent) for n in node)
    return pad + repr(node)


if __name__ == "__main__":
    demo = '''
    let a: number = 10;
    const s: string = "hello";
    function add(x: number, y: number): number {
      return x + y;
    }
    if (a > 5 && s == "hello") { a = add(a, 3); } else { a = 0; }
    while (a < 100) { a++; }
    '''
    ast, le, pe = parse(demo)
    if pe:
        print(pe[0])
    else:
        print(ast_to_text(ast))

"""Mini-ArkTS 词法分析器 (实验一)
将 ArkTS 源代码字符串转换为 Token 序列。
支持: 关键字、装饰器、标识符、数字/字符串字面量、注释、运算符、分隔符、词法错误处理。
"""
from __future__ import annotations
from dataclasses import dataclass, field

KEYWORDS = {
    "let", "const", "if", "else", "while", "for", "function", "return",
    "struct", "class", "interface", "extends", "implements", "import",
    "export", "true", "false", "null", "new", "this", "break", "continue",
}

# 鸿蒙声明式 UI 装饰器
DECORATORS = {"@Entry", "@Component", "@State", "@Link", "@Prop", "@Provide",
              "@Consume", "@Builder", "@Reusable", "@Observed", "@ObjectLink",
              "@CrossDevice", "@Remote", "@Local"}

# 多字符运算符优先匹配
OPERATORS = ["===", "!==", "==", "!=", "<=", ">=", "&&", "||", "++", "--",
             "+=", "-=", "*=", "/=", "=>",
             "+", "-", "*", "/", "%", "=", "<", ">", "!", "?", ":", "&", "|"]
SEPARATORS = {"(": "LPAREN", ")": "RPAREN", "{": "LBRACE", "}": "RBRACE",
              "[": "LBRACKET", "]": "RBRACKET", ";": "SEMICOLON",
              ",": "COMMA", ".": "DOT"}


@dataclass
class Token:
    type: str          # KEYWORD / IDENT / DECORATOR / INT / FLOAT / STRING / OP / SEP / EOF
    value: object
    line: int
    col: int

    def __repr__(self):
        return f"{self.type}({self.value!r})@{self.line}:{self.col}"


@dataclass
class LexError(Exception):
    msg: str
    line: int
    col: int

    def __str__(self):
        return f"[词法错误] 第{self.line}行 第{self.col}列: {self.msg}"


class Lexer:
    def __init__(self, src: str):
        self.src = src
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self.errors: list[LexError] = []

    def _peek(self, k=0):
        i = self.pos + k
        return self.src[i] if i < len(self.src) else ""

    def _advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _add(self, type_, value, line, col):
        self.tokens.append(Token(type_, value, line, col))

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.src):
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "/" and self._peek(1) == "/":          # 行注释
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
            elif ch == "/" and self._peek(1) == "*":          # 块注释
                sl, sc = self.line, self.col
                self._advance(); self._advance()
                closed = False
                while self.pos < len(self.src):
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance(); self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    self.errors.append(LexError("未闭合的块注释", sl, sc))
            elif ch.isdigit():                                 # 数字字面量
                self._number()
            elif ch.isalpha() or ch == "_" or ch == "$":       # 标识符/关键字
                self._ident()
            elif ch == "@":                                    # 装饰器
                sl, sc = self.line, self.col
                self._advance()
                name = self._read_word()
                if "@" + name in DECORATORS:
                    self._add("DECORATOR", "@" + name, sl, sc)
                else:
                    self._add("IDENT", name, sl, sc)
                    self.errors.append(LexError(f"未知装饰器 @{name}", sl, sc))
            elif ch == '"' or ch == "'":                       # 字符串字面量
                self._string(ch)
            else:
                self._symbol()
        self._add("EOF", None, self.line, self.col)
        return self.tokens

    def _read_word(self):
        start = self.pos
        while self._peek() and (self._peek().isalnum() or self._peek() in "_$"):
            self._advance()
        return self.src[start:self.pos]

    def _number(self):
        sl, sc = self.line, self.col
        start = self.pos
        while self._peek().isdigit():
            self._advance()
        is_float = False
        if self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        text = self.src[start:self.pos]
        self._add("FLOAT" if is_float else "INT",
                  float(text) if is_float else int(text), sl, sc)

    def _ident(self):
        sl, sc = self.line, self.col
        word = self._read_word()
        if word in KEYWORDS:
            self._add("KEYWORD", word, sl, sc)
        else:
            self._add("IDENT", word, sl, sc)

    def _string(self, quote):
        sl, sc = self.line, self.col
        self._advance()                                   # 跳过开头引号
        buf = []
        while True:
            if self.pos >= len(self.src):
                self.errors.append(LexError(f"未闭合的字符串字面量", sl, sc))
                break
            ch = self._advance()
            if ch == quote:
                break
            if ch == "\\":                                # 转义
                if self.pos < len(self.src):
                    esc = self._advance()
                    buf.append({"n": "\n", "t": "\t", '"': '"',
                                "'": "'", "\\": "\\"}.get(esc, esc))
            else:
                buf.append(ch)
        self._add("STRING", "".join(buf), sl, sc)

    def _symbol(self):
        sl, sc = self.line, self.col
        for op in OPERATORS:                              # 最长匹配
            if self.src.startswith(op, self.pos):
                for _ in op:
                    self._advance()
                self._add("OP", op, sl, sc)
                return
        if self._peek() in SEPARATORS:
            ch = self._advance()
            self._add("SEP", ch, sl, sc)
            return
        self.errors.append(LexError(f"非法字符 {self._peek()!r}", sl, sc))
        self._advance()


def tokenize(src: str):
    """返回 (tokens, errors)"""
    lx = Lexer(src)
    toks = lx.tokenize()
    return toks, lx.errors


if __name__ == "__main__":
    demo = '''
// Mini-ArkTS demo
@Entry
@Component
struct Hello {
  @State count: number = 0
  @State msg: string = "hi"
  build() {
    Column() {
      Text("点击次数: " + this.count).fontSize(30)
      Button("add").onClick(() => { this.count++ })
    }
  }
}
'''
    toks, errs = tokenize(demo)
    for t in toks:
        print(t)
    for e in errs:
        print(e)

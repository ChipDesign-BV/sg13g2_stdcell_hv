#!/usr/bin/env python3
"""Translate Liberty Boolean expressions into charlib's syntax.

Liberty and charlib do not use the same operator set:

    Liberty   !X  X'   X&Y  X*Y  X Y   X+Y  X|Y   X^Y
    charlib   !X       X&Y              X|Y        --

charlib's BooleanEvaluator only rewrites ! ~ & |, so Liberty's *, + and
implicit AND have to be normalised, and ^ has no counterpart at all and must
be expanded to (a & !b) | (!a & b).

Liberty precedence, tightest first:  '  !  &  ^  |
"""
import re

TOKEN = re.compile(r"\s*([A-Za-z_]\w*|[01]|[!~&*+|^()']|\S)")


def tokenize(s):
    out, i = [], 0
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            break
        out.append(m.group(1))
        i = m.end()
    return out


class Parser:
    def __init__(self, expr):
        self.t = tokenize(expr)
        self.i = 0
        self.src = expr

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        v = self.peek()
        self.i += 1
        return v

    # expr := xor ( ('|'|'+') xor )*
    def expr(self):
        n = self.xor()
        while self.peek() in ("|", "+"):
            self.take()
            n = ("or", n, self.xor())
        return n

    # xor := andx ( '^' andx )*
    def xor(self):
        n = self.andx()
        while self.peek() == "^":
            self.take()
            n = ("xor", n, self.andx())
        return n

    # andx := unary ( ('&'|'*'|<implicit>) unary )*
    def andx(self):
        n = self.unary()
        while True:
            p = self.peek()
            if p in ("&", "*"):
                self.take()
                n = ("and", n, self.unary())
            elif p is not None and (p == "(" or re.fullmatch(r"[A-Za-z_]\w*|[01]", p)):
                n = ("and", n, self.unary())      # implicit AND (juxtaposition)
            else:
                return n

    # unary := ('!'|'~') unary | primary "'"*
    def unary(self):
        p = self.peek()
        if p in ("!", "~"):
            self.take()
            return ("not", self.unary())
        n = self.primary()
        while self.peek() == "'":
            self.take()
            n = ("not", n)
        return n

    def primary(self):
        p = self.take()
        if p == "(":
            n = self.expr()
            if self.peek() == ")":
                self.take()
            return n
        if p is None:
            raise ValueError(f"unexpected end of expression in {self.src!r}")
        return ("var", p)


def emit(n):
    k = n[0]
    if k == "var":
        return n[1]
    if k == "not":
        return f"!({emit(n[1])})"
    if k == "and":
        return f"({emit(n[1])} & {emit(n[2])})"
    if k == "or":
        return f"({emit(n[1])} | {emit(n[2])})"
    if k == "xor":
        a, b = emit(n[1]), emit(n[2])
        return f"(({a} & !({b})) | (!({a}) & {b}))"
    raise ValueError(k)


def convert(liberty_expr):
    """Liberty Boolean expression -> charlib Boolean expression."""
    return emit(Parser(liberty_expr).expr())


def operands(liberty_expr):
    return sorted(set(re.findall(r"[A-Za-z_]\w*", liberty_expr)))


def truth_table(charlib_expr, ins):
    """Evaluate the converted expression the way charlib will, so a
    translation can be checked against the original."""
    py = (charlib_expr.upper().replace("!", " not ").replace("~", " not ")
          .replace("&", " and ").replace("|", " or "))
    f = eval(f"lambda {','.join(ins)}: {py}")
    out = []
    for m in range(2 ** len(ins)):
        vals = {p: bool((m >> k) & 1) for k, p in enumerate(ins)}
        out.append(bool(f(**vals)))
    return out


def liberty_truth_table(lib_expr, ins):
    """Reference evaluation straight from the Liberty AST."""
    def ev(n, vals):
        k = n[0]
        if k == "var":
            if n[1] in ("0", "1"):
                return n[1] == "1"
            return vals[n[1]]
        if k == "not":
            return not ev(n[1], vals)
        if k == "and":
            return ev(n[1], vals) and ev(n[2], vals)
        if k == "or":
            return ev(n[1], vals) or ev(n[2], vals)
        if k == "xor":
            return ev(n[1], vals) != ev(n[2], vals)
        raise ValueError(k)

    ast = Parser(lib_expr).expr()
    out = []
    for m in range(2 ** len(ins)):
        vals = {p: bool((m >> k) & 1) for k, p in enumerate(ins)}
        out.append(ev(ast, vals))
    return out


if __name__ == "__main__":
    tests = ["!(A*B)", "!(A+B)", "(A&B)|C", "A^B", "!(A^B)",
             "!((A1*A2)+B1)", "(A1 A2)+B1", "A'", "!(A*(B+C))",
             "(D*GATE)+(Q*!GATE)"]
    print(f"{'liberty':28s} {'charlib':50s} equiv")
    ok = True
    for t in tests:
        c = convert(t)
        ins = operands(t)
        same = truth_table(c, ins) == liberty_truth_table(t, ins)
        ok &= same
        print(f"{t:28s} {c:50s} {'OK' if same else 'MISMATCH'}")
    print("\nall equivalent" if ok else "\nTRANSLATION BUG")

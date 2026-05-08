from .ketypes import Location, error, nowhere
from . import global_state

memory__get_as_expression = lambda **kw: None
forward__string_of_expr = lambda _: ""

def is_store(expr) -> bool:
    return isinstance(expr, tuple) and expr[0] == "Store"

def loc_of_expr(expr) -> Location:
    match expr:
        case ("Int", l, _) | ("Str", l, _) | ("Res", l, _) | ("Store", l) | \
             ("VarOrFn", l, _, _) | ("Op", l, _, _, _) | ("LogOp", l, _, _, _) | \
             ("AndOr", l, _, _, _) | ("Unary", l, _, _) | ("Func", l, _, _, _, _) | \
             ("SelFunc", l, _, _, _, _) | ("IVar", l, _, _) | ("SVar", l, _, _) | \
             ("Deref", l, _, _, _) | ("ExprSeq", l, _, _, _) | ("Parens", l, _):
            return l
    raise ValueError(f"Invalid expression node: {expr}")

def simple_of_expression(e) -> tuple:
    return ("Simple", loc_of_expr(e), e)

def expression_of_simple(simp) -> tuple:
    if simp[0] == "Simple": return simp[2]
    raise ValueError("expression_of_simple")

def type_of_normalised_expr(e, allow_invalid: bool = True) -> str:
    match e:
        case ("Int", _, _) | ("Store", _) | ("IVar", _, _, _) | ("LogOp", _, _, _, _) | \
             ("AndOr", _, _, _, _) | ("Unary", _, _, _):
            return "int"
        case ("Str", _, _):
            return "literal"
        case ("SVar", _, _, _):
            return "str"
        case ("Op", _, inner, _, _) | ("Parens", _, inner):
            return type_of_normalised_expr(inner, allow_invalid)
        case ("Func", l, _, _, _, _) | ("SelFunc", l, _, _, _, _):
            if allow_invalid: return "invalid"
            error(l, "invalid element in type_of_normalised_expr")
        case ("Deref", l, _, _, _) | ("VarOrFn", l, _, _) | ("Res", l, _) | ("ExprSeq", l, _, _, _):
            error(l, "invalid element in type_of_normalised_expr")
    raise ValueError()

def normalised_expr_is_const(e) -> bool:
    match e:
        case ("Int", _, _) | ("Str", _, _): return True
        case ("Parens", _, inner): return normalised_expr_is_const(inner)
        case _: return False

def const_of_normalised_expr(e, abort_on_fail: bool = True, expect: str = "none") -> tuple:
    def fail(l: Location, s: str):
        if abort_on_fail:
            errstr = s + "\nErroneous expression: " + forward__string_of_expr(e) if l == nowhere else s
            error(l, errstr)
        else:
            raise Exception("const_of_normalised_expr failed")
            
    match e:
        case ("Int", l, i):
            if expect == "str": fail(l, "expected string constant, found integer")
            return ("Integer", i)
        case ("Str", l, t):
            if expect == "int": fail(l, "expected integer constant, found string")
            return ("String", t)
        case ("Parens", _, inner):
            return const_of_normalised_expr(inner, abort_on_fail, expect)
        case ("Store", l) | ("IVar", l, _, _):
            fail(l, "expected constant, found integer variable")
        case ("SVar", l, _, _):
            fail(l, "expected constant, found string variable")
        case _:
            fail(loc_of_expr(e), "expected constant, found variable expression")

def int_of_normalised_expr(e) -> int:
    res = const_of_normalised_expr(e, expect="int")
    if res[0] == "Integer": return res[1]
    raise AssertionError()

def str_of_normalised_expr(e) -> list:
    res = const_of_normalised_expr(e, expect="str")
    if res[0] == "String": return res[1]
    raise AssertionError()

def map_expr_leaves(f, expr):
    match expr:
        case ("Op", l, a, o, b): return ("Op", l, map_expr_leaves(f, a), o, map_expr_leaves(f, b))
        case ("LogOp", l, a, o, b): return ("LogOp", l, map_expr_leaves(f, a), o, map_expr_leaves(f, b))
        case ("AndOr", l, a, o, b): return ("AndOr", l, map_expr_leaves(f, a), o, map_expr_leaves(f, b))
        case ("Unary", l, o, e): return ("Unary", l, o, map_expr_leaves(f, e))
        case ("Parens", l, e): return ("Parens", l, map_expr_leaves(f, e))
        case ("Func", _, _, _, _, _) | ("SelFunc", _, _, _, _, _) | ("ExprSeq", _, _, _, _): return expr
        case leaf: return f(leaf)

def set_expr_loc(l: Location, expr):
    match expr:
        case ("Int", _, i): return ("Int", l, i)
        case ("Str", _, t): return ("Str", l, t)
        case ("Res", _, t): return ("Res", l, t)
        case ("Store", _): return ("Store", l)
        case ("IVar", _, i, e): return ("IVar", l, i, e)
        case ("SVar", _, i, e): return ("SVar", l, i, e)
        case ("Deref", _, s, t, e): return ("Deref", l, s, t, e)
        case ("VarOrFn", _, s, t): return ("VarOrFn", l, s, t)
        case ("Op", _, a, op, b): return ("Op", l, a, op, b)
        case ("LogOp", _, a, op, b): return ("LogOp", l, a, op, b)
        case ("AndOr", _, a, op, b): return ("AndOr", l, a, op, b)
        case ("Unary", _, op, e): return ("Unary", l, op, e)
        case ("Parens", _, e): return ("Parens", l, set_expr_loc(l, e))
        case ("Func", _, s, t, p, d): return ("Func", l, s, t, p, d)
        case ("SelFunc", _, s, t, o, p): return ("SelFunc", l, s, t, o, p)
        case ("ExprSeq", _, t, s, d): return ("ExprSeq", l, t, s, d)

def loc_of_statement(stmt) -> Location:
    match stmt:
        case ("Null",) | ("Hiding", _, _, _) | ("Seq", _): return nowhere
        case ("Halt", l) | ("Break", l) | ("Continue", l) | ("Label", (l, _, _)) | ("Decl", l, _, _, _): return l
        case ("GotoOn", l, _, _, _) | ("GotoCase", l, _, _, _) | ("UnknownOp", l, _, _, _): return l
        case ("Select", l, _, _, _, _, _) | ("FuncCall", l, _, _, _, _, _) | ("VarOrFn", l, _, _): return l
        case ("Return", l, _, _) | ("LoadFile", l, _) | ("Assign", l, _, _, _): return l
        case ("Define", l, _, _, _, _) | ("DConst", l, _, _, _, _) | ("DUndef", l, _): return l
        case ("DInline", l, _, _, _, _, _) | ("DTarget", l, _) | ("DVersion", l, _, _, _, _): return l
        case ("DSet", l, _, _, _, _) | ("Directive", l, _, _, _): return l
        case ("Block", l, _) | ("If", l, _, _, _) | ("DIf", l, _, _, _): return l
        case ("DFor", l, _, _, _, _, _) | ("While", l, _, _) | ("Repeat", l, _, _): return l
        case ("For", l, _, _, _, _) | ("Case", l, _, _, _) | ("RawCode", l, _): return l
    raise ValueError(f"Unknown statement: {stmt}")

def expr_of_statement(stmt):
    match stmt:
        case ("VarOrFn", _, _, _) as e: return e
        case ("Return", _, _, e): return e
        case ("Select", l, ("Store", _), s, i, e, p): return ("SelFunc", l, s, i, e, p)
        case ("FuncCall", l, d, s, t, p, lbl) if d is None or (isinstance(d, tuple) and d[0] == "Store"): 
            return ("Func", l, s, t, p, lbl)
        case _: error(loc_of_statement(stmt), "expected expression, found non-convertible statement")

def equal_strings(s1, s2) -> bool:
    return False

def equal_exprs(e1, e2) -> bool:
    match (e1, e2):
        case (("Func", *args), _) | (_, ("Func", *args)) | (("SelFunc", *args), _) | (_, ("SelFunc", *args)):
            raise AssertionError()
        case (("Res", *args), _) | (_, ("Res", *args)) | (("Deref", *args), _) | (_, ("Deref", *args)) | \
             (("VarOrFn", *args), _) | (_, ("VarOrFn", *args)) | (("ExprSeq", *args), _) | (_, ("ExprSeq", *args)):
            raise Exception("expressions not normalised")
        case (("Parens", _, a), ("Parens", _, b)): return equal_exprs(a, b)
        case (("Parens", _, a), b): return equal_exprs(a, b)
        case (a, ("Parens", _, b)): return equal_exprs(a, b)
        case (("Int", _, i), ("Int", _, j)): return i == j
        case (("Str", _, t), ("Str", _, u)): return equal_strings(t, u)
        case (("Store", _), ("Store", _)): return True
        case (("IVar", _, i, a), ("IVar", _, j, b)): return i == j and equal_exprs(a, b)
        case (("SVar", _, i, a), ("SVar", _, j, b)): return i == j and equal_exprs(a, b)
        case (("Op", _, a, o, b), ("Op", _, c, p, d)): return o == p and equal_exprs(a, c) and equal_exprs(b, d)
        case (("LogOp", _, a, o, b), ("LogOp", _, c, p, d)): return o == p and equal_exprs(a, c) and equal_exprs(b, d)
        case (("AndOr", _, a, o, b), ("AndOr", _, c, p, d)): return o == p and equal_exprs(a, c) and equal_exprs(b, d)
        case (("Unary", _, o, i), ("Unary", _, p, j)): return o == p and equal_exprs(i, j)
        case _: return False

def exists_in_expr(f, expr) -> bool:
    if f(expr): return True
    match expr:
        case ("Store", _) | ("Int", _, _) | ("Str", _, _) | ("Res", _, _): return False
        case ("VarOrFn", loc, _, t): 
            try: return f(memory__get_as_expression(t, loc=loc))
            except: return False
        case ("Deref", _, _, _, e): return exists_in_expr(f, e)
        case ("Op", _, a, _, b) | ("LogOp", _, a, _, b) | ("AndOr", _, a, _, b): return exists_in_expr(f, a) or exists_in_expr(f, b)
        case ("Unary", _, _, e) | ("Parens", _, e) | ("IVar", _, _, e) | ("SVar", _, _, e): return exists_in_expr(f, e)
        case ("Func", _, _, _, p, _):
            for param in p:
                match param:
                    case ("Simple", _, e): 
                        if exists_in_expr(f, e): return True
                    case ("Complex", _, es) | ("Special", _, _, es):
                        if any(exists_in_expr(f, se) for se in es): return True
            return False
        case ("SelFunc", _, _, _, w, p):
            if w is not None and exists_in_expr(f, w): return True
            for param in p:
                match param:
                    case ("Always", _, e):
                        if exists_in_expr(f, e): return True
                    case ("Special", _, l, e):
                        if exists_in_expr(f, e): return True
                        for spec in l:
                            match spec:
                                case ("Flag", _, _, _): pass
                                case ("Cond", _, _, _, None, e2) | ("NonCond", _, _, _, e2):
                                    if exists_in_expr(f, e2): return True
                                case ("Cond", _, _, _, Some_d, e2):
                                    if exists_in_expr(f, Some_d) or exists_in_expr(f, e2): return True
            return False
        case ("ExprSeq", _, _, _, d):
            return len(d) > 1 or (len(d) == 1 and f(expr_of_statement(d[-1])))
    return False

# Pretty-printing
def string_of_op(op: str) -> str:
    ops = {"Add": "+", "Sub": "-", "Mul": "*", "Div": "/", "Mod": "%", "And": "&", "Or": "|", "Xor": "^", "Shl": "<<", "Shr": ">>", "LAnd": "&&", "LOr": "||", "Equ": "==", "Neq": "!=", "Ltn": "<", "Lte": "<=", "Gtn": ">", "Gte": ">=", "Not": "!", "Inv": "~"}
    return ops.get(op, str(op))

def string_of_assign_op(op: str) -> str:
    ops = {"Set": "=", "Add": "+=", "Sub": "-=", "Mul": "*=", "Div": "/=", "Mod": "%=", "And": "&=", "Or": "|=", "Xor": "^=", "Shl": "<<=", "Shr": ">>="}
    return ops.get(op, str(op))

def string_of_list(f, p, sep=",") -> str:
    return (sep + " ").join(map(f, p))

def variable_name(b: int, prefix: bool = True) -> str:
    sprefix = lambda s: ("str" + s) if prefix else s
    iprefix = lambda i: ("int" + i) if prefix else i
    var_map = { 0x0a: sprefix("K"), 0x0b: iprefix("L"), 0x0c: sprefix("M"), 0x12: sprefix("S"), 0x00: iprefix("A"), 0x01: iprefix("B"), 0x02: iprefix("C"), 0x03: iprefix("D"), 0x04: iprefix("E"), 0x05: iprefix("F"), 0x06: iprefix("G"), 0x19: iprefix("Z") }
    return var_map.get(b, f"VAR{b}")

def string_of_expr(expr) -> str:
    match expr:
        case ("Store", _) | ("IVar", _, _, _) | ("SVar", _, _, _) | ("Deref", _, _, _, _) | ("VarOrFn", _, _, _): return string_of_assignable(expr)
        case ("Int", _, i): return str(i)
        case ("Str", _, t): return f"'{string_of_strtokens(t)}'"
        case ("Res", _, t): return f"#res<{t}>"
        case ("Op", _, a, op, b): return f"{string_of_expr(a)} {string_of_op(op)} {string_of_expr(b)}"
        case ("LogOp", _, a, op, b): return f"{string_of_expr(a)} {string_of_op(op)} {string_of_expr(b)}"
        case ("AndOr", _, a, op, b): return f"{string_of_expr(a)} {string_of_op(op)} {string_of_expr(b)}"
        case ("Unary", _, op, e): return f"{string_of_op(op)}{string_of_expr(e)}"
        case ("Parens", _, e): return f"({string_of_expr(e)})"
        case ("Func", _, s, _, p, d): return f"{s}({string_of_list(string_of_param, p)}){(' ' + string_of_label(d)) if d else ''}"
        case ("SelFunc", _, s, _, None, p): return f"{s}({string_of_list(string_of_sel_param, p)})"
        case ("SelFunc", _, s, _, e, p): return f"{s}[{string_of_expr(e)}]({string_of_list(string_of_sel_param, p)})"
        case ("ExprSeq", _, _, l, d):
            # Flattened lambda and string concat to avoid pre-Python 3.12 f-string backslash errors
            prefix = f"< {string_of_list(lambda x: str(x[0]) + ' = ' + string_of_expr(x[1]), l)} " if l else ""
            return f"{{{prefix}> {string_of_list(string_of_statement, d)} }}"
    return ""

def string_of_strtokens(tokens) -> str:
    rv = []
    for t in tokens:
        match t:
            case ("DQuote", _): rv.append('"')
            case ("RCur", _): rv.append("}")
            case ("LLentic", _): rv.append("[")
            case ("RLentic", _): rv.append("]")
            case ("Asterisk", _): rv.append("*")
            case ("Percent", _): rv.append("%")
            case ("Hyphen", _): rv.append("-")
            case ("Speaker", _): rv.append("\\{")
            case ("Space", _, i): rv.append(" " * i)
            case ("Text", _, _, txt): rv.append(str(txt))
            case ("Delete", _): rv.append("\\d")
    return "".join(rv)

def string_of_assignable(a) -> str:
    match a:
        case ("Store", _): return "store"
        case ("IVar", _, i, e): return f"{variable_name(i)}[{string_of_expr(e)}]"
        case ("SVar", _, i, e): return f"{variable_name(i)}[{string_of_expr(e)}]"
        case ("Deref", _, s, _, e): return f"{s}[{string_of_expr(e)}]"
        case ("VarOrFn", _, s, _): return s

def string_of_param(p) -> str:
    match p:
        case ("Simple", _, e): return string_of_expr(e)
        case ("Complex", _, params): return f"{{{string_of_list(string_of_expr, params)}}}"
        case ("Special", _, i, params): return f"__special[{i}]({string_of_list(string_of_expr, params)})"

def string_of_sel_param(p) -> str:
    match p:
        case ("Always", _, e): return string_of_expr(e)
        case ("Special", _, l, e):
            def f(x):
                match x:
                    case ("Flag", _, s, _): return s
                    case ("NonCond", _, s, _, e): return f"{s}({string_of_expr(e)})"
                    case ("Cond", _, s, _, None, e): return f"{s} if {string_of_expr(e)}"
                    case ("Cond", _, s, _, v, e): return f"{s}({string_of_expr(v)}) if {string_of_expr(e)}"
            return f"{'; '.join(map(f, l))}: {string_of_expr(e)}"

def string_of_label(lbl) -> str:
    return f"@{lbl[1]}"

def goto_gosub(tup) -> str:
    return tup[0]

def string_of_case(c) -> str:
    match c:
        case ("Default", l): return f"_: {string_of_label(l)}"
        case ("Match", e, l): return f"({string_of_expr(e)}): {string_of_label(l)}"

def string_of_statement(stmt) -> str:
    match stmt:
        case ("Null",): return "[null]"
        case ("Hiding", _, txt, _): return "[hiding]"
        case ("RawCode", _, _): return "raw ... endraw"
        case ("Halt", _): return "halt"
        case ("Break", _): return "break"
        case ("Continue", _): return "continue"
        case ("Label", l): return f"  {string_of_label(l)}"
        case ("GotoOn", _, g, e, l): return f"{goto_gosub(g)}_on ({string_of_expr(e)}) {{ {string_of_list(string_of_label, l)} }}"
        case ("GotoCase", _, g, e, c): return f"{goto_gosub(g)}_case ({string_of_expr(e)}) {{ {string_of_list(string_of_case, c, sep=';')} }}"
        case ("Select", _, ("Store", _), s, _, None, p): return f"{s}({string_of_list(string_of_sel_param, p)})"
        case ("Select", _, ("Store", _), s, _, e, p): return f"{s}[{string_of_expr(e)}]({string_of_list(string_of_sel_param, p)})"
        case ("Select", _, d, s, _, None, p): return f"{string_of_assignable(d)} = {s}({string_of_list(string_of_sel_param, p)})"
        case ("Select", _, d, s, _, e, p): return f"{string_of_assignable(d)} = {s}[{string_of_expr(e)}]({string_of_list(string_of_sel_param, p)})"
        case ("UnknownOp", _, fn, _, p): return f"{fn['ident']}({string_of_list(string_of_param, p)})"
        case ("FuncCall", _, None, s, _, p, l): return f"{s}({string_of_list(string_of_param, p)}){(' ' + string_of_label(l)) if l else ''}"
        case ("FuncCall", _, d, s, _, p, l): return f"{string_of_assignable(d)} = {s}({string_of_list(string_of_param, p)}){(' ' + string_of_label(l)) if l else ''}"
        case ("Assign", _, d, op, e): return f"{string_of_assignable(d)} {string_of_assign_op(op)} {string_of_expr(e)}"
        case ("VarOrFn", _, s, _): return s
        case ("Return", _, b, e): return f"{'return ' if b else ''}{string_of_expr(e)}"
        case ("LoadFile", _, e): return f"#load {string_of_expr(e)}"
        case ("Define", _, s, _, sc, e): return f"#{'s' if sc else ''}define {s} = {string_of_expr(e)}"
        case ("DConst", _, s, _, cb, e): return f"#{cb.lower()} {s} = {string_of_expr(e)}"
        case ("DUndef", _, l): return f"#undef {string_of_list(lambda x: x[1], l)}"
        case ("DTarget", _, s): return f"#target {s}"
        case ("DVersion", _, a, b, c, d): return f"#version {string_of_expr(a)}.{string_of_expr(b)}.{string_of_expr(c)}.{string_of_expr(d)}"
        case ("Directive", _, s, _, e): return f"#{s} {string_of_expr(e)}"
        case ("Seq", b): return string_of_list(string_of_statement, b)
        case ("Block", _, b): return f":\n  {string_of_list(string_of_statement, b, sep=chr(10)+' ' )};"
        case ("If", _, e, s, None): return f"if {string_of_expr(e)} {string_of_statement(s)}"
        case ("If", _, e, s, t): return f"if {string_of_expr(e)} {string_of_statement(s)}\nelse {string_of_statement(t)}"
        case ("While", _, e, s): return f"while {string_of_expr(e)} {string_of_statement(s)}"
        case ("Repeat", _, s, e): return f"repeat\n  {string_of_list(string_of_statement, s, sep=chr(10)+' ')}\ntill {string_of_expr(e)}"
        case ("For", _, p, c, i, s): return f"for ({string_of_statement(('Seq', p))}; {string_of_expr(c)}; {string_of_statement(('Seq', i))}) {string_of_statement(s)}"
        case ("DFor", _, s, _, f, t, d): return f"#for {s} = {string_of_expr(f)} .. {string_of_expr(t)} {string_of_statement(d)}"
        case ("DIf", _, _, _, _) as dif: return string_of_ifdir(False, dif)
    return str(stmt)

def string_of_ifdir(is_cont: bool, d) -> str:
    match d:
        case ("DIf", _, e, b, c): return f"#{'else' if is_cont else ''}if {string_of_expr(e)}\n  {string_of_list(string_of_statement, b, sep=chr(10)+' ')}\n{string_of_ifdir(True, c)}"
        case ("DElse", _, b): return f"#else\n  {string_of_list(string_of_statement, b, sep=chr(10)+' ')}\n#endif"
        case ("DEndif", _): return "#endif"

forward__string_of_expr = string_of_expr
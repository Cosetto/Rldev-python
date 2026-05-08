from typing import List, Dict, Any, Optional
from . import ketypes
from .ketypes import *
from . import global_state
from . import app

def unique_label(loc: Location) -> tuple:
    s = f"__auto@_{global_state.unique()}__"
    return (loc, s, s)

def code_of_op(op: str) -> str:
    mapping = {
        "Add": '\x00', "Sub": '\x01', "Mul": '\x02', "Div": '\x03', "Mod": '\x04',
        "And": '\x05', "Or": '\x06', "Xor": '\x07', "Shl": '\x08', "Shr": '\x09',
        "LAnd": '\x3c', "LOr": '\x3d', "Equ": '\x28', "Neq": '\x29',
        "Lte": '\x2a', "Ltn": '\x2b', "Gte": '\x2c', "Gtn": '\x2d'
    }
    return mapping[op]

def code_of_assign_op(op: str) -> str:
    mapping = {
        "Add": '\x14', "Sub": '\x15', "Mul": '\x16', "Div": '\x17', "Mod": '\x18',
        "And": '\x19', "Or": '\x1a', "Xor": '\x1b', "Shl": '\x1c', "Shr": '\x1d',
        "Set": '\x1e'
    }
    return mapping[op]

def code_of_binary(lhs: str, op: str, rhs: str) -> str:
    return f"{lhs}\\{op}{rhs}"

def code_of_int32(cval: int) -> str:
    # Decode the 4-byte packed int32 as latin-1 to concatenate with string
    packed = ketypes.str_of_int32(cval).decode('latin-1')
    return f"$\xff{packed}"

def code_of_var(var) -> str:
    match var:
        case ("Store", _):
            return "$\xc8"
        case ("IVar", _, i, e) | ("SVar", _, i, e):
            return f"${chr(i)}[{code_of_expr(e)}]"
        case ("Deref", l, _, _, _) | ("VarOrFn", l, _, _):
            error(l, "internal error: user variable or function should have been disambiguated in Expr.transform")
    raise ValueError(f"Unknown var in code_of_var: {var}")

def code_of_expr(expr) -> str:
    match expr:
        case ("Int", _, i): return code_of_int32(i)
        case ("Op", _, a, op, b): return code_of_binary(code_of_expr(a), code_of_op(op), code_of_expr(b))
        case ("LogOp", _, a, op, b): return code_of_binary(code_of_expr(a), code_of_op(op), code_of_expr(b))
        case ("AndOr", _, a, op, b): return code_of_binary(code_of_expr(a), code_of_op(op), code_of_expr(b))
        case ("Unary", _, "Sub", e): return f"\\{code_of_op('Sub')}{code_of_expr(e)}"
        case ("Unary", l, _, _): error(l, "internal error: unary operators other than '-' should have been transformed to binary operations in Expr.transform")
        case ("Parens", _, e): return f"({code_of_expr(e)})"
        case ("Store", *_) | ("IVar", *_) | ("SVar", *_) | ("Deref", *_) | ("VarOrFn", *_) as v: return code_of_var(v)
        case ("Func", l, *_) | ("SelFunc", l, *_):
            error(l, "internal error: function calls should have been lifted out of expressions in Expr.transform")
        case ("Str", l, *_) | ("Res", l, *_):
            error(l, "internal error: type mismatches should have been discovered in Expr.transform")
        case ("ExprSeq", l, *_):
            error(l, "internal error: sequence expressions should have been lifted out of expressions in Expr.transform")
    raise ValueError(f"Unknown expression in code_of_expr: {expr}")

def code_of_assignment(assign) -> str:
    _, loc, dest, op, expr = assign
    return code_of_binary(code_of_var(dest), code_of_assign_op(op), code_of_expr(expr))

def code_of_opcode(op_type: int, op_module: int, op_code: int, argc: int, overload: int) -> str:
    op_code_str = ketypes.str16_of_int(op_code).decode('latin-1')
    argc_str = ketypes.str16_of_int(argc).decode('latin-1')
    return f"#{chr(op_type)}{chr(op_module)}{op_code_str}{argc_str}{chr(overload)}"

class OutputState:
    def __init__(self):
        self.bytecode: List[Any] = []
        self.labels: Dict[str, Any] = {}
        self.lnum: int = -1

    def add_line(self, loc: Location, force: bool = False):
        if app.debug_info:
            self.bytecode.append(("Lineref", loc.line))
        elif force:
            self.bytecode.append(("Lineref", 0))
        self.lnum = loc.line

    def maybe_line(self, loc: Location):
        if loc != nowhere and loc.line != self.lnum:
            self.add_line(loc)

    def add_code(self, loc: Location, s: str):
        self.maybe_line(loc)
        self.bytecode.append(("Code", s))

    def length(self) -> int:
        return len(self.bytecode)

    def insert_code(self, i: int, s: str):
        self.bytecode.insert(i, ("Code", s))

    def add_label(self, tup: tuple):
        loc, s, t = tup
        if t in self.labels:
            error(loc, f"@{s} already defined; label identifiers must be unique")
        self.bytecode.append(("Label", t))
        self.labels[t] = None

    def add_ref(self, tup: tuple):
        loc, _, t = tup
        self.bytecode.append(("LabelRef", loc, t))

    def add_entry(self, idx: int):
        self.bytecode.append(("Entrypoint", idx))

    def add_kidoku(self, loc: Location):
        self.maybe_line(loc)
        self.bytecode.append(("Kidoku", loc.line))

Output = OutputState()
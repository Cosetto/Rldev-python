from typing import Dict, Tuple, Callable, List, Any

from . import ketypes
from .ketypes import *
from . import global_state
from . import keast
from . import memory

builtins: Dict[str, Tuple[Callable, Callable]] = {}

def is_builtin(t: str) -> bool:
    return t in builtins

def buildin(s: str, f: Callable, g: Callable):
    builtins[s] = (f, g)

def eval_as_expr(tup: tuple) -> Any:
    loc, _, t, parms, label = tup
    assert label is None
    return builtins[t][0](loc, parms)

def eval_as_code(tup: tuple) -> Any:
    loc, rv, _, t, parms, label = tup
    assert label is None
    return builtins[t][1](loc, rv, parms)

def make_unignorable_as_code(fn: str) -> Callable:
    def inner(loc: Location, rv: Any, parms: List[Any]):
        if rv is None:
            error(loc, f"the return value of the '{fn}' intrinsic cannot be ignored")
        return ("Assign", loc, rv, "Set", eval_as_expr((loc, fn, fn, parms, None)))
    return inner

# The actual functions

def defined_expr(loc: Location, syms: List[Any]):
    all_defined = True
    for sym in syms:
        if isinstance(sym, tuple) and sym[0] == "Simple" and isinstance(sym[2], tuple) and sym[2][0] == "VarOrFn":
            if not memory.defined(sym[2][3]):
                all_defined = False
                break
        else:
            error(loc, "the 'defined?' intrinsic must be passed only simple identifiers")
    return ("Int", loc, 1 if all_defined else 0)

buildin("defined?", defined_expr, make_unignorable_as_code("defined?"))

def default_expr(loc: Location, syms: List[Any]):
    if len(syms) == 2 and syms[0][0] == "Simple" and syms[1][0] == "Simple":
        ifdef = syms[0][2]
        ifndef = syms[1][2]
        if ifdef[0] == "VarOrFn" and memory.defined(ifdef[3]):
            return ifdef
        return ifndef
    error(loc, "the 'default' intrinsic must be passed a symbol and an expression")

buildin("default", default_expr, make_unignorable_as_code("default"))

def constant_expr(loc: Location, exprs: List[Any]):
    try:
        for ex in exprs:
            if ex[0] == "Simple":
                global_state.expr__normalise_and_get_const(ex[2], abort_on_fail=False)
            else:
                raise ValueError()
        return ("Int", loc, 1)
    except Exception:
        return ("Int", loc, 0)

buildin("constant?", constant_expr, make_unignorable_as_code("constant?"))

def integer_expr(loc: Location, exprs: List[Any]):
    def not_int(e) -> bool:
        ptype = e[0]
        if ptype in ("Int", "Store", "IVar", "LogOp", "AndOr", "Unary", "SelFunc"): return False
        if ptype in ("Str", "SVar", "Res"): return True
        if ptype in ("Op", "Parens"): return not_int(e[2])
        if ptype == "ExprSeq": return not_int(keast.expr_of_statement(e[4][-1]))
        if ptype == "Func" and (memory.defined(e[3]) or is_builtin(e[3])):
            return not_int(global_state.expr__disambiguate(e))
        if ptype in ("VarOrFn", "Deref"):
            return not_int(global_state.expr__disambiguate(e))
        if ptype == "Func":
            f = ketypes.rlfun(e[3])
            return ketypes.function_type(f) != "int"
        return False
        
    try:
        for ex in exprs:
            if ex[0] == "Simple":
                if not_int(ex[2]): raise ValueError()
            else: raise ValueError()
        return ("Int", loc, 1)
    except Exception:
        return ("Int", loc, 0)

buildin("integer?", integer_expr, make_unignorable_as_code("integer?"))

def array_expr(loc: Location, syms: List[Any]):
    def check_arr(x: str) -> bool:
        val, _ = memory.symbols.get(x, (None, None))
        if not val: return False
        if val[0] == "StaticVar" and val[3] is not None: return True
        if val[0] == "Macro" and val[1][0] == "VarOrFn": return check_arr(val[1][3])
        return False

    all_defined = True
    for sym in syms:
        if sym[0] == "Simple" and sym[2][0] == "VarOrFn":
            if not check_arr(sym[2][3]):
                all_defined = False
                break
        else:
            error(loc, "the 'array?' intrinsic must be passed only simple identifiers")
    return ("Int", loc, 1 if all_defined else 0)

buildin("array?", array_expr, make_unignorable_as_code("array?"))

def length_expr(loc: Location, syms: List[Any]):
    if len(syms) == 1 and syms[0][0] == "Simple" and syms[0][2][0] == "VarOrFn":
        str_name, sym = syms[0][2][2], syms[0][2][3]
        def get_len(x: str):
            val, _ = memory.symbols.get(x, (None, None))
            if val and val[0] == "StaticVar" and val[3] is not None:
                return ("Int", loc, val[3])
            if val and val[0] == "Macro" and val[1][0] == "VarOrFn":
                return get_len(val[1][3])
            error(loc, f"'{str_name}' is not an array")
        return get_len(sym)
    error(loc, "the 'length' function must be passed a single array variable")

buildin("length", length_expr, make_unignorable_as_code("length"))

def __deref_expr(loc: Location, syms: List[Any]):
    if len(syms) == 2 and syms[0][0] == "Simple" and syms[1][0] == "Simple":
        space = global_state.expr__normalise_and_get_int(syms[0][2])
        return ("IVar", loc, space, syms[1][2])
    error(loc, "the '__deref' intrinsic must be passed an integer constant and an expression")

buildin("__deref", __deref_expr, make_unignorable_as_code("__deref"))

def __sderef_expr(loc: Location, syms: List[Any]):
    if len(syms) == 2 and syms[0][0] == "Simple" and syms[1][0] == "Simple":
        space = global_state.expr__normalise_and_get_int(syms[0][2])
        return ("SVar", loc, space, syms[1][2])
    error(loc, "the '__sderef' intrinsic must be passed an integer constant and an expression")

buildin("__sderef", __sderef_expr, make_unignorable_as_code("__sderef"))

def gameexe_expr(loc: Location, params: List[Any]):
    if not params: error(loc, "the 'gameexe' intrinsic requires you to specify at minimum a key")
    if len(params) > 3: error(loc, "too many parameters to 'gameexe': this intrinsic takes a maximum of three")
    
    key_expr = params[0][2]
    idx_expr = params[1][2] if len(params) > 1 else ("Int", nowhere, 0)
    default_expr = params[2][2] if len(params) > 2 else None

    try:
        k_str = global_state.expr__normalise_and_get_str(key_expr, abort_on_fail=False)
        k_str = "".join([t[3] for t in k_str if t[0] == "Text"]) # Basic extraction
        if not k_str: error(loc, "the key passed to 'gameexe' must not be empty")
        if k_str.startswith('#'): k_str = k_str[1:]
    except Exception:
        error(loc, "the key passed to 'gameexe' must evaluate to a constant")

    try:
        idx = global_state.expr__normalise_and_get_int(idx_expr, abort_on_fail=False)
    except Exception:
        error(loc, "the index passed to 'gameexe' must evaluate to a constant")

    from . import ini_parser
    val = ini_parser.get(k_str)
    if val:
        try:
            item = val[idx]
            if item[0] == "Enabled": return ("Int", loc, 1 if item[1] else 0)
            if item[0] == "Integer": return ("Int", loc, item[1])
            if item[0] == "String": return ("Str", loc, [("Text", loc, "Sbcs", item[1])])
        except IndexError:
            error(loc, f"unable to return value {idx} from #{k_str}: index out of range")
            
    if default_expr is not None:
        return default_expr
    error(loc, f"unable to find #{k_str} in GAMEEXE.INI, and no default was provided")

buildin("gameexe", gameexe_expr, make_unignorable_as_code("gameexe"))

def kinetic_expr(loc: Location, params: List[Any]):
    if not params:
        return ("Int", loc, 1 if ketypes.global_target == "kinetic" else 0)
    error(loc, "'kinetic?' takes no parameters")

buildin("kinetic?", kinetic_expr, make_unignorable_as_code("kinetic?"))

def __variable_expr(loc: Location, syms: List[Any]):
    rtrue = ("Int", loc, 1)
    rfalse = ("Int", loc, 0)
    if len(syms) == 1:
        e = syms[0][2]
        if e[0] in ("IVar", "SVar"): return rtrue
        if e[0] == "VarOrFn":
            try:
                val = memory.get_as_expression(e[3], loc=loc, allow_arrays=True, recurse=True)
                if val[0] in ("IVar", "SVar"): return rtrue
            except KeyError: pass
        elif e[0] == "Deref":
            try:
                val = memory.get_deref_as_expression(e[3], e[4], loc=loc)
                if val[0] in ("IVar", "SVar"): return rtrue
            except KeyError: pass
    return rfalse

buildin("__variable?", __variable_expr, make_unignorable_as_code("__variable?"))


def __addr_expr(loc: Location, syms: List[Any]):
    def make_addr(space, iexpr):
        return ("Op", nowhere, iexpr, "Or", ("Op", nowhere, ("Int", nowhere, space), "Shl", ("Int", nowhere, 16)))
        
    if len(syms) == 1:
        e = syms[0][2]
        if e[0] in ("IVar", "SVar"): return make_addr(e[2], e[3])
        if e[0] == "VarOrFn":
            try:
                val = memory.get_as_expression(e[3], loc=loc, allow_arrays=True, recurse=True)
                if val[0] in ("IVar", "SVar"): return make_addr(val[2], val[3])
            except KeyError: pass
        elif e[0] == "Deref":
            try:
                val = memory.get_deref_as_expression(e[3], e[4], loc=loc)
                if val[0] in ("IVar", "SVar"): return make_addr(val[2], val[3])
            except KeyError: pass
    error(loc, "the '__addr' intrinsic must be passed a single variable")

buildin("__addr", __addr_expr, make_unignorable_as_code("__addr"))


def __ident_expr(loc: Location, syms: List[Any]):
    if len(syms) == 1:
        e = syms[0][2]
        try:
            str_arr = global_state.expr__normalise_and_get_str(e)
            s = "".join([t[3] for t in str_arr if t[0] == "Text"])
            return ("VarOrFn", loc, s, s)
        except Exception: pass
    error(loc, "the '__ident' intrinsic function must be passed a single string constant")

buildin("__ident", __ident_expr, make_unignorable_as_code("__ident"))


def at_expr(loc: Location, syms: List[Any]):
    if len(syms) == 3:
        try:
            f = "".join([t[3] for t in global_state.expr__normalise_and_get_str(syms[0][2]) if t[0] == "Text"])
            ln = global_state.expr__normalise_and_get_int(syms[1][2])
            return keast.set_expr_loc(Location(f, ln), syms[2][2])
        except Exception: pass
    error(loc, "the 'at' intrinsic function must be passed a location and an expression (str file; int line; any expression)")

def at_code(loc: Location, rv: Any, syms: List[Any]):
    assert rv is None
    if len(syms) == 3:
        try:
            f = "".join([t[3] for t in global_state.expr__normalise_and_get_str(syms[0][2], abort_on_fail=False) if t[0] == "Text"])
            ln = global_state.expr__normalise_and_get_int(syms[1][2])
            code_str = "".join([t[3] for t in global_state.expr__normalise_and_get_str(syms[2][2], abort_on_fail=False) if t[0] == "Text"])
            
            from . import ke_u_lexer
            ke_u_lexer.call_parser_on_text("program", Location(f, ln), code_str)
            return ("Null",)
        except Exception: pass
    error(loc, "the 'at' intrinsic statement must be passed a location and a string to evaluate (str file; int line; str statement_string)")

buildin("at", at_expr, at_code)


def __empty_string_expr(loc: Location, syms: List[Any]):
    if len(syms) == 1:
        try:
            sarr = global_state.expr__normalise_and_get_str(syms[0][2], abort_on_fail=False)
            text = "".join([t[3] for t in sarr if t[0] == "Text"])
            return ("Int", loc, 1 if text == "" else 0)
        except Exception: pass
    error(loc, "the '__empty_string?' intrinsic must be passed a single string constant")

buildin("__empty_string?", __empty_string_expr, make_unignorable_as_code("__empty_string?"))


def __equal_strings_expr(loc: Location, syms: List[Any]):
    if len(syms) == 2:
        try:
            s1 = "".join([t[3] for t in global_state.expr__normalise_and_get_str(syms[0][2], abort_on_fail=False) if t[0] == "Text"])
            s2 = "".join([t[3] for t in global_state.expr__normalise_and_get_str(syms[1][2], abort_on_fail=False) if t[0] == "Text"])
            return ("Int", loc, 1 if s1 == s2 else 0)
        except Exception: pass
    error(loc, "the '__equal_strings?' intrinsic must be passed a single string constant")

buildin("__equal_strings?", __equal_strings_expr, make_unignorable_as_code("__equal_strings?"))


def rlc_parse_string_expr(loc: Location, syms: List[Any]):
    if len(syms) == 1:
        try:
            str_arr = global_state.expr__normalise_and_get_str(syms[0][2], abort_on_fail=False)
            text = "".join([t[3] for t in str_arr if t[0] == "Text"])
            from . import ke_u_lexer
            return ke_u_lexer.call_parser_on_text("just_expression", loc, text)
        except Exception: pass
    error(loc, "the 'rlc_parse_string' intrinsic must be passed a single string constant")

def rlc_parse_string_code(loc: Location, rv: Any, syms: List[Any]):
    assert rv is None
    if len(syms) == 1:
        try:
            str_arr = global_state.expr__normalise_and_get_str(syms[0][2], abort_on_fail=False)
            text = "".join([t[3] for t in str_arr if t[0] == "Text"])
            from . import ke_u_lexer
            ke_u_lexer.call_parser_on_text("program", loc, text)
            return ("Null",)
        except Exception: pass
    error(loc, "the 'rlc_parse_string' intrinsic must be passed a single string constant")

buildin("rlc_parse_string", rlc_parse_string_expr, rlc_parse_string_code)


def make_target_comp(fname: str, op_fn: Callable):
    def compver(loc, args):
        res = []
        for a in args:
            try:
                res.append(global_state.expr__normalise_and_get_int(a[2], abort_on_fail=False))
            except Exception:
                error(loc, f"the parameters to '{fname}' must evaluate to integer constants")
        if 1 <= len(res) <= 4:
            return tuple(res + [0] * (4 - len(res)))
        error(loc, f"'{fname}' must be passed between 1 and 4 parameters")

    def expr_fn(loc: Location, args: List[Any]):
        v_target = ketypes.current_version()
        v_comp = compver(loc, args)
        return ("Int", loc, 1 if op_fn(v_target, v_comp) else 0)
    
    buildin(fname, expr_fn, make_unignorable_as_code(fname))

make_target_comp("target_lt", lambda a, b: a < b)
make_target_comp("target_le", lambda a, b: a <= b)
make_target_comp("target_gt", lambda a, b: a > b)
make_target_comp("target_ge", lambda a, b: a >= b)

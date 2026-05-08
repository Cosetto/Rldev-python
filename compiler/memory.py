from typing import Dict, List, Tuple, Any, Optional
from . import ketypes
from .ketypes import *
from . import global_state
from . import meta

class MemoryError(Exception):
    pass

def memerr(s: str):
    raise MemoryError(s)

# Static variable map
staticvars: List[Dict[int, int]] = [{} for _ in range(13)]

def varidx(i: int) -> int:
    if i < 7: return i
    if i == 25: return 7
    if i == 18: return 8
    if i == 12: return 9
    if i in (10, 11) and current_version() > (1, 3, 0, 0): return i
    raise KeyError()

# Global state tables
symbols: Dict[str, Tuple[Any, bool]] = {}
scope: List[Dict[str, None]] = []
defines: Dict[str, None] = {}

def _key(id_: str) -> str:
    return id_.lower()

def open_scope():
    scope.append({})

open_scope() # open top-level scope

def defined(t: str) -> bool:
    return _key(t) in symbols

def pull_sym(id_: str) -> Tuple[Any, bool]:
    id_ = _key(id_)
    rv = symbols[id_]
    del symbols[id_]
    return rv

def replace_sym(id_: str, sym: Tuple[Any, bool]):
    id_ = _key(id_)
    symbols[id_] = sym

def check_def(s: str) -> Callable[[], bool]:
    def check():
        return defined(s)
    return check

warn_hide = check_def("__WarnHiddenSymbols__")

def warn_hide_fun() -> bool:
    return not check_def("__HideFunctionsSilently__")()

def define(id_: str, value: Any, warnings: bool = True, scoped: bool = True, loc: Location = nowhere):
    id_ = _key(id_)
    if warnings:
        if warn_hide() and defined(id_):
            warning(loc, f"hiding existing symbol '{id_}'")
        else:
            if warn_hide_fun() and (global_state.intrinsic__is_builtin(id_) or id_ in ketypes.functions):
                warning(loc, f"symbol is hiding API function '{id_}'")
    symbols[id_] = (value, scoped)
    if scoped:
        scope[-1][id_] = None
    else:
        defines[id_] = None

def dealloc(sym: Any):
    if sym[0] == "StaticVar":
        space, idx, length = sym[1], sym[2], sym[6] # (space, idx, len_opt, space_mapped, idx, length)
        space_mapped = sym[4]
        for i in range(idx, idx + length):
            m = staticvars[space_mapped]
            nval = m.get(i, 0) - 1
            assert nval >= 0
            if nval == 0:
                del m[i]
            else:
                m[i] = nval

def process_sym(f: Callable[[Dict], Any]) -> Any:
    try:
        return f(symbols)
    except KeyError:
        memerr("undeclared identifier[6]")

def undefine(loc: Location, s: str, id_: str):
    id_ = _key(id_)
    def inner_undef(tbl):
        sym, scoped = tbl[id_]
        dealloc(sym)
        del tbl[id_]
        return scoped
    scoped = process_sym(inner_undef)
    tbl = scope[-1] if scoped else defines
    if id_ in tbl:
        del tbl[id_]
    else:
        error(loc, f"cannot undefine symbol '{s}': not declared in current scope")

def close_scope():
    closing = scope.pop()
    if not scope:
        memerr("internal error: closed top-level scope")
    for id_ in closing:
        try:
            def inner_del(tbl):
                sym, _ = tbl[id_] # Simplification of OCaml filter for local scope var
                dealloc(sym)
                del tbl[id_]
            process_sym(inner_del)
        except MemoryError:
            pass

def describe(t: str) -> str:
    t = _key(t)
    try:
        val, _ = symbols[t]
        if val[0] == "Macro": return "macro"
        if val[0] == "Inline": return "inline block"
        if val[0] == "Integer": return "integer constant"
        if val[0] == "String": return "string constant"
        if val[0] == "StaticVar":
            space_mapped = val[4]
            if val[3] is None and space_mapped in (8, 9, 10): return "string variable"
            if space_mapped in (8, 9, 10): return "string array"
            if val[3] is None: return "integer variable"
            return "integer array"
    except KeyError:
        pass
    return "undeclared identifier[8]"

def get_args(loc: Location, args: List[Any], defs: List[Any], s: str) -> List[Tuple[str, Any]]:
    al = len(args)
    dl = len(defs)
    optcount = sum(1 for d in defs if d[3] != "None")
    
    if dl - optcount <= al <= dl:
        acc = []
        for i, d in enumerate(defs):
            _, _, t, e = d
            if i < al:
                acc.append((t, args[i]))
            else:
                if e[0] == "Some":
                    acc.append((t, e[1]))
                elif e == "Optional":
                    continue
                else:
                    error(loc, f"internal error: parameter {d[1]} should have a default value")
        return acc
    else:
        if al < dl:
            missing = ", ".join([d[1] for d in defs[al:]])
            error(loc, f"missing parameters to {s}: {missing}")
        else:
            error(loc, f"{al - dl} extra parameters to {s}")

def get_as_expression(id_: str, allow_arrays: bool = False, recurse: bool = False, args: List[Any] = None, loc: Location = nowhere, s: Optional[str] = None):
    id_ = _key(id_)
    args = args or []
    s_val = s if s else id_
    try:
        val, _ = symbols[id_]
    except KeyError:
        raise KeyError()

    if val[0] == "Integer": return ("Int", loc, val[1])
    if val[0] == "String": return ("Str", loc, [("Text", loc, "Sbcs", val[1])])
    if val[0] == "StaticVar":
        space, idx, len_opt, space_mapped = val[1], val[2], val[3], val[4]
        if len_opt is not None and not allow_arrays:
            error(loc, f"expected scalar, found array '{s_val}'")
        if space_mapped in (8, 9, 10):
            return ("SVar", loc, space, ("Int", loc, idx))
        return ("IVar", loc, space, ("Int", loc, idx))
    if val[0] == "Inline":
        l, a = val[1], val[2]
        if a[0] == "Seq":
            seq = a[1]
        elif a[0] == "Block":
            seq = a[2]
        else:
            seq = [a]
        return ("ExprSeq", loc, id_, get_args(loc, args, l, s_val), seq)
    if val[0] == "Macro":
        inner = val[1]
        if inner[0] == "VarOrFn" and recurse and defined(inner[3]):
            return get_as_expression(inner[3], allow_arrays, recurse, args, loc, s_val)
        return inner

def get_deref_as_expression(id_: str, offset, loc: Location = nowhere, s: Optional[str] = None):
    id_ = _key(id_)
    s_val = s if s else id_
    try:
        val, _ = symbols[id_]
    except KeyError:
        raise KeyError()
        
    if val[0] == "StaticVar":
        sp, idx, len_opt, space_mapped, _, length = val[1], val[2], val[3], val[4], val[5], val[6]
        try:
            offsc = global_state.expr__normalise_and_get_int(offset, abort_on_fail=False)
            if offsc < 0 or offsc >= length:
                error(loc, f"index {offsc} exceeds bounds of array '{s_val}[{length}]'")
        except Exception:
            if check_def("__SafeArrays__")():
                lhs = ("LogOp", nowhere, offset, "Gte", meta.int_val(0))
                rhs = ("LogOp", nowhere, offset, "Ltn", meta.int_val(length))
                parm = ("AndOr", nowhere, lhs, "LAnd", rhs)
                msg = ("Str", nowhere, [("Text", nowhere, "Sbcs", "array index out of bounds")])
                parms = [("Simple", nowhere, parm), ("Simple", nowhere, msg)]
                meta.parse_elt(("FuncCall", nowhere, None, "assert", "assert", parms, None))
        
        idx_expr = ("Op", nowhere, ("Int", nowhere, idx), "Add", offset)
        if space_mapped >= 8: return ("SVar", loc, sp, idx_expr)
        return ("IVar", loc, sp, idx_expr)
        
    if val[0] == "Macro" and val[1][0] == "VarOrFn":
        return get_deref_as_expression(val[1][3], offset, loc, s_val)
    if val[0] in ("Macro", "Inline"):
        error(loc, f"expected array, found macro '{s_val}'")
    error(loc, f"expected array, found scalar '{s_val}'")

def get_as_code(id_: str, args: List[Any] = None, loc: Location = nowhere, s: Optional[str] = None):
    id_ = _key(id_)
    args = args or []
    s_val = s if s else id_
    val, _ = symbols[id_]
    
    if val[0] == "Macro":
        return ("Return", loc, False, val[1])
    if val[0] in ("Integer", "String", "StaticVar"):
        return ("Return", loc, False, get_as_expression(id_, loc=loc, s=s_val))
    if val[0] == "Inline":
        l, c = val[1], val[2]
        args_mapped = get_args(loc, args, l, s_val)
        if not l: return c
        rv = []
        for t_t, e in args_mapped:
            rv.append(("Define", loc, t_t, t_t, True, e))
        rv.append(c)
        return ("Block", nowhere, rv)

def get(id_: str):
    id_ = _key(id_)
    def inner_get(tbl):
        return tbl[id_]
    return process_sym(inner_get)

def mutate(loc: Location, s: str, id_: str, value: Any, scoped: bool):
    id_ = _key(id_)
    symbols[id_] = (value, scoped)

def find_unused_index(loc: Location, smap: Dict[int, int], first: int, last: int) -> int:
    i = first
    while True:
        if i == last:
            error(loc, "failed to allocate static memory")
        if smap.get(i, 0) > 0:
            i += 1
        else:
            return i

def find_unused_block(loc: Location, smap: Dict[int, int], first: int, length: int, max_idx: int = None) -> int:
    limit = 2000 - length
    i = first
    while i < limit:
        avail = True
        for j in range(i, i + length):
            if smap.get(j, 0) > 0:
                avail = False
                break
        if avail:
            if max_idx is not None and i + length > max_idx:
                error(loc, "unable to allocate block")
            return i
        i += 1
    error(loc, "failed to allocate static block")

temploc = Location("temporary variable", -2)

tis = "__int_alloc_space__"
tif = "__int_alloc_first__"
til = "__int_alloc_last__"
tss = "__str_alloc_space__"
tsf = "__str_alloc_first__"
tsl = "__str_alloc_last__"

def get_const(id_: str) -> int:
    id_ = _key(id_)
    assert defined(id_)
    val, _ = symbols[id_]
    assert val[0] == "Integer"
    return val[1]

def temp_int_spc(): return get_const(tis)
def temp_int_min(): return get_const(tif)
def temp_int_max(): return get_const(til)
def temp_str_spc(): return get_const(tss)
def temp_str_min(): return get_const(tsf)
def temp_str_max(): return get_const(tsl)

def allocate_block(loc: Location, space: int, idx: int, length: int):
    try:
        sp_idx = varidx(space)
    except KeyError:
        error(loc, f"cannot allocate variables in block 0x{space:02x}")
    for i in range(idx, idx + length):
        currbinding = staticvars[sp_idx].get(i, 0)
        staticvars[sp_idx][i] = currbinding + 1

def get_temp_int(space=None, min_val=None, max_val=None, useloc=temploc):
    space = space if space is not None else temp_int_spc()
    min_val = min_val if min_val is not None else temp_int_min()
    max_val = max_val if max_val is not None else temp_int_max()
    vidx = varidx(space)
    idx = find_unused_index(nowhere if useloc == temploc else useloc, staticvars[vidx], min_val, max_val)
    staticvars[vidx][idx] = 1
    define(f"[temp {space}.{idx}]", ("StaticVar", space, idx, None, vidx, idx, 1), warnings=False)
    return ("IVar", useloc, space, ("Int", nowhere, idx))

def get_temp_str(space=None, min_val=None, max_val=None, useloc=temploc):
    space = space if space is not None else temp_str_spc()
    min_val = min_val if min_val is not None else temp_str_min()
    max_val = max_val if max_val is not None else temp_str_max()
    vidx = varidx(space)
    idx = find_unused_index(nowhere if useloc == temploc else useloc, staticvars[vidx], min_val, max_val)
    staticvars[vidx][idx] = 1
    define(f"[temp {space}.{idx}]", ("StaticVar", space, idx, None, vidx, idx, 1), warnings=False)
    return ("SVar", useloc, space, ("Int", nowhere, idx))

def get_temp_var(vtype: str, s: str):
    try:
        return get_as_expression(s)
    except KeyError:
        tempvar = get_temp_int() if vtype == "Int" else get_temp_str()
        define(s, ("Macro", tempvar))
        return tempvar

from typing import Any
from . import ketypes
from .ketypes import *
from . import global_state
from . import memory
from . import meta
from . import str_lexer
from . import keast
from . import app
from . import codegen

def resource(loc: Location, expr: Any, res_dict: dict):
    # Retrieve literal string
    str_val = "".join([t[3] for t in global_state.expr__normalise_and_get_str(expr) if t[0] == "Text"])
    str_lexer.load_resfile(loc, str_val, res_dict)

def getconst(e: Any) -> Any:
    res = global_state.expr__normalise_and_get_const(e, abort_on_fail=True)
    if res[0] == "Integer": return ("Integer", res[1])
    if res[0] == "String": return ("String", "".join([t[3] for t in res[1] if t[0] == "Text"]))
    raise ValueError("getconst failed")

def set_val(tup: tuple):
    loc, s, t, is_set, e = tup
    try:
        val, scoped = memory.get(t)
        if val[0] in ("Macro", "Integer", "String"):
            new_val = getconst(e) if is_set else ("Macro", e)
            memory.mutate(loc, s, t, new_val, scoped)
        else:
            memory.memerr("not a constant")
    except memory.MemoryError as err:
        error(loc, f"cannot mutate '{s}': {err}")

def generic(loc: Location, expr: Any, cmd: str):
    def as_string(ex: Any) -> str:
        res = global_state.expr__normalise_and_get_const(ex)
        if res[0] == "String": return "".join([t[3] for t in res[1] if t[0] == "Text"])
        if res[0] == "Integer": return str(res[1])
        return ""
        
    if cmd == "warn": warning(keast.loc_of_expr(expr), as_string(expr))
    elif cmd == "error": error(keast.loc_of_expr(expr), as_string(expr))
    elif cmd == "print":
        l = keast.loc_of_expr(expr)
        ketypes.cli_info(f"{l.file} line {l.line}: {as_string(expr)}")
    elif cmd == "resource": resource(loc, expr, global_state.resources)
    elif cmd == "base_res": resource(loc, expr, global_state.base_res)
    elif cmd == "val_0x2c": global_state.val_0x2c = keast.int_of_normalised_expr(expr)
    elif cmd == "character": global_state.dramatis_personae.append(as_string(expr))
    elif cmd == "entrypoint":
        idx = keast.int_of_normalised_expr(expr)
        if idx < 0 or idx >= 100: error(loc, f"invalid entrypoint #Z{idx:02d}: valid values are 0..99")
        codegen.Output.add_entry(idx)
    elif cmd == "kidoku_type":
        global_state.kidoku_type = keast.int_of_normalised_expr(expr)
    elif cmd == "file":
        if not app.outfile: app.outfile = as_string(expr)
    else: raise ValueError(f"Unknown generic directive: {cmd}")

def define(dir_type: str, loc: Location, s: str, t: str, df: Any, scoped: bool):
    memory.define(t, df, scoped=scoped, loc=loc)

def compile_directive(d: Any):
    ptype = d[0]
    if ptype == "Directive":
        generic(d[1], d[4], d[2])
    elif ptype == "DTarget":
        if ketypes.target_forced: warning(d[1], "target specified on command-line: ignoring #target directive")
        else: ketypes.global_target = ketypes.target_t_of_string(d[2])
    elif ptype == "Define":
        define("define", d[1], d[2], d[3], ("Macro", d[5]), d[4])
    elif ptype == "DConst":
        define("const", d[1], d[2], d[3], getconst(d[5]), True)
    elif ptype == "DInline":
        define("inline", d[1], d[2], d[3], ("Inline", d[5], d[6]), d[4])
    elif ptype == "DUndef":
        for loc, s, t in d[2]: memory.undefine(loc, s, t)
    elif ptype == "DSet":
        set_val((d[1], d[2], d[3], d[4], d[5]))
    elif ptype == "DVersion":
        v_list = [global_state.expr__normalise_and_get_int(x) for x in (d[2], d[3], d[4], d[5])]
        ketypes.global_version = tuple(v_list)

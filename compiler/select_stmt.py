from typing import Any
from . import ketypes
from .ketypes import *
from . import codegen
from . import function
from . import global_state
from . import memory
from . import keast
from . import meta
from . import func_asm

def handle_parameter(insert_pos: int, s: str, l: Location, e: Any):
    etype = keast.type_of_normalised_expr(e)
    if etype == "invalid":
        function.undeclared_func_in_expr(e)
    if etype in ("int", "str"):
        codegen.Output.add_code(nowhere, f"###PRINT({codegen.code_of_expr(e)})")
        return
        
    text = function.get_literal_from_expr(e)
    def invalid(l_loc, c): error(l_loc, f"'\\{c}{{}}' invalid in {s}() calls")
    
    buf = []
    quoted = False
    
    def quote():
        nonlocal quoted
        if not quoted:
            buf.append('"')
            quoted = True
            
    def unquote():
        nonlocal quoted
        if quoted:
            buf.append('"')
            quoted = False
            
    def not_quoted(): return not quoted
    
    if not memory.defined("__DynamicLineationUsed__"):
        memory.define("__DynamicLineationUsed__", ("Integer", 1), scoped=False)
        
    for t in text:
        if t[0] == "RCur": quote(); buf.append("}")
        elif t[0] == "LLentic": buf.append("\x81\x79")
        elif t[0] == "RLentic": buf.append("\x81\x7a")
        elif t[0] == "Asterisk": buf.append("\x81\x96")
        elif t[0] == "Percent": buf.append("\x81\x93")
        elif t[0] == "Hyphen": buf.append("-")
        elif t[0] == "Space": quote(); buf.append(" " * t[2])
        elif t[0] == "Text":
            if not_quoted():
                pass
            buf.append(str(t[3]))
        elif t[0] == "Speaker": invalid(t[1], "{}' / `\\name")
        elif t[0] == "Gloss": invalid(t[1], "g" if t[2]=="Gloss" else "ruby")
        elif t[0] == "Add": invalid(t[1], "a")
        elif t[0] == "Delete": invalid(t[1], "d")
        elif t[0] == "ResRef": invalid(t[1], "res")
        elif t[0] == "Rewrite": invalid(t[1], "f")
        elif t[0] == "Code" and t[2] not in ("s", "i"): invalid(t[1], t[2])
        elif t[0] == "Name":
            lg = "\x81\x93" if t[2] == "Local" else "\x81\x96"
            idx_val = keast.int_of_normalised_expr(t[3])
            buf.append(f"__NAME_{lg}_{idx_val}__") # Mocked name str token
            if t[4]:
                w_val = keast.int_of_normalised_expr(t[4])
                buf.append(f"\x82{chr(w_val + 0x4f)}")
        elif t[0] == "DQuote":
            unquote()
            dq = function.double_quote_var(insert_pos)
            buf.append(f"###PRINT({codegen.code_of_expr(dq)})")
        elif t[0] == "Code":
            unquote()
            p = t[4][0][2]
            if t[2] == "s":
                buf.append(f"###PRINT({codegen.code_of_expr(p)})")
            elif t[2] == "i":
                s_var = memory.get_temp_str()
                codegen.Output.insert_code(insert_pos, func_asm.compile_function_str(nowhere, ketypes.rlfun("itoa"), [("Integer", codegen.code_of_expr(p)), ("Integer", codegen.code_of_expr(t[3]))], returnval=codegen.code_of_var(s_var)))
                buf.append(f"###PRINT({codegen.code_of_expr(s_var)})")
                
    unquote()
    codegen.Output.add_code(nowhere, "".join(buf))

def get_op(l: Location, s: str, t: str) -> str:
    mapping = {"colour": '0', "title": '1', "grey": '1', "hide": '2', "blank": '3', "cursor": '4'}
    if t in mapping: return mapping[t]
    error(l, f"unknown effect '{s}' in select condition")

def compile(tup: tuple):
    # Properly extract items, ignoring the node string at index 0
    _, loc, dest, s, opcode, window, params = tup
    if not params: warning(loc, f"'{s}' called with no options")

    window_args = []
    if window is not None:
        window_args = window if isinstance(window, list) else [window]
    overload = 2 if len(window_args) >= 3 else 1 if len(window_args) == 2 else 0
    
    codegen.Output.add_kidoku(loc)
    codegen.Output.add_code(loc, codegen.code_of_opcode(0, 2, opcode, len(params), overload))
    if window_args:
        if opcode == 13: error(loc, f"select window specifiers are not valid in '{s}' (opcode {opcode}) calls")
        codegen.Output.add_code(nowhere, "(" + "".join(codegen.code_of_expr(e) for e in window_args) + ")")
        
    codegen.Output.add_code(nowhere, "{")
    codegen.Output.add_line(loc, force=True)
    
    for p in params:
        if p[0] in ("Always", "Special"):
            if p[0] == "Always" or (p[0] == "Special" and not p[2]):
                e = p[2] if p[0] == "Always" else p[3]
                l = p[1]
                handle_parameter(codegen.Output.length(), s, l, e)
                codegen.Output.add_line(l, force=True)
            elif p[0] == "Special":
                l, cl, e = p[1], p[2], p[3]
                codegen.Output.add_code(nowhere, "(")
                use_line = True
                for spec in cl:
                    if spec[0] == "Flag":
                        codegen.Output.add_code(nowhere, get_op(spec[1], spec[2], spec[3]))
                        try: use_line = (keast.str_of_normalised_expr(e) != "")
                        except: use_line = True
                    elif spec[0] == "NonCond":
                        codegen.Output.add_code(nowhere, f"{get_op(spec[1], spec[2], spec[3])}{codegen.code_of_expr(spec[4])}")
                    elif spec[0] == "Cond":
                        codegen.Output.add_code(nowhere, f"({codegen.code_of_expr(spec[5])}){get_op(spec[1], spec[2], spec[3])}")
                        if spec[4]: codegen.Output.add_code(nowhere, codegen.code_of_expr(spec[4]))
                codegen.Output.add_code(nowhere, ")")
                if use_line: handle_parameter(codegen.Output.length(), s, l, e)
                codegen.Output.add_line(l, force=True)
                
    codegen.Output.add_code(nowhere, "}")
    if dest is not None and dest[0] != "Store":
        codegen.Output.add_code(loc, f"{codegen.code_of_var(dest)}\\\x1e$\xc8")

def compile_vwf(tup: tuple):
    # Properly extract items, ignoring the node string at index 0
    _, loc, dest, s, opcode, window, params = tup
    if opcode not in (0, 1, 10, 11):
        compile(tup)
        return
        
    def get_var(e):
        v = memory.get_temp_str(useloc=nowhere)
        function.compile(("FuncCall", nowhere, None, "strcpy", "strcpy", [("Simple", nowhere, v), ("Simple", nowhere, e)], None))
        return v
        
    memory.open_scope()
    vars_list, vparams = [], []
    for p in params:
        if p[0] == "Always":
            v = get_var(p[2])
            vars_list.append(v)
            vparams.append(("Always", p[1], v))
        elif p[0] == "Special":
            v = get_var(p[3])
            vars_list.append(v)
            vparams.append(("Special", p[1], p[2], v))
            
    def loop(func_str, l):
        if not l: return
        meta.call(func_str, [window if window is not None else meta.int_val(-1)] + l[:3])
        loop("__vwf_SelectAdd", l[3:])
        
    loop("__vwf_SelectInit", vars_list)
    compile((loc, dest, s, opcode, window, vparams))
    meta.call("__vwf_SelectCleanup", [dest] if dest else [])
    memory.close_scope()

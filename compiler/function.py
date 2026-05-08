from typing import Any, List, Optional
from . import ketypes
from .ketypes import *
from . import global_state
from . import memory
from . import codegen
from . import func_asm
from . import intrinsic
from . import keast
from . import goto
from . import text_encoding

def fail(loc: Location, s: str):
    error(loc, f"unable to find a prototype for '{s}' that matches these parameters")

def expected(loc: Location, etype: str, msg: str):
    mapping = {
        "Any": "any type", "Int": "integer variable", "IntC": "integer", "IntV": "integer",
        "Str": "string variable", "StrC": "string", "StrV": "string", "ResStr": "string",
        "Special": "special function", "Complex": "tuple"
    }
    tn = mapping.get(etype, str(etype))
    error(loc, f"expected {tn}, {msg}")

def _as_simple_param(param_or_expr: Any) -> Any:
    if isinstance(param_or_expr, tuple) and param_or_expr[0] == "Simple":
        return param_or_expr
    return keast.simple_of_expression(param_or_expr)

def _compile_short_gan_loader(loc: Location, s: str, t: str, params: List[Any], label: Any, def_op: ketypes.FuncDef) -> bool:
    short_overloads = {2: 0, 3: 1, 5: 2, 6: 3, 8: 4}
    if t.lower() not in ("objoffilegan", "objbgoffilegan"):
        return False
    if len(params) not in short_overloads:
        return False
    if len(params) >= 3:
        p = params[2]
        if p[0] != "Simple" or keast.type_of_normalised_expr(p[2], allow_invalid=False) != "int":
            return False

    paramdefs = [("IntC", []), ("StrC", [])] + [("IntC", []) for _ in params[2:]]
    m_params, _, cancel = check_and_compile(loc, s, paramdefs, params)
    if not cancel:
        f, a = func_asm.compile_function(loc, def_op, m_params, short_overloads[len(params)])
        codegen.Output.add_code(loc, f)
        if label: codegen.Output.add_ref(label)
        if a: codegen.Output.add_code(loc, a)
    return True

def undeclared_func_in_expr(e: Any):
    if e[0] == "Func": error(e[1], f"undeclared identifier[5] '{e[2]}'")
    elif e[0] == "Parens": undeclared_func_in_expr(e[2])
    else: raise ValueError("undeclared_func_in_expr")

def get_literal_from_expr(e: Any) -> Any:
    if e[0] == "Str": return e[2]
    if e[0] == "Parens": return get_literal_from_expr(e[2])
    raise ValueError("get_literal_from_expr")

def _literal_token_bytes(tokens: List[Any]) -> str:
    parts: List[str] = []
    needs_quotes = False

    def add_text(s: str, loc: Location):
        nonlocal needs_quotes
        raw = text_encoding.encode_text(str(s), loc, "function parameter")
        parts.append("".join(chr(b) for b in raw))
        for ch in str(s):
            ch_raw = text_encoding.encode_text(ch, loc, "function parameter")
            if len(ch_raw) == 2:
                continue
            b = ch_raw[0]
            if not (ord('A') <= b <= ord('Z') or ord('0') <= b <= ord('9') or b in (ord('_'), ord('?'))):
                needs_quotes = True

    for t in tokens:
        tag = t[0]
        loc = t[1] if len(t) > 1 else nowhere
        if tag == "RCur":
            needs_quotes = True
            parts.append("}")
        elif tag == "LLentic":
            add_text("\u3010", loc)
        elif tag == "RLentic":
            add_text("\u3011", loc)
        elif tag == "Asterisk":
            add_text("\uff0a", loc)
        elif tag == "Percent":
            add_text("\uff05", loc)
        elif tag == "Hyphen":
            needs_quotes = True
            parts.append("-")
        elif tag == "Space":
            needs_quotes = True
            parts.append(" " * t[2])
        elif tag == "Text":
            add_text(t[3], loc)
        else:
            error(loc, f"\\{tag} invalid in constant strings")

    s = "".join(parts)
    return f'"{s}"' if needs_quotes else s

def double_quote_var(insert_pos: int = None) -> Any:
    sym = "__double_quote_var__\000"
    try:
        return memory.get_as_expression(sym)
    except KeyError:
        svar = memory.get_temp_str()
        memory.define(sym, ("Macro", svar))
        
        # Compile zentohan call for Japanese double quote
        code_str = func_asm.compile_function_str(nowhere, ketypes.rlfun("zentohan"), 
            [("Literal", "\x81\x68")], returnval=codegen.code_of_var(svar))
            
        if insert_pos is None: codegen.Output.add_code(nowhere, code_str)
        else: codegen.Output.insert_code(insert_pos, code_str)
        return svar

def get_func_def(t: str, params: List[Any], look_in: dict = None) -> ketypes.FuncDef:
    look_in = look_in if look_in is not None else ketypes.functions
    
    # Force search to compare lowercase identities 
    t_lower = t.lower()
    found = look_in.get(t_lower)
    defs = [found] if found is not None else []
    valid_defs = [d for d in defs if ketypes.valid_opcode(d)]
    
    if not valid_defs:
        error(nowhere, f"the function '{t}' is not supported in {ketypes.current_version_string()}")
        
    if len(valid_defs) == 1:
        return valid_defs[0]
        
    if params:
        first_param = params[0] if params[0][0] == "Simple" else None
        if first_param:
            ptype = keast.type_of_normalised_expr(first_param[2], allow_invalid=False)
            for d in valid_defs:
                p = d.prototypes
                if p and p[0]:
                    p1_type = p[0][0][0]
                    if (ptype in ("str", "literal") and p1_type in ("Str", "StrC", "StrV", "ResStr")) or \
                       (ptype == "int" and p1_type in ("Int", "IntC", "IntV")):
                        return d
    return ketypes.ver_fun(t, valid_defs)

def check_and_compile(loc: Location, funname: str, defs: List[Any], params: List[Any]) -> Tuple[List[Any], int, bool]:
    cancel_compile_func = False
    argc = 0

    def map_param(s_defs, i: int, param: Any) -> Any:
        nonlocal argc, cancel_compile_func
        
        def handle_special(ll: Location, stype: Any, lparams: List[Any], p_def: Any) -> Any:
            nonlocal argc
            ptype, pflags = p_def[0], p_def[1]
            if ptype != "Special":
                msg = "special function" if stype[0] == "Index" else f"undeclared function '{stype[1]}'" if stype[0] == "Named" else "tuple"
                expected(ll, ptype, f"found {msg}")
            
            sdefs_list = p_def[2] if len(p_def)>2 else [] 
            s_id, s_def, s_flags = -1, [], []
            if stype[0] == "Index":
                idx = stype[1]
                match = next((s for s in sdefs_list if s[0] == idx), None)
                if not match: error(ll, f"special function {idx} is not defined for {funname}")
                s_id, s_def, s_flags = match[0], match[3], ["nobrace"] if match[4] else []
            elif stype[0] == "Named":
                name = stype[1]
                matches = [s for s in sdefs_list if s[1] == "named" and s[2] == name]
                if not matches: expected(ll, ptype, f"found undeclared function {name}")
                if len(matches) == 1: 
                    s_id, s_def, s_flags = matches[0][0], matches[0][3], ["nobrace"] if matches[0][4] else []
                else:
                    match = next((m for m in matches if len(m[3]) == len(lparams)), None)
                    if not match: error(ll, f"unable to find a version of the {funname} special function '{name}' that matches these parameters")
                    s_id, s_def, s_flags = match[0], match[3], ["nobrace"] if match[4] else []
            elif stype[0] == "AsComplex":
                valid_match = None
                for m in sdefs_list:
                    if m[1] in ("Named", "Index", "named", "index"): continue
                    sparams = m[3]
                    if len(sparams) != len(lparams): continue
                    
                    match_ok = True
                    for dt_param, lparam in zip(sparams, lparams):
                        dt = dt_param[0]
                        lt = keast.type_of_normalised_expr(lparam, allow_invalid=False)
                        if dt == "Any" and lt in ("int", "str", "literal"): continue
                        if dt in ("Int", "IntC", "IntV") and lt == "int": continue
                        if dt in ("Str", "StrC", "StrV", "ResStr") and lt in ("str", "literal"): continue
                        match_ok = False
                        break
                    
                    if match_ok:
                        valid_match = m
                        break
                        
                if not valid_match:
                    expected(ll, ptype, "found tuple (type mismatch)")
                    
                s_id, s_def, s_flags = valid_match[0], valid_match[3], ["nobrace"] if valid_match[4] else []
            
            if len(s_def) != len(lparams):
                msg = "special function" if stype[0] == "Index" else f"'{stype[1]}'" if stype[0] == "Named" else "tuple"
                error(ll, f"expected {len(s_def)} parameters to {msg}, but found {len(lparams)} parameters")
            if "uncount" not in pflags: argc += 1
            
            mapped_lparams = [map_param(s_def, idx, _as_simple_param(elt)) for idx, elt in enumerate(lparams)]
            return ("Special", s_id, s_flags, mapped_lparams)

        def handle_complex(ll: Location, lparams: List[Any], c_def: List[Any], pflags: List[str]) -> Any:
            nonlocal argc
            if len(c_def) != len(lparams):
                error(ll, f"expected {len(c_def)} parameters in tuple, but found {len(lparams)} parameters")
            if "uncount" not in pflags: argc += 1
            return ("List", [map_param(c_def, idx, keast.simple_of_expression(elt)) for idx, elt in enumerate(lparams)])

        def handle_literal_in_strc(ll: Location, pflags: List[str], e: Any) -> Any:
            nonlocal cancel_compile_func
            text = get_literal_from_expr(e)
            is_basic = True
            for t in text:
                if t[0] not in ("RCur", "LLentic", "RLentic", "Asterisk", "Percent", "Hyphen", "Text", "Space"):
                    is_basic = False; break
            if is_basic:
                return ("Literal", _literal_token_bytes(text))
            
            is_cpy_or_cat = "Strcpy" if funname.lower() == "strcpy" else "Strcat" if funname.lower() == "strcat" else "No"
            
            accum = params[0][2] if is_cpy_or_cat != "No" else memory.get_temp_str()
            empty = True
            buf = []
            quoted = False
            
            def flush():
                nonlocal empty, quoted
                if buf:
                    fn = "strcpy" if is_cpy_or_cat != "Strcat" and empty else "strcat"
                    s = "".join(buf)
                    s_lit = f'"{s}"' if quoted else s
                    codegen.Output.add_code(nowhere, func_asm.compile_function_str(nowhere, ketypes.rlfun(fn), [("String", codegen.code_of_expr(accum)), ("Literal", s_lit)]))
                    empty = False
                    quoted = False
                    buf.clear()

            for t in text:
                if t[0] == "RCur": quoted = True; buf.append("}")
                elif t[0] == "LLentic": buf.append("\x81\x79")
                elif t[0] == "RLentic": buf.append("\x81\x7a")
                elif t[0] == "Asterisk": buf.append("\x81\x96")
                elif t[0] == "Percent": buf.append("\x81\x93")
                elif t[0] == "Hyphen": quoted = True; buf.append("-")
                elif t[0] == "Space": quoted = True; buf.append(" " * t[2])
                elif t[0] == "Text":
                    buf.append(text_encoding.text_to_byte_string(t[3], t[1], "function parameter"))
                elif t[0] == "DQuote":
                    flush()
                    if is_cpy_or_cat != "Strcat" and empty:
                        codegen.Output.add_code(nowhere, func_asm.compile_function_str(nowhere, ketypes.rlfun("zentohan"), [("Literal", "\x81\x68")], returnval=codegen.code_of_expr(accum)))
                    else:
                        codegen.Output.add_code(nowhere, func_asm.compile_function_str(nowhere, ketypes.rlfun("strcat"), [("String", codegen.code_of_expr(accum)), ("String", codegen.code_of_expr(double_quote_var()))]))
                    empty = False
                elif t[0] == "Code":
                    if t[1] == "s":
                        parm = t[3][0][2]
                        flush()
                        fn = "strcpy" if is_cpy_or_cat != "Strcat" and empty else "strcat"
                        codegen.Output.add_code(nowhere, func_asm.compile_function_str(nowhere, ketypes.rlfun(fn), [("String", codegen.code_of_expr(accum)), ("String", codegen.code_of_expr(parm))]))
                        empty = False
            
            if empty and is_cpy_or_cat == "No":
                return ("Literal", "".join(buf) if not quoted else f'"{ "".join(buf) }"')
            
            flush()
            if is_cpy_or_cat == "Strcat" or (is_cpy_or_cat == "Strcpy" and len(params) == 2):
                cancel_compile_func = True
                return ("Unknown", "")
            return ("String", codegen.code_of_expr(accum))

        def handle_simple(ll: Location, e: Any, p_def: Any) -> Any:
            nonlocal argc
            ptype, pflags = p_def[0], p_def[1]
            if "uncount" not in pflags: argc += 1
            
            etype = keast.type_of_normalised_expr(e, allow_invalid=True)
            if etype == "invalid": undeclared_func_in_expr(e)
            
            if ptype == "Any" and etype == "literal": return handle_literal_in_strc(ll, pflags, e)
            if ptype == "Any": return ("Unknown", codegen.code_of_expr(e))
            if ptype in ("IntC", "Int") and etype == "int": return ("Integer", codegen.code_of_expr(e))
            if ptype == "IntV" and etype == "int":
                if e[0] in ("Store", "IVar"): return ("Integer", codegen.code_of_expr(e))
                tv = memory.get_temp_int()
                codegen.Output.add_code(nowhere, codegen.code_of_assignment((nowhere, tv, "Set", e)))
                return ("Integer", codegen.code_of_var(tv))
            if ptype in ("StrC", "ResStr") and etype == "str": return ("String", codegen.code_of_expr(e))
            if ptype in ("StrC", "ResStr") and etype == "literal": return handle_literal_in_strc(ll, pflags, e)
            if ptype == "Str" and etype == "str": return ("String", codegen.code_of_expr(e))
            if ptype == "StrV" and etype in ("str", "literal"):
                if e[0] == "SVar": return ("String", codegen.code_of_expr(e))
                tv = memory.get_temp_str()
                compile(("FuncCall", nowhere, None, "strcpy", "strcpy", [("Simple", nowhere, tv), ("Simple", nowhere, e)], None))
                return ("String", codegen.code_of_expr(tv))
                
            expected(ll, ptype, f"found {etype}")

        # Map Param Body
        p_def = s_defs[i] if i < len(s_defs) else s_defs[-1]
        
        if param[0] == "Simple" and param[2][0] == "Func":
            return handle_special(param[1], ("Named", param[2][2], param[2][3]), param[2][4], p_def)
        if param[0] == "Special":
            return handle_special(param[1], ("Index", param[2]), param[3], p_def)
        if param[0] == "Complex":
            if p_def[0] == "Special":
                return handle_special(param[1], ("AsComplex",), param[2], p_def)
            return handle_complex(param[1], param[2], p_def[2] if len(p_def)>2 else [], p_def[1])
        if param[0] == "Simple":
            if p_def[0] == "Special":
                return handle_special(param[1], ("AsComplex",), [param[2]], p_def)
            return handle_simple(param[1], param[2], p_def)
            
    plen = len(params)
    mapped_defs = []
    dlen = 0
    for elt in [d for d in defs if "return" not in d[1]]:
        if dlen < plen:
            mapped_defs.append(elt)
            dlen += 1
        elif any(f in ("optional", "argc") for f in elt[1]):
            break
            
    if dlen < plen:
        if "argc" in mapped_defs[-1][1]:
            for _ in range(dlen, plen): mapped_defs.append(mapped_defs[-1])
        else:
            fail(loc, funname)
            
    mapped_params = [map_param(mapped_defs, idx, p) for idx, p in enumerate(params)]
    return mapped_params, argc, cancel_compile_func

def choose_overload_func(loc: Location, options: List[Any], params: List[Any]) -> int:
    overload_lengths = []
    for idx, elt in enumerate(options):
        if elt is None:
            overload_lengths.append(None)
        else:
            t, o, r = 0, 0, False
            for param_def in elt:
                ptype, pflags = param_def[0], param_def[1]
                if ptype in ("Special", "Complex") or "argc" in pflags:
                    r = True
                elif "return" in pflags:
                    pass
                else:
                    t += 1
                    if "optional" in pflags:
                        o += 1
            overload_lengths.append((t, o, r, idx))
    
    param_count = 0
    for p in params:
        if p[0] == "Simple":
            expr = p[2]
            if isinstance(expr, tuple) and expr[0] == "Func":
                pass # Do not count inline Func calls
            else:
                param_count += 1
        else:
            param_count += 1
            
    for p_len in reversed(overload_lengths):
        if p_len is None: continue
        t, o, r, idx = p_len
        if t >= param_count and t - o <= param_count:
            return idx
            
    for i, opt in enumerate(options):
        if opt is not None: return i
    raise Exception("Not_found")

def compile(tup: tuple, is_code: bool = False):
    _, loc, dest, s, t, params, label = tup
    
    try:
        def_op = get_func_def(t, params, look_in=ketypes.ctrlcodes if is_code else ketypes.functions)
    except Exception:
        fail(loc, s)

    if not is_code and _compile_short_gan_loader(loc, s, t, params, label, def_op):
        return

    # Use our new statement-safe overload chooser
    if len(def_op.prototypes) == 1:
        overload = 0
    else:
        try:
            overload = choose_overload_func(loc, def_op.prototypes, params)
        except Exception:
            fail(loc, s)
            
    paramdefs = def_op.prototypes[overload]
    if not paramdefs: paramdefs = [("Any", []) for _ in params]

    # Handle special case conditionals
    if "cond" in def_op.flags and goto.special_case(compile, loc, s, def_op.ident, "neg" in def_op.flags, "call" in def_op.flags, params, label):
        return

    m_params, argc, cancel = check_and_compile(loc, s, paramdefs, params)
    
    if not cancel:
        rv = codegen.code_of_var(dest) if dest else None
        f, a = func_asm.compile_function(loc, def_op, m_params, overload, returnval=rv)
        codegen.Output.add_code(loc, f)
        if label: codegen.Output.add_ref(label)
        if a: codegen.Output.add_code(loc, a)

def compile_unknown(uop: tuple):
    # Properly extract items, ignoring the node string at index 0
    _, loc, def_op, overload, params = uop
    paramdefs = [("Any", []) for _ in params]
    m_params, argc, _ = check_and_compile(loc, def_op.ident, paramdefs, params)
    codegen.Output.add_code(loc, func_asm.compile_function_str(loc, def_op, m_params, overload))

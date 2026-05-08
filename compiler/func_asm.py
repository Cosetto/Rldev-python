from typing import List, Optional, Tuple, Any
from . import ketypes
from .ketypes import *
from . import codegen

# Parameter representations:
# ("String", str)
# ("Integer", str)
# ("Unknown", str)
# ("List", List[parameter])
# ("Special", int, List[str], List[parameter])
# ("Literal", str)

def parameters_to_string(params: List[Any], prev: Optional[Any] = None) -> str:
    parts = []
    current_prev = prev
    for p in params:
        s, current_prev = parameter_to_string(p, current_prev)
        parts.append(s)
    return "".join(parts)

def parameter_to_string(p: Any, prev: Optional[Any]) -> Tuple[str, Any]:
    ptype = p[0]
    if ptype in ("String", "Unknown"):
        return p[1], p
    if ptype == "List":
        inner = parameters_to_string(p[1], None)
        return f"({inner})", p
    if ptype == "Special":
        i, f, l = p[1], p[2], p[3]
        buf = []
        if i > 255:
            b0 = i & 0xff
            b1 = ((i >> 8) & 0xff) - 1
            buf.append(f"a{chr(b0)}a{chr(b1)}")
        else:
            buf.append(f"a{chr(i)}")
            
        if "nobrace" in f:
            buf.append(parameters_to_string(l, None))
        else:
            inner, _ = parameter_to_string(("List", l), None)
            buf.append(inner)
        return "".join(buf), p
    if ptype == "Integer":
        s = p[1]
        buf = []
        if s.startswith('\\'):
            needs_comma = True
            if prev is None or prev[0] in ("List", "Literal"): needs_comma = False
            elif prev[0] == "Special" and "nobrace" not in prev[2]: needs_comma = False
            if needs_comma: buf.append(",")
        buf.append(s)
        return "".join(buf), p
    if ptype == "Literal":
        s = p[1]
        buf = []
        needs_comma = False
        if prev is not None:
            if prev[0] == "Literal": needs_comma = True
            elif prev[0] == "Special" and "nobrace" in prev[2]: needs_comma = True
        if needs_comma: buf.append(",")
        buf.append('""' if s == "" else s)
        return "".join(buf), p
    raise ValueError(f"Unknown parameter type: {ptype}")

def get_prototype_lengths(func: ketypes.FuncDef) -> List[Tuple[int, int]]:
    found_arb = False
    rv = []
    for prototype in func.prototypes:
        if prototype is None:
            assert not found_arb
            found_arb = True
            rv.append((-1, -1))
            continue
            
        alen, blen = 0, 0
        for param_def in prototype:
            pflags = param_def[1]  # Safe extraction instead of 2-tuple unpack
            if alen == -1:
                pass
            elif "argc" in pflags:
                assert not found_arb
                found_arb = True
                alen, blen = -1, -1
            elif "optional" in pflags:
                blen += 1
            else:
                alen += 1
                blen += 1
        rv.append((alen, blen))
    return rv

def choose_overload(loc: Location, func: ketypes.FuncDef, argc: int) -> int:
    i = 0
    arb_idx = -1
    nonarbs = []
    
    for (min_len, max_len) in get_prototype_lengths(func):
        if min_len == -1:
            arb_idx = i
        elif min_len == max_len:
            nonarbs.append((i, min_len))
        else:
            for n in range(min_len, max_len + 1):
                nonarbs.append((i, n))
        i += 1

    if len(func.prototypes) <= 1:
        return 0
        
    for idx, length in nonarbs:
        if length == argc:
            return idx
            
    if arb_idx == -1:
        error(loc, f"unable to find a prototype for '{func.ident}' that matches these parameters")
    return arb_idx

def compile_function(loc: Location, func: ketypes.FuncDef, parameters: List[Any], overload: int = None, returnval: str = None) -> Tuple[str, Optional[str]]:
    argc = len(parameters) + (0 if returnval is None or "store" in func.flags else 1)
    
    overload_idx = choose_overload(loc, func, argc) if overload is None else overload
    
    if not func.prototypes or func.prototypes[overload_idx] is None:
        if returnval is not None and "store" not in func.flags:
            error(loc, "the assignment syntax is only valid for functions with prototypes")
        parameters_prime, argc_prime, append = parameters, argc, ""
    else:
        prototype = func.prototypes[overload_idx]
        rvpos, argcmod = -1, 0
        for i, param_def in enumerate(prototype):
            pflags = param_def[1]  # Safe extraction instead of 2-tuple unpack
            if "return" in pflags: rvpos = i
            if "uncount" in pflags: argcmod += 1
            
        if rvpos == -1 and returnval in (None, "$\xc8"):
            parameters_prime, append = parameters, ""
        elif rvpos == -1 and returnval is not None:
            if "store" in func.flags:
                parameters_prime, append = parameters, f"{returnval}\\\x1e$\xc8"
            else:
                error(loc, f"the function '{func.ident}' does not return a value")
        elif returnval is None:
            error(loc, f"return value of function '{func.ident}' cannot be ignored")
        else:
            parameters_prime = parameters[:rvpos] + [("Unknown", returnval)] + parameters[rvpos:]
            append = ""
            
        argc_prime = argc - argcmod

    buf = []
    buf.append(codegen.code_of_opcode(func.op_type, func.op_module, func.op_code, argc_prime, overload_idx))
    if parameters_prime:
        buf.append("(")
        buf.append(parameters_to_string(parameters_prime, None))
        buf.append(")")
        
    return "".join(buf), append if append else None

def compile_function_str(loc: Location, func: ketypes.FuncDef, parameters: List[Any], overload: int = None, returnval: str = None) -> str:
    s, t = compile_function(loc, func, parameters, overload, returnval)
    return s if t is None else s + t
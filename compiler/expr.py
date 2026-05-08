import sys
import math
from typing import Any, Tuple, List, Optional
from . import ketypes
from .ketypes import *
from . import global_state
from . import memory
from . import codegen
from . import func_asm
from . import keast
from . import intrinsic
from . import function

class TransformAux:
    def __init__(self, expr: Any):
        self._id_counter = 0
        self.tempvars = {}
        self.pre_code = []
        self.redef_store = None
        self._expr = expr
        self._contains_store = None

    def get_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    @property
    def contains_store(self) -> bool:
        if self._contains_store is None:
            self._contains_store = keast.exists_in_expr(keast.is_store, self._expr)
        return self._contains_store

def prec(op: str) -> int:
    if op in ("Add", "Sub"): return 10
    if op in ("Mul", "Div", "Mod", "And", "Or", "Xor", "Shl", "Shr"): return 20
    raise ValueError(f"Unknown arith_op for precedence: {op}")

def to_signed_32(n: int) -> int:
    n = n & 0xFFFFFFFF
    return (n ^ 0x80000000) - 0x80000000

def apply_arith(a: int, b: int, op: str) -> int:
    if op == "Add": res = a + b
    elif op == "Sub": res = a - b
    elif op == "Mul": res = a * b
    elif op == "Div": res = int(a / b) if b != 0 else 0
    elif op == "Mod": res = int(math.fmod(a, b)) if b != 0 else 0
    elif op == "And": res = a & b
    elif op == "Or": res = a | b
    elif op == "Xor": res = a ^ b
    elif op == "Shl": res = a << b
    elif op == "Shr": res = a >> b
    else: raise ValueError(f"Unknown arith_op: {op}")
    return to_signed_32(res)

def apply_unary(i: int, op: str) -> int:
    if op == "Sub": res = -i
    elif op == "Not": res = 1 if i == 0 else 0
    elif op == "Inv": res = ~i
    else: raise ValueError(f"Unknown unary_op: {op}")
    return to_signed_32(res)

def apply_cond(a: int, b: int, op: str) -> int:
    res = False
    if op == "Equ": res = (a == b)
    elif op == "Neq": res = (a != b)
    elif op == "Ltn": res = (a < b)
    elif op == "Lte": res = (a <= b)
    elif op == "Gtn": res = (a > b)
    elif op == "Gte": res = (a >= b)
    return 1 if res else 0

def reverse_cond(op: str) -> str:
    mapping = {"Equ": "Neq", "Neq": "Equ", "Ltn": "Gte", "Lte": "Gtn", "Gtn": "Lte", "Gte": "Ltn"}
    return mapping[op]

def expr_disambiguate(elt: Any) -> Any:
    if elt[0] == "VarOrFn":
        loc, s, t = elt[1], elt[2], elt[3]
        if not memory.defined(t):
            if intrinsic.is_builtin(t):
                return intrinsic.eval_as_expr((loc, s, t, [], None))
            else:
                try:
                    ketypes.ver_fun("", [ketypes.functions[t]] if t in ketypes.functions else [])
                    return ("Func", loc, s, t, [], None)
                except Exception:
                    error(loc, f"undeclared identifier[1] '{s}'")
        else:
            return memory.get_as_expression(t, loc=loc, s=s)
            
    elif elt[0] == "Deref":
        loc, s, t, offset = elt[1], elt[2], elt[3], elt[4]
        if not memory.defined(t):
            if intrinsic.is_builtin(t) or t in ketypes.functions:
                error(loc, f"'{s}' is not an array")
            else:
                error(loc, f"undeclared identifier[2] '{s}'")
        else:
            return memory.get_deref_as_expression(t, offset, loc=loc, s=s)
            
    elif elt[0] == "Func":
        loc, s, t, parms, label = elt[1], elt[2], elt[3], elt[4], elt[5]
        assert memory.defined(t) or intrinsic.is_builtin(t)
        assert label is None
        if memory.defined(t):
            def mf(p):
                if p[0] == "Simple": return p[2]
                error(p[1], "expected expression as parameter to inline expansion")
            return memory.get_as_expression(t, loc=loc, s=s, args=[mf(p) for p in parms])
        else:
            return intrinsic.eval_as_expr((loc, s, t, parms, None))
            
    raise ValueError(f"expr_disambiguate: unhandled node {elt[0]}")

global_state.expr__disambiguate = expr_disambiguate

def map_func_param(f, aux, param):
    if param[0] == "Simple": return ("Simple", param[1], f(aux, param[2]))
    if param[0] == "Complex": return ("Complex", param[1], [f(aux, p) for p in param[2]])
    if param[0] == "Special": return ("Special", param[1], param[2], [f(aux, p) for p in param[3]])

def map_sel_param(f, aux, param):
    if param[0] == "Always": return ("Always", param[1], f(aux, param[2]))
    if param[0] == "Special":
        mapped_cl = []
        for spec in param[2]:
            if spec[0] == "Flag": mapped_cl.append(spec)
            elif spec[0] == "NonCond": mapped_cl.append(("NonCond", spec[1], spec[2], spec[3], f(aux, spec[4])))
            elif spec[0] == "Cond": mapped_cl.append(("Cond", spec[1], spec[2], spec[3], f(aux, spec[4]) if spec[4] else None, f(aux, spec[5])))
        return ("Special", param[1], mapped_cl, f(aux, param[3]))

def unary_to_logop(l: Location, e: Any) -> Any:
    if e[0] == "LogOp": return ("LogOp", e[1], e[2], reverse_cond(e[3]), e[4])
    if e[0] == "Unary" and e[2] == "Not": return conditional_unit(e[3])
    return ("LogOp", l, e, "Equ", ("Int", l, 0))

def conditional_unit(e: Any) -> Any:
    if e[0] in ("LogOp", "AndOr"): return e
    if e[0] == "Unary" and e[2] == "Not": return unary_to_logop(e[1], conditional_unit(e[3]))
    if e[0] == "Parens": return ("Parens", e[1], conditional_unit(e[2]))
    if e[0] in ("VarOrFn", "Deref", "Func"):
        t = e[3] if e[0] == "VarOrFn" else e[3]
        if memory.defined(t) or intrinsic.is_builtin(t):
            return conditional_unit(expr_disambiguate(e))
    l = keast.loc_of_expr(e)
    return ("LogOp", l, e, "Neq", ("Int", l, 0))

def last_store_ref(aux: TransformAux) -> Optional[int]:
    c = aux.pre_code
    n = len(c) - 1
    while n >= 0:
        _, cmd = c[n]
        if cmd[0] == "FuncCall" and cmd[1] is not None and cmd[1][0] == "Store": return n
        if cmd[0] == "Select" and cmd[1][0] == "Store": return n
        n -= 1
    return None

def add_store_func(aux: TransformAux, last_ref: Optional[int], loc: Location, rv: Any) -> Any:
    if last_ref is None:
        if aux.contains_store:
            ti = memory.get_temp_int()
            assert aux.redef_store is None
            aux.redef_store = ti
    else:
        tv = memory.get_temp_int()
        id_, cmd = aux.pre_code[last_ref]
        aux.tempvars[id_] = tv
        if cmd[0] == "FuncCall":
            aux.pre_code[last_ref] = (id_, ("FuncCall", cmd[1], tv, cmd[3], cmd[4], cmd[5], cmd[6]))
        elif cmd[0] == "Select":
            aux.pre_code[last_ref] = (id_, ("Select", cmd[1], tv, cmd[3], cmd[4], cmd[5], cmd[6]))
            
    id_ = aux.get_id()
    aux.pre_code.append((id_, rv))
    aux.tempvars[id_] = ("Store", memory.temploc)
    return ("ExFunc", loc, id_)

def add_int_of_conditional(aux: TransformAux, cond: Any) -> Any:
    tv = memory.get_temp_int()
    lb = codegen.unique_label(nowhere)
    aux.pre_code.append((-1, ("Assign", nowhere, tv, "Set", ("Int", nowhere, 0))))
    aux.pre_code.append((-1, ("ProcCall", nowhere, "goto_unless", "goto_unless", [("Simple", nowhere, cond)], lb)))
    aux.pre_code.append((-1, ("Assign", nowhere, tv, "Set", ("Int", nowhere, 1))))
    aux.pre_code.append((-1, ("Label", lb)))
    return tv

# Recursive Transformation

def transform(e: Any, reject: str, as_cond: bool = False) -> Tuple[Any, TransformAux]:
    aux = TransformAux(e)
    res = traverse(aux, conditional_unit(e) if as_cond else e, reject=reject, as_cond=as_cond)
    return res, aux

def traverse(aux: TransformAux, e: Any, reject: str, as_cond: bool = False, keep_unknown_funcs: bool = False) -> Any:
    ptype = e[0]
    
    if ptype == "Int":
        if reject == "Int": error(e[1], "type mismatch: integer in string expression")
        return e
        
    if ptype == "Store":
        if reject == "Int": error(e[1], "type mismatch: integer in string expression")
        return e
        
    if ptype == "Str":
        if reject == "Str": error(e[1], "type mismatch: string constant in integer expression")
        return ("IStr", e[1], traverse_str_tokens(aux, e[2]))
        
    if ptype == "Res":
        if reject == "Str": error(e[1], "type mismatch: #res<> in integer expression")
        t, l = global_state.get_resource(e[1], (e[2], e[2]))
        return traverse(aux, ("Str", l, t), reject=reject, as_cond=as_cond, keep_unknown_funcs=keep_unknown_funcs)
        
    if ptype == "Parens":
        inner = traverse(aux, e[2], reject=reject, as_cond=as_cond)
        if inner[0] in ("Store", "IStr", "Int", "IVar", "SVar", "ExFunc"): return inner
        if inner[0] == "Parens" or reject == "Int": return inner
        return ("Parens", e[1], inner)
        
    if ptype == "SVar":
        if reject == "Str": error(e[1], "type mismatch: string variable in integer expression")
        return ("SVar", e[1], e[2], traverse(aux, e[3], reject="Str"))
        
    if ptype == "IVar":
        if reject == "Int": error(e[1], "type mismatch: integer variable in string expression")
        return ("IVar", e[1], e[2], traverse(aux, e[3], reject="Str"))
        
    if ptype in ("Deref", "VarOrFn"):
        return traverse(aux, expr_disambiguate(e), reject=reject, as_cond=as_cond)
        
    if ptype == "Func":
        if memory.defined(e[3]) or intrinsic.is_builtin(e[3]):
            return traverse(aux, expr_disambiguate(e), reject=reject, as_cond=as_cond)
        return traverse_func(aux, e, reject=reject, keep_unknown_funcs=keep_unknown_funcs, as_cond=as_cond)
        
    if ptype == "Op":
        l, a, op, b = e[1], e[2], e[3], e[4]
        simple_a = traverse(aux, a, reject=reject)
        if keast.type_of_normalised_expr(simple_a) == "int":
            simple_b = traverse(aux, b, reject="Str")
            if op in ("Div", "Mod") and simple_b[0] == "Int" and simple_b[2] == 0:
                error(l, "division by zero")
                
            # Algebraic optimizations
            if op == "And" and (simple_b == ("Int", l, -1) or simple_a == ("Int", l, -1)):
                return simple_a if simple_b[0] == "Int" else simple_b
            if op in ("Or", "Xor") and (simple_b == ("Int", l, 0) or simple_a == ("Int", l, 0)):
                return simple_a if simple_b[0] == "Int" else simple_b
            if op in ("Add", "Sub") and simple_b == ("Int", l, 0): return simple_a
            if op == "Add" and simple_a == ("Int", l, 0): return simple_b
            if op in ("Mul", "Div") and simple_b == ("Int", l, 1): return simple_a
            if op == "Mul" and simple_a == ("Int", l, 1): return simple_b
            if op in ("And", "Mul") and (simple_b == ("Int", l, 0) or simple_a == ("Int", l, 0)): return ("Int", l, 0)
            if op in ("Div", "Mod") and simple_a == ("Int", l, 0): return ("Int", l, 0)
            
            if op in ("And", "Or") and keast.equal_exprs(simple_a, simple_b): return simple_a
            if op in ("Sub", "Xor", "Mod") and keast.equal_exprs(simple_a, simple_b): return ("Int", l, 0)
            if op == "Div" and keast.equal_exprs(simple_a, simple_b): return ("Int", l, 1)
            
            if simple_a[0] == "Int" and simple_b[0] == "Int":
                return ("Int", l, apply_arith(simple_a[2], simple_b[2], op))
                
            if op == "Add" and simple_b[0] == "Int" and simple_b[2] < 0:
                return ("Op", l, simple_a, "Sub", ("Int", simple_b[1], -simple_b[2]))
            if op == "Sub" and simple_b[0] == "Int" and simple_b[2] < 0:
                return ("Op", l, simple_a, "Add", ("Int", simple_b[1], -simple_b[2]))
            if op == "Add" and simple_b[0] == "Unary" and simple_b[2] == "Sub":
                return ("Op", l, simple_a, "Sub", simple_b[3])
            if op == "Sub" and simple_b[0] == "Unary" and simple_b[2] == "Sub":
                return ("Op", l, simple_a, "Add", simple_b[3])
            if op in ("Div", "Mul") and simple_a[0] == "Unary" and simple_a[2] == "Sub" and simple_b[0] == "Unary" and simple_b[2] == "Sub":
                return ("Op", l, simple_a[3], op, simple_b[3])
                
            pa = ("Parens", l, simple_a) if simple_a[0] == "Op" and prec(simple_a[3]) < prec(op) else simple_a
            pb = ("Parens", l, simple_b) if simple_b[0] == "Op" and prec(simple_b[3]) <= prec(op) else simple_b
            return ("Op", l, pa, op, pb)
        else:
            simple_b = traverse(aux, b, reject="Int")
            if op != "Add": error(l, f"invalid operator '{op}' in string expression")
            
            if simple_a[0] == "IStr" and simple_b[0] == "IStr":
                return ("IStr", l, simple_a[2] + simple_b[2])
            if simple_a[0] == "IStr" and not simple_a[2]: return simple_b
            if simple_b[0] == "IStr" and not simple_b[2]: return simple_a
            
            if simple_a[0] == "SChain" and simple_b[0] == "SChain": return ("SChain", l, simple_a[2] + simple_b[2])
            if simple_b[0] == "SChain": return ("SChain", keast.loc_of_expr(simple_a), [simple_a] + simple_b[2])
            if simple_a[0] == "SChain": return ("SChain", l, simple_a[2] + [simple_b])
            return ("SChain", keast.loc_of_expr(simple_a), [simple_a, simple_b])
            
    if ptype == "LogOp":
        l, a, op, b = e[1], e[2], e[3], e[4]
        if reject == "Int": error(l, f"invalid operator '{op}' in string expression")
        simple_b = traverse(aux, b, reject="None")
        if keast.type_of_normalised_expr(simple_b) == "int":
            simple_a = traverse(aux, a, reject="Str")
            if simple_a[0] == "Int" and simple_b[0] == "Int":
                return ("Int", l, apply_cond(simple_a[2], simple_b[2], op))
            if op in ("Equ", "Gte", "Lte") and keast.equal_exprs(simple_a, simple_b): return ("Int", l, 1)
            if op in ("Neq", "Gtn", "Ltn") and keast.equal_exprs(simple_a, simple_b): return ("Int", l, 0)
            
            rv = ("LogOp", l, simple_a, op, simple_b)
            return rv if as_cond else add_int_of_conditional(aux, rv)
        else:
            simple_a = traverse(aux, a, reject="Int")
            tv = add_store_func(aux, last_store_ref(aux), nowhere, 
                ("FuncCall", nowhere, ("Store", nowhere), "strcmp", "strcmp", [("Simple", nowhere, simple_a), ("Simple", nowhere, simple_b)], None))
            if op == "Neq" and not as_cond: return tv
            rv = ("LogOp", l, tv, op, ("Int", nowhere, 0))
            return rv if as_cond else add_int_of_conditional(aux, rv)
            
    if ptype == "AndOr":
        l, a, op, b = e[1], e[2], e[3], e[4]
        if reject == "Int": error(l, f"invalid operator '{op}' in string expression")
        simple_a = traverse(aux, conditional_unit(a), reject="Str", as_cond=True)
        simple_b = traverse(aux, conditional_unit(b), reject="Str", as_cond=True)
        
        def ret(rv):
            if rv[0] in ("LogOp", "AndOr") and not as_cond: return add_int_of_conditional(aux, rv)
            return rv
            
        if op == "LAnd" and simple_a[0] == "Int" and simple_b[0] == "Int":
            return ("Int", l, 1 if simple_a[2] != 0 and simple_b[2] != 0 else 0)
        if op == "LAnd" and ((simple_b[0] == "Int" and simple_b[2] != 0) or (simple_a[0] == "Int" and simple_a[2] != 0)):
            return ret(simple_a if simple_b[0] == "Int" else simple_b)
        if op == "LAnd" and ((simple_b[0] == "Int" and simple_b[2] == 0) or (simple_a[0] == "Int" and simple_a[2] == 0)):
            return ("Int", l, 0)
            
        if op == "LOr" and simple_a[0] == "Int" and simple_b[0] == "Int":
            return ("Int", l, 1 if simple_a[2] != 0 or simple_b[2] != 0 else 0)
        if op == "LOr" and ((simple_b[0] == "Int" and simple_b[2] == 0) or (simple_a[0] == "Int" and simple_a[2] == 0)):
            return ret(simple_a if simple_b[0] == "Int" else simple_b)
        if op == "LOr" and ((simple_b[0] == "Int" and simple_b[2] != 0) or (simple_a[0] == "Int" and simple_a[2] != 0)):
            return ("Int", l, 1)
            
        if keast.equal_exprs(simple_a, simple_b): return ret(simple_a)
        
        pa = ("Parens", l, simple_a) if simple_a[0] == "AndOr" and simple_a[3] == "LAnd" and op == "LOr" else simple_a
        pb = ("Parens", l, simple_b) if simple_b[0] == "AndOr" and op == "LOr" else simple_b
        return ret(("AndOr", l, pa, op, pb))

    if ptype == "Unary":
        l, op, inner = e[1], e[2], e[3]
        if reject == "Int": error(l, f"invalid operator '{op}' in string expression")
        simple_inner = traverse(aux, inner, reject="Str")
        if simple_inner[0] == "Int": return ("Int", l, apply_unary(simple_inner[2], op))
        if simple_inner[0] == "Unary" and simple_inner[2] == op: return simple_inner[3]
        if op == "Sub":
            return ("Unary", l, "Sub", ("Parens", l, simple_inner) if simple_inner[0] == "Op" else simple_inner)
        if op == "Inv":
            inner_mod = ("Parens", l, simple_inner) if simple_inner[0] == "Op" and prec(simple_inner[3]) < prec("Xor") else simple_inner
            return ("Op", l, inner_mod, "Xor", ("Int", l, -1))
        if op == "Not" and simple_inner[0] == "Unary" and simple_inner[2] == "Sub":
            simple_inner = simple_inner[3]
        if op == "Not":
            rv = ("LogOp", l, simple_inner, "Equ", ("Int", l, 0))
            return rv if as_cond else add_int_of_conditional(aux, rv)

    if ptype == "ExprSeq":
        l, id_, defs, smts = e[1], e[2], e[3], e[4]
        if not smts: error(l, f"inline block '{id_}' expands to empty sequence: this is invalid in expressions")
        last = smts[-1]
        smts_body = smts[:-1]
        assert memory.defined(id_)
        sym = memory.pull_sym(id_)
        memory.open_scope()
        memory.define("__INLINE_CALL__", ("Macro", ("Int", nowhere, 1)), scoped=True)
        memory.define("__CALLER_FILE__", ("Macro", ("Str", nowhere, [("Text", nowhere, "Sbcs", l.file)])), scoped=True)
        memory.define("__CALLER_LINE__", ("Macro", ("Int", nowhere, l.line)), scoped=True)
        for i, ex in defs: memory.define(i, ("Macro", ex), scoped=True)
        
        from . import meta
        meta.parse(smts_body)
        rv = traverse(aux, keast.expr_of_statement(last), reject=reject, as_cond=as_cond, keep_unknown_funcs=keep_unknown_funcs)
        memory.close_scope()
        memory.replace_sym(id_, sym)
        return rv

    if ptype == "SelFunc":
        l, s_ident, opcode, window, params = e[1], e[2], e[3], e[4], e[5]
        if reject == "Int": error(l, f"type mismatch: function '{s_ident}' returns an integer, but is here used in a string expression")
        last_ref = last_store_ref(aux)
        w = traverse(aux, window, reject="Str") if window is not None else None
        
        p_mapped = []
        for p in params:
            if p[0] == "Always":
                p_mapped.append(("Always", p[1], traverse(aux, p[2], reject="Int")))
            elif p[0] == "Special":
                ll, cl, ev = p[1], p[2], p[3]
                mapped_cl = []
                for spec in cl:
                    if spec[0] == "Flag": mapped_cl.append(spec)
                    elif spec[0] == "NonCond": mapped_cl.append(("NonCond", spec[1], spec[2], spec[3], traverse(aux, spec[4], reject="Str")))
                    elif spec[0] == "Cond": mapped_cl.append(("Cond", spec[1], spec[2], spec[3], traverse(aux, spec[4], reject="Str") if spec[4] else None, traverse(aux, conditional_unit(spec[5]), reject="Str", as_cond=True)))
                p_mapped.append(("Special", ll, mapped_cl, traverse(aux, ev, reject="Int")))
        return add_store_func(aux, last_ref, l, ("Select", l, ("Store", nowhere), s_ident, opcode, w, p_mapped))

    return e

def traverse_str_tokens(aux: TransformAux, tkns: List[Any]) -> List[Any]:
    rv = []
    for tkn in tkns:
        if tkn[0] == "Code":
            id_ = tkn[2]
            p = tkn[4]
            args = [map_func_param(lambda a, e: traverse(a, e, reject="None"), aux, param) for param in p]
            rv.append(("Code", tkn[1], tkn[2], None if tkn[3] is None else traverse(aux, tkn[3], reject="Str"), args))
        elif tkn[0] == "Gloss":
            l, gtype, base, gloss = tkn[1], tkn[2], tkn[3], tkn[4]
            if gloss[0] == "Closed":
                gloss_loc, gloss_tokens = gloss[1], gloss[2]
            elif gloss[0] == "ResStr":
                gloss_tokens, gloss_loc = global_state.get_resource(gloss[1], (gloss[2], gloss[2]))
            else:
                raise AssertionError(f"unknown gloss node {gloss!r}")
            rv.append(("Gloss", l, gtype, traverse_str_tokens(aux, base), ("Closed", gloss_loc, traverse_str_tokens(aux, gloss_tokens))))
        elif tkn[0] == "Name":
            rv.append(("Name", tkn[1], tkn[2], traverse(aux, tkn[3], reject="Str"), None if tkn[4] is None else traverse(aux, tkn[4], reject="Str")))
        else:
            rv.append(tkn)
    return rv

def traverse_func(aux: TransformAux, e: Any, reject: str, keep_unknown_funcs: bool = False, as_cond: bool = False) -> Any:
    l, s, t, p, label = e[1], e[2], e[3], e[4], e[5]
    try:
        fdef = ketypes.functions.get(t)
        f = ketypes.ver_fun("", [fdef] if fdef is not None else [])
    except Exception:
        if keep_unknown_funcs: return ("Func", l, s, t, [map_func_param(lambda a, px: traverse(a, px, reject="None"), aux, param) for param in p], label)
        error(l, f"unable to find an appropriate definition for the function '{s}'")
        
    argc = len(p) + (0 if "store" in f.flags else 1)
    overload = func_asm.choose_overload(l, f, argc)
    return_as = ketypes.function_type(f)
    if return_as == "int" and reject == "Int": error(l, f"type mismatch: function '{s}' returns an integer, but is here used in a string expression")
    
    last_ref = last_store_ref(aux)
    p_mapped = [map_func_param(lambda a, px: traverse(a, px, reject="None", as_cond=as_cond, keep_unknown_funcs=True), aux, param) for param in p]
    
    if return_as == "store":
        return add_store_func(aux, last_ref, l, ("FuncCall", l, ("Store", nowhere), s, t, p_mapped, label))
    elif return_as == "int":
        id_ = aux.get_id()
        if last_ref is None and not aux.contains_store:
            aux.tempvars[id_] = ("Store", memory.temploc)
            tv, rv = ("Store", memory.temploc), ("ExFunc", l, id_)
        else:
            tv = memory.get_temp_int()
            rv = tv
        aux.pre_code.append((id_, ("FuncCall", l, tv, s, t, p_mapped, label)))
        return rv
    else:
        tv = memory.get_temp_str()
        aux.pre_code.append((-1, ("FuncCall", l, tv, s, t, p_mapped, label)))
        return tv

def finalise(aux: TransformAux, expr: Any) -> Any:
    ptype = expr[0]
    if ptype == "Store": return aux.redef_store if aux.redef_store else expr
    if ptype == "Int": return expr
    if ptype == "IStr": return ("Str", expr[1], [finalise_str_tokens(aux, t) for t in expr[2]])
    if ptype == "IVar": return ("IVar", expr[1], expr[2], finalise(aux, expr[3]))
    if ptype == "SVar": return ("SVar", expr[1], expr[2], finalise(aux, expr[3]))
    if ptype == "Parens": return ("Parens", expr[1], finalise(aux, expr[2]))
    if ptype == "Op": return ("Op", expr[1], finalise(aux, expr[2]), expr[3], finalise(aux, expr[4]))
    if ptype == "LogOp": return ("LogOp", expr[1], finalise(aux, expr[2]), expr[3], finalise(aux, expr[4]))
    if ptype == "AndOr": return ("AndOr", expr[1], finalise(aux, expr[2]), expr[3], finalise(aux, expr[4]))
    if ptype == "Unary": return ("Unary", expr[1], expr[2], finalise(aux, expr[3]))
    if ptype == "Func": return ("Func", expr[1], expr[2], expr[3], [map_func_param(finalise, aux, p) for p in expr[4]], expr[5])
    if ptype == "ExFunc": return aux.tempvars[expr[2]]
    if ptype == "SChain":
        l, chain = expr[1], expr[2]
        s = []
        for ch in chain:
            if ch[0] == "IStr": s.extend([finalise_str_tokens(aux, t) for t in ch[2]])
            elif ch[0] == "SVar": s.append(("Code", l, "s", None, [("Simple", l, ("SVar", l, ch[2], finalise(aux, ch[3])))]))
            else: error(l, "expected string")
        return ("Str", l, s)
    return expr

def finalise_str_tokens(aux: TransformAux, tkn: Any) -> Any:
    if tkn[0] == "Code":
        return ("Code", tkn[1], tkn[2], None if tkn[3] is None else finalise(aux, tkn[3]), [map_func_param(finalise, aux, p) for p in tkn[4]])
    if tkn[0] == "Gloss":
        return ("Gloss", tkn[1], tkn[2], [finalise_str_tokens(aux, tk) for tk in tkn[3]], ("Closed", tkn[4][1], [finalise_str_tokens(aux, tk) for tk in tkn[4][2]]))
    if tkn[0] == "Name":
        return ("Name", tkn[1], tkn[2], finalise(aux, tkn[3]), None if tkn[4] is None else finalise(aux, tkn[4]))
    return tkn

def finalise_generated_code(aux: TransformAux, code: Any) -> Any:
    _, s = code
    if s[0] == "Assign": return ("Assign", s[1], s[2], s[3], finalise(aux, s[4]))
    if s[0] == "ProcCall": return ("FuncCall", s[1], None, s[2], s[3], [map_func_param(finalise, aux, p) for p in s[4]], s[5])
    if s[0] == "FuncCall": return ("FuncCall", s[1], s[2], s[3], s[4], [map_func_param(finalise, aux, p) for p in s[5]], s[6])
    if s[0] == "Select": return ("Select", s[1], s[2], s[3], s[4], s[5] if s[5] is None else finalise(aux, s[5]), [map_sel_param(finalise, aux, p) for p in s[6]])
    return s

def normalise_funccall(stmt: Any) -> List[Any]:
    l, dest, s_ident, t_ident, params, label = stmt[1], stmt[2], stmt[3], stmt[4], stmt[5], stmt[6]
    
    if params and params[0][0] == "Simple" and isinstance(params[0][2], tuple) and params[0][2][0] == "VarOrFn":
        fake_tag = params[0][2][2].upper()
        possible_target = f"{s_ident}_{fake_tag}"
        if possible_target.lower() in ketypes.functions:
            s_ident = possible_target
            t_ident = s_ident
            params = params[1:]
            
    aux = TransformAux(("Func", l, s_ident, t_ident, params, label))
    
    try:
        def_op = function.get_func_def(t_ident, params)
        as_cond = "cond" in def_op.flags
    except Exception:
        as_cond = False
        
    p_cond = [("Simple", p[1], conditional_unit(p[2])) if as_cond and p[0] == "Simple" else p for p in params]
    p_mapped = [map_func_param(lambda a, px: traverse(a, px, reject="None", as_cond=as_cond, keep_unknown_funcs=True), aux, param) for param in p_cond]
    
    aux.pre_code.append((-1, ("ProcCall", l, s_ident, t_ident, p_mapped, label)))
    
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
    return d

def normalise_unknown(stmt: Any) -> List[Any]:
    l, def_op, overload, params = stmt[1], stmt[2], stmt[3], stmt[4]
    aux = TransformAux(("Store", nowhere))
    aux._contains_store = True 
    
    p_mapped = [map_func_param(lambda a, px: traverse(a, px, reject="None", keep_unknown_funcs=True), aux, param) for param in params]
    p_fin = [map_func_param(finalise, aux, param) for param in p_mapped]
    
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
    d.append(("UnknownOp", l, def_op, overload, p_fin))
    return d

def normalise_select(stmt: Any) -> List[Any]:
    l, dest, s_ident, opcode, window, params = stmt[1], stmt[2], stmt[3], stmt[4], stmt[5], stmt[6]
    aux = TransformAux(("SelFunc", l, s_ident, opcode, window, params))
    
    w = traverse(aux, window, reject="Str") if window is not None else None
    
    p_mapped = []
    for p in params:
        if p[0] == "Always":
            p_mapped.append(("Always", p[1], traverse(aux, p[2], reject="Int")))
        elif p[0] == "Special":
            ll, cl, e = p[1], p[2], p[3]
            mapped_cl = []
            for spec in cl:
                if spec[0] == "Flag": mapped_cl.append(spec)
                elif spec[0] == "NonCond": mapped_cl.append(("NonCond", spec[1], spec[2], spec[3], traverse(aux, spec[4], reject="Str")))
                elif spec[0] == "Cond": mapped_cl.append(("Cond", spec[1], spec[2], spec[3], traverse(aux, spec[4], reject="Str") if spec[4] else None, traverse(aux, conditional_unit(spec[5]), reject="Str", as_cond=True)))
            p_mapped.append(("Special", ll, mapped_cl, traverse(aux, e, reject="Int")))
            
    aux.pre_code.append((-1, ("Select", l, dest, s_ident, opcode, w, p_mapped)))
    
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
    return d

def normalise_gotocase(stmt: Any) -> List[Any]:
    l, jump_type, e, cases = stmt[1], stmt[2], stmt[3], stmt[4]
    aux = TransformAux(("Store", nowhere))
    aux._contains_store = True
    
    e_trav = traverse(aux, e, reject="Str")
    cases_trav = []
    for c in cases:
        if c[0] == "Default": cases_trav.append(c)
        elif c[0] == "Match": cases_trav.append(("Match", traverse(aux, c[1], reject="Str"), c[2]))
        
    e_fin = finalise(aux, e_trav)
    if e_fin[0] == "Parens": e_fin = e_fin[2]
    
    cases_fin = []
    for c in cases_trav:
        if c[0] == "Default": cases_fin.append(c)
        elif c[0] == "Match":
            fin_m = finalise(aux, c[1])
            if fin_m[0] == "Parens": fin_m = fin_m[2]
            cases_fin.append(("Match", fin_m, c[2]))
            
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
    d.append(("GotoCase", l, jump_type, e_fin, cases_fin))
    return d

def normalise_nonassignment(s: Any) -> List[Any]:
    if s[0] == "GotoOn": e, aux = transform(s[3], reject="Str")
    elif s[0] == "Return": e, aux = transform(s[3], reject="None")
    elif s[0] == "LoadFile": e, aux = transform(s[2], reject="Int")
    elif s[0] == "Directive": 
        tp = s[3]
        rej = "Int" if tp == "Str" else "Str" if tp == "Int" else "None"
        e, aux = transform(s[4], reject=rej)
    elif s[0] == "DConst": e, aux = transform(s[5], reject="None")
    else: raise ValueError(f"Unhandled nonassignment {s[0]}")
    
    e_fin = finalise(aux, e)
    if e_fin[0] == "Parens": e_fin = e_fin[2]
    
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
        
    if s[0] == "GotoOn": d.append(("GotoOn", s[1], s[2], e_fin, s[4]))
    elif s[0] == "Return": d.append(("Return", s[1], s[2], e_fin))
    elif s[0] == "LoadFile": d.append(("LoadFile", s[1], e_fin))
    elif s[0] == "Directive": d.append(("Directive", s[1], s[2], s[3], e_fin))
    elif s[0] == "DConst": d.append(("Define", s[1], s[2], s[3], s[4] == "Bind", e_fin))
    return d

def normalise_assignment(assign: Any) -> List[Any]:
    loc, dest, op, e = assign[1], assign[2], assign[3], assign[4]
    
    # Dest disambiguation logic
    def disambiguate_dest(dst):
        if dst[0] in ("Store", "IVar"): return dst, True, "Str"
        if dst[0] == "SVar": return dst, False, "Int"
        if dst[0] == "Func" and intrinsic.is_builtin(dst[3]):
            return disambiguate_dest(intrinsic.eval_as_expr((dst[1], dst[2], dst[3], dst[4], dst[5])))
        if dst[0] == "Deref":
            try:
                return disambiguate_dest(memory.get_deref_as_expression(dst[3], dst[4], loc=dst[1], s=dst[2]))
            except KeyError:
                error(dst[1], f"undeclared identifier[3] '{dst[2]}'")
        if dst[0] == "VarOrFn":
            t = dst[3]
            if intrinsic.is_builtin(t):
                return disambiguate_dest(intrinsic.eval_as_expr((dst[1], dst[2], t, [], None)))
            if memory.defined(t):
                return disambiguate_dest(memory.get_as_expression(t, loc=dst[1], s=dst[2]))
            error(dst[1], f"undeclared identifier[4] '{dst[2]}'")
        error(loc, "left-hand side of assignment must be a variable")
        
    dest_norm_dest, is_int, reject = disambiguate_dest(dest)
    dest = dest_norm_dest
    
    e_norm, aux = transform(e, reject=reject)
    dest_norm = traverse(aux, dest, reject=reject)
    
    e_fin = finalise(aux, e_norm)
    if e_fin[0] == "Parens": e_fin = e_fin[2]
    
    d = [finalise_generated_code(aux, c) for c in aux.pre_code]
    if aux.redef_store:
        d.insert(0, ("Assign", nowhere, aux.redef_store, "Set", ("Store", nowhere)))
        
    if is_int:
        if e_fin[0] == "Store" and d and d[-1][0] == "Assign" and d[-1][2][0] == "Store" and d[-1][3] == "Set":
            d[-1] = ("Assign", loc, dest_norm, op, d[-1][4])
        elif e_fin[0] == "Store" and d and d[-1][0] == "FuncCall" and op == "Set" and d[-1][2] is not None and d[-1][2][0] == "Store":
            d[-1] = ("FuncCall", d[-1][1], dest_norm, d[-1][3], d[-1][4], d[-1][5], d[-1][6])
        elif e_fin[0] == "Store" and d and d[-1][0] == "Select" and op == "Set" and d[-1][2][0] == "Store":
            d[-1] = ("Select", d[-1][1], dest_norm, d[-1][3], d[-1][4], d[-1][5], d[-1][6])
        elif e_fin[0] == "Store" and op == "Set" and keast.is_store(dest_norm):
            pass
        elif op == "Set" and keast.equal_exprs(e_fin, dest_norm):
            pass
        else:
            if e_fin[0] == "Op" and keast.equal_exprs(e_fin[2], dest_norm):
                d.append(("Assign", loc, dest_norm, e_fin[3], e_fin[4]))
            else:
                d.append(("Assign", loc, dest_norm, op, e_fin))
    else:
        if e_fin[0] == "SVar" and d and d[-1][0] == "FuncCall" and op == "Set" and d[-1][2] is not None and d[-1][2][0] == "SVar":
            if e_fin[1] == memory.temploc and e_fin[1] == d[-1][2][1]:
                d[-1] = ("FuncCall", d[-1][1], dest_norm, d[-1][3], d[-1][4], d[-1][5], d[-1][6])
                return d
                
        e_str, new_op = e_fin, op
        if e_fin[0] == "Str" and len(e_fin[2]) > 1:
            tempvar = None
            chop = False
            
            def check_and_map(p):
                nonlocal tempvar
                if p[0] == "Simple" and keast.equal_exprs(p[2], dest_norm):
                    if tempvar is None: tempvar = memory.get_temp_str(useloc=p[1])
                    return ("Simple", p[1], tempvar)
                return p
                
            ntext = []
            for tk in e_fin[2]:
                if tk[0] == "Code":
                    ntext.append(("Code", tk[1], tk[2], tk[3], [check_and_map(p) for p in tk[4]]))
                else:
                    ntext.append(tk)
                    
            if op == "Set" and e_fin[2][0][0] == "Code" and len(e_fin[2][0][4]) == 1 and e_fin[2][0][4][0][0] == "Simple" and keast.equal_exprs(e_fin[2][0][4][0][2], dest_norm):
                ntext.pop(0)
                chop = True
                
            if tempvar is not None:
                d.insert(0, ("FuncCall", loc, None, "strcpy", "strcpy", [("Simple", loc, tempvar), ("Simple", loc, dest_norm)], None))
                
            e_str, new_op = ("Str", loc, ntext), ("Add" if chop else op)
            
        if new_op == "Set":
            if not keast.equal_exprs(dest_norm, e_str):
                d.append(("FuncCall", loc, None, "strcpy", "strcpy", [("Simple", loc, dest_norm), ("Simple", loc, e_str)], None))
        elif new_op == "Add":
            d.append(("FuncCall", loc, None, "strcat", "strcat", [("Simple", loc, dest_norm), ("Simple", loc, e_str)], None))
        else:
            error(loc, f"assignment operator '{string_of_assign_op(new_op)}' is not valid for strings")

    return d

def normalise(stmt: Any) -> Any:
    def call(f, e):
        memory.open_scope()
        m = f(e)
        if not m:
            memory.close_scope()
            return ("Nothing",)
        return ("Multiple", m)
        
    if stmt[0] == "Assign": return call(normalise_assignment, stmt)
    elif stmt[0] == "FuncCall":
        l, dest, s, t, p, d = stmt[1], stmt[2], stmt[3], stmt[4], stmt[5], stmt[6]
        if dest is None or (isinstance(dest, tuple) and dest[0] == "Store"):
            return call(normalise_funccall, stmt)
        else:
            return call(normalise_assignment, ("Assign", l, dest, "Set", ("Func", l, s, t, p, d)))
    elif stmt[0] == "UnknownOp": return call(normalise_unknown, stmt)
    elif stmt[0] == "GotoCase": return call(normalise_gotocase, stmt)
    elif stmt[0] == "Select": return call(normalise_select, stmt)
    elif stmt[0] == "DConst" and stmt[4] in ("Bind", "EBind"):
        return call(normalise_nonassignment, stmt)
    elif stmt[0] in ("GotoOn", "Return", "LoadFile", "Directive"):
        return call(normalise_nonassignment, stmt)
    return ("Single", stmt)

def normalise_and_get_const(e: Any, expect: str = "none", abort_on_fail: bool = True) -> Any:
    e_norm, aux = transform(e, reject="None")
    if aux.pre_code:
        if abort_on_fail: error(nowhere, "expected constant, found variable expression")
        raise Exception()
    return keast.const_of_normalised_expr(finalise(aux, e_norm), abort_on_fail=abort_on_fail, expect=expect)

def normalise_and_get_int(e: Any, abort_on_fail: bool = True) -> int:
    res = normalise_and_get_const(e, expect="int", abort_on_fail=abort_on_fail)
    if res[0] == "Integer":
        return res[1]
    raise AssertionError()

def normalise_and_get_str(e: Any, abort_on_fail: bool = True) -> Any:
    res = normalise_and_get_const(e, expect="str", abort_on_fail=abort_on_fail)
    if res[0] == "String":
        return res[1]
    raise AssertionError()

global_state.expr__normalise_and_get_const = normalise_and_get_const
global_state.expr__normalise_and_get_int = normalise_and_get_int
global_state.expr__normalise_and_get_str = normalise_and_get_str

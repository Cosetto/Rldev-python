from typing import Any
from . import ketypes
from .ketypes import *
from . import codegen
from . import keast

def special_case(compile_fn, loc: Location, s: str, id_: str, neg: bool, call: bool, params: list, label: Any) -> bool:
    param = params[0][2] if params[0][0] == "Simple" else None
    if not keast.normalised_expr_is_const(param):
        return False
        
    val = keast.int_of_normalised_expr(param)
    
    if (val == 0 and neg) or (val != 0 and not neg):
        ident = "gosub" if call else "goto"
        compile_fn(("FuncCall", loc, None, ident, ident, [], label))
        
    return True

def goto_on(tup: tuple):
    loc, (str_func, txt), expr, labels = tup[1], tup[2], tup[3], tup[4]
    func = ketypes.rlfun(str_func)
    
    codegen.Output.add_code(loc, f"{codegen.code_of_opcode(0, func.op_module, func.op_code, len(labels), 0)}({codegen.code_of_expr(expr)}){{")
    for lbl in labels:
        codegen.Output.add_ref(lbl)
    codegen.Output.add_code(nowhere, "}")

def goto_case(tup: tuple):
    loc, (str_func, txt), expr, cases = tup[1], tup[2], tup[3], tup[4]
    func = ketypes.rlfun(str_func)
    
    codegen.Output.add_code(loc, f"{codegen.code_of_opcode(0, func.op_module, func.op_code, len(cases), 0)}({codegen.code_of_expr(expr)}){{")
    
    for c in cases:
        if c[0] == "Default":
            codegen.Output.add_code(nowhere, "()")
            codegen.Output.add_ref(c[1])
        elif c[0] == "Match":
            codegen.Output.add_code(nowhere, f"({codegen.code_of_expr(c[1])})")
            codegen.Output.add_ref(c[2])
            
    codegen.Output.add_code(nowhere, "}")
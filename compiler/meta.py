from . import ketypes
from .ketypes import *
from . import global_state

def parse(d: list):
    global_state.compilerFrame__parse(d)

def parse_elt(e):
    parse([e])

def assign(lhs, op: str, rhs):
    # Determine if LHS and RHS are valid assignables/expressions
    parse_elt(("Assign", nowhere, lhs, op, rhs))

def call(funname: str, args: list, rv=None, label=None):
    mapped_args = [("Simple", nowhere, e) for e in args]
    parse_elt(("FuncCall", nowhere, rv, funname, funname, mapped_args, label))

zero = ("Int", nowhere, 0)
def int_val(x: int):
    return ("Int", nowhere, x)

def goto(label):
    call("goto", [], label=label)

def gosub(label):
    call("gosub", [], label=label)

def goto_unless(cond, label):
    call("goto_unless", [cond], label=label)
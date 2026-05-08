import sys
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple, List, Dict, Any

def str_of_int32(v: int) -> bytes:
    return struct.pack('<I', v & 0xFFFFFFFF)

def str_of_int(v: int) -> bytes:
    return struct.pack('<I', v & 0xFFFFFFFF)

def str16_of_int(v: int) -> bytes:
    return struct.pack('<H', v & 0xFFFF)

# Reporting functions
@dataclass(frozen=True)
class Location:
    file: str
    line: int

nowhere = Location("generated code", -1)

def cli_error(msg: str) -> None:
    sys.stderr.write(f"Error: {msg}\n")
    sys.exit(2)

def cli_warning(msg: str) -> None:
    sys.stderr.write(f"Warning: {msg}\n")

def cli_info(msg: str) -> None:
    sys.stdout.write(f"{msg}\n")

def error(where: Location, what: str) -> None:
    cli_error(f"({where.file} line {where.line}): {what}")

def warning(where: Location, what: str) -> None:
    cli_warning(f"({where.file} line {where.line}): {what}")

def info(where: Location, what: str) -> None:
    cli_info(f"{where.file} line {where.line}: {what}")

# Target settings
TargetT = str | Tuple[str, Callable[[Tuple[int, int, int, int]], bool]]

global_target: str = 'default'
global_version: Tuple[int, int, int, int] = (0, 0, 0, 0)
target_forced: bool = False
compiler_version: int = 10002

def target_t_of_string(s: str) -> str:
    s_lower = s.lower()
    if s_lower in ("reallive", "2"): return "reallive"
    if s_lower in ("avg2000", "1"): return "avg2000"
    if s_lower in ("kinetic", "3"): return "kinetic"
    cli_error(f"unknown target '{s}'")
    return "default"

def current_version() -> Tuple[int, int, int, int]:
    if global_version != (0, 0, 0, 0): return global_version
    if global_target == 'avg2000': return (1, 0, 0, 0)
    return (1, 2, 7, 0)

def current_version_string() -> str:
    i = "AVG2000" if global_target == 'avg2000' else "Kinetic" if global_target == 'kinetic' else "RealLive"
    v = current_version()
    if v[2] == 0 and v[3] == 0: return f"{i} {v[0]}.{v[1]}"
    if v[3] == 0: return f"{i} {v[0]}.{v[1]}.{v[2]}"
    return f"{i} {v[0]}.{v[1]}.{v[2]}.{v[3]}"

def has_goto_if() -> bool:
    return global_target != 'kinetic'

def ident_of_opcode(op_type: int, op_module: int, op_code: int, op_overload: int) -> str:
    return f"__op_{op_type}_{op_module}_{op_code}_{op_overload}"

@dataclass
class FuncDef:
    ident: str
    flags: List[str]
    op_type: int
    op_module: int
    op_code: int
    prototypes: List[Optional[List[Any]]]
    targets: List[TargetT]

functions: Dict[str, FuncDef] = {}
ctrlcodes: Dict[str, FuncDef] = {}
gotofuncs: List[Tuple[str, str]] = []
modules: Dict[str, int] = {}

def valid_opcode(f: FuncDef) -> bool:
    if not f.targets: return True
    interpreter = 'reallive' if global_target == 'default' else global_target
    c_ver = current_version()
    interpreters = []
    versions = []
    for t in f.targets:
        if isinstance(t, tuple) and t[0] == 'compare':
            versions.append(t[1])
        else:
            interpreters.append(t)
            
    if not all(func(c_ver) for func in versions): return False
    return (not interpreters) or (interpreter in interpreters)

def ver_fun(s: str, opts: List[FuncDef]) -> FuncDef:
    for opt in opts:
        if valid_opcode(opt): return opt
    if s:
        cli_error(f"the function '{s}' is not supported in {current_version_string()}")
    raise KeyError()

def rlfun(s: str) -> FuncDef:
    key = s.lower()
    opts = [functions[key]] if key in functions else []
    return ver_fun(s, opts)

def ccode(s: str) -> FuncDef:
    key = s.lower()
    opts = [ctrlcodes[key]] if key in ctrlcodes else []
    return ver_fun(s, opts)

def function_type(f: FuncDef) -> str:
    if "store" in f.flags: return "int"
    valid_protos = [p for p in f.prototypes if p is not None]
    if not valid_protos: return "none"
    proto = valid_protos[0]
    for param_type, pattrs in proto:
        if "return" in pattrs:
            if param_type in ("int", "intC", "intV", "Int", "IntC", "IntV"): return "int"
            if param_type in ("str", "strC", "strV", "res", "Str", "StrC", "StrV", "ResStr"): return "str"
            cli_error(f"error in reallive.kfn: invalid return type for function '{f.ident}'")
    return "none"

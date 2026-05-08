from typing import Dict, Tuple, Any, List, Callable
from .ketypes import Location, error

# Workaround for OCaml int32 padded string conversion
def int32_to_string_padded(width: int, value: int) -> str:
    s = str(value)
    d = width - len(s)
    return ('0' * d + s) if d > 0 else s

# Forward references for mutual recursion across modules
intrinsic__is_builtin: Callable[[str], bool] = lambda _: False
compilerFrame__parse: Callable[[List[Any]], None] = lambda _: None
expr__normalise_and_get_const: Callable[..., Any] = lambda *a, **kw: None
expr__disambiguate: Callable[[Any], Any] = lambda _: None

def expr__normalise_and_get_int(e: Any, abort_on_fail: bool = True) -> int:
    res = expr__normalise_and_get_const(e, expect="int", abort_on_fail=abort_on_fail)
    if res[0] == "Integer": return res[1]
    raise AssertionError()

def expr__normalise_and_get_str(e: Any, abort_on_fail: bool = True) -> Any:
    res = expr__normalise_and_get_const(e, expect="str", abort_on_fail=abort_on_fail)
    if res[0] == "String": return res[1]
    raise AssertionError()

# Header data
dramatis_personae: List[str] = []
val_0x2c: int = 0
kidoku_type: int = 0

# Rlc-style resources
resources: Dict[str, Tuple[List[Any], Location]] = {}
base_res: Dict[str, Tuple[List[Any], Location]] = {}

def get_resource(loc: Location, key_tuple: Tuple[str, str]) -> Tuple[List[Any], Location]:
    key, keyt = key_tuple
    keyt_norm = keyt.lower() 
    if keyt_norm in resources:
        return resources[keyt_norm]
    error(loc, f"undefined resource string '{key}'")

def get_base_resource(loc: Location, key_tuple: Tuple[str, str]) -> Tuple[List[Any], Location]:
    key, keyt = key_tuple
    keyt_norm = keyt.lower()
    if keyt_norm in base_res:
        return base_res[keyt_norm]
    error(loc, f"undefined base resource string '{key}'")

# Miscellaneous
_unique_src = -9223372036854775808 # Int64.min_int

def unique() -> int:
    global _unique_src
    rv = _unique_src
    _unique_src += 1
    return rv

gloss_count: int = 0

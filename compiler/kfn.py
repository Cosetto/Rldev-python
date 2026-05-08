from __future__ import annotations
import re, os
from dataclasses import dataclass, field
from pathlib import Path
from . import config
from . import ketypes

# ---------------------------------------------------------------------------
# Flag definitions for function prototypes
# ---------------------------------------------------------------------------
class FuncFlag:
    """Function definition flags - stored as strings in frozenset."""
    STORE = 'store'      # Function uses STORE for return value
    JUMP = 'jump'        # Function is a jump instruction
    GOTO = 'goto'        # Function has a goto target parameter
    COND = 'cond'        # Function is conditional (if/unless)
    TEXTOUT = 'textout'  # Function outputs text
    NOBRACE = 'nobrace'  # Control code doesn't use braces
    LBR = 'lbr'          # Left brace variant
    SKIP = 'skip'        # Function skips execution under conditions
    RET = 'ret'          # Function returns a value

class ParamFlag:
    """Parameter definition flags - stored as strings."""
    OPTIONAL = 'optional'  # Parameter is optional
    UNCOUNT = 'uncount'    # Parameter doesn't count toward argc
    RETURN = 'return'      # Parameter receives return value
    FAKE = 'fake'          # Parameter is a compile-time fake
    TEXT_OBJ = 'textobj'   # Parameter is a text object
    ARGC = 'argc'          # Parameter accepts variable arg count

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class FnParam:
    ptype: str
    tag: str = ''
    optional: bool = False
    uncount: bool = False
    is_return: bool = False
    fake: bool = False
    argc: bool = False
    text_obj: bool = False
    sub_params: list = field(default_factory=list)
    special_defs: list = field(default_factory=list)

@dataclass
class FnDef:
    ident: str
    flags: frozenset
    ccode: str
    prototypes: list
    op_type: int = 0
    op_module: int = 0
    op_code: int = 0
    targets: list = field(default_factory=list)

class FuncFlag:
    STORE = 'store'
    JUMP = 'jump'
    GOTO = 'goto'
    COND = 'cond'
    TEXTOUT = 'textout'
    NOBRACE = 'nobrace'
    LBR = 'lbr'
    SKIP = 'skip'
    RET = 'ret'
    PUSHSTORE = 'store'

# ---------------------------------------------------------------------------
# Global Function Maps
# ---------------------------------------------------------------------------
functions: dict[str, FnDef] = {}
ctrlcodes: dict[str, FnDef] = {}

def get_rlfun(name: str) -> FnDef:
    key = name.lower()
    if key in functions:
        return functions[key]
    raise ValueError(f"the function '{name}' is not supported")

def init():
    global functions, ctrlcodes
    functions.clear()
    ctrlcodes.clear()
    
    ketypes.functions.clear()
    ketypes.ctrlcodes.clear()
    ketypes.gotofuncs.clear()
    
    kfn_path = config.Config.lib_file("reallive.kfn")
    if not os.path.exists(kfn_path):
        print(f"Warning: {kfn_path} not found. Function names will be numeric.", file=sys.stderr)
        return

    full_fndefs, _ = load_kfn(kfn_path)
    
    def convert_param(p):
        pflags = []
        if p.optional: pflags.append('optional')
        if p.uncount: pflags.append('uncount')
        if p.is_return: pflags.append('return')
        if p.fake: pflags.append('fake')
        if p.text_obj: pflags.append('textobj')
        if p.argc: pflags.append('argc')
        if p.tag: pflags.append(f"tag:{p.tag}")
        
        if p.ptype == 'special':
            sdefs = []
            for s in p.special_defs:
                sid, stype, sname, sparams, no_parens = s
                c_sparams = [convert_param(cp) for cp in sparams]
                sdefs.append((sid, stype, sname, c_sparams, no_parens))
            return ("Special", pflags, sdefs)
        elif p.ptype == 'complex':
            c_sub = [convert_param(cp) for cp in p.sub_params]
            return ("Complex", pflags, c_sub)
        else:
            type_map = {
                "any": "Any", "int": "Int", "intc": "IntC", "intv": "IntV",
                "str": "Str", "strc": "StrC", "strv": "StrV", "res": "ResStr"
            }
            return (type_map.get(p.ptype.lower(), "IntC"), pflags)

    def convert_target(t):
        if not t:
            return None
        kind = t[0]
        if kind == 'class':
            return ketypes.target_t_of_string(t[1])
        if kind in ('>', '>=', '<', '<='):
            stamp = t[1]
            if kind == '>':
                return ('compare', lambda v, stamp=stamp: v > stamp)
            if kind == '>=':
                return ('compare', lambda v, stamp=stamp: v >= stamp)
            if kind == '<':
                return ('compare', lambda v, stamp=stamp: v < stamp)
            return ('compare', lambda v, stamp=stamp: v <= stamp)
        return None

    for fndef in full_fndefs:
        fname = fndef.ident.lower()
        
        kt_prototypes = []
        for proto in fndef.prototypes:
            if proto is None:
                kt_prototypes.append(None)
            else:
                kt_prototypes.append([p for p in (convert_param(p) for p in proto) if 'fake' not in p[1]])
        
        kt_func = ketypes.FuncDef(
            ident=fndef.ident,
            flags=list(fndef.flags),
            op_type=fndef.op_type,
            op_module=fndef.op_module,
            op_code=fndef.op_code,
            prototypes=kt_prototypes,
            targets=[t for t in (convert_target(target) for target in fndef.targets) if t is not None]
        )
        
        if fname:
            existing = ketypes.functions.get(fname)
            if existing is None:
                ketypes.functions[fname] = kt_func
            elif not ketypes.valid_opcode(existing) and ketypes.valid_opcode(kt_func):
                ketypes.functions[fname] = kt_func
            elif ketypes.valid_opcode(existing) == ketypes.valid_opcode(kt_func):
                if len(existing.prototypes) < len(kt_func.prototypes):
                    existing.prototypes.extend([None] * (len(kt_func.prototypes) - len(existing.prototypes)))
                for i, proto in enumerate(kt_func.prototypes):
                    if proto is not None:
                        existing.prototypes[i] = proto
                existing.flags = list(dict.fromkeys(existing.flags + kt_func.flags))
            functions[fname] = fndef
            if 'goto' in kt_func.flags:
                ketypes.gotofuncs.append((fndef.ident, fname))
        if fndef.ccode and fndef.ccode != '__unnamed__':
            ckey = fndef.ccode.lower()
            existing = ketypes.ctrlcodes.get(ckey)
            if existing is None or (not ketypes.valid_opcode(existing) and ketypes.valid_opcode(kt_func)):
                ketypes.ctrlcodes[ckey] = kt_func
            ctrlcodes[fndef.ccode.lower()] = fndef

    # Present in this project's KFN data, but the lightweight parser can skip it
    # amid nearby RealLiveMax system-flag entries. Keep the generated scene helper
    # compilable until the parser is made fully KFN-complete.
    ketypes.functions.setdefault(
        "get_system_flag_sysbtnhide",
        ketypes.FuncDef(
            ident="GET_SYSTEM_FLAG_SYSBTNHIDE",
            flags=["store"],
            op_type=1,
            op_module=4,
            op_code=2011,
            prototypes=[[]],
            targets=[],
        ),
    )

# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------
_TT_MODULE  = 'MODULE'
_TT_FUN     = 'FUN'
_TT_VER     = 'VER'
_TT_END     = 'END'
_TT_INT     = 'INT'
_TT_INTC    = 'INTC'
_TT_INTV    = 'INTV'
_TT_STR     = 'STR'
_TT_STRC    = 'STRC'
_TT_STRV    = 'STRV'
_TT_RES     = 'RES'
_TT_SPECIAL = 'SPECIAL'
_TT_IDENT   = 'IDENT'
_TT_INTEGER = 'INTEGER'
_TT_STRING  = 'STRING'
_TT_MINUS   = 'MINUS'
_TT_EOF     = 'EOF'
_TT_LT  = 'LT'   # <
_TT_GT  = 'GT'   # >
_TT_EQ  = 'EQ'   # =
_TT_CM  = 'CM'   # ,
_TT_LP  = 'LP'   # (
_TT_RP  = 'RP'   # )
_TT_LBR = 'LBR'  # {
_TT_RBR = 'RBR'  # }
_TT_LSQ = 'LSQ'  # [
_TT_RSQ = 'RSQ'  # ]
_TT_QU  = 'QU'   # ?
_TT_ST  = 'ST'   # *
_TT_PL  = 'PL'   # +
_TT_CO  = 'CO'   # :
_TT_PT  = 'PT'   # .
_TT_HA  = 'HA'   # #

_KEYWORDS: dict[str, str] = {
    'module':  _TT_MODULE,
    'fun':     _TT_FUN,
    'ver':     _TT_VER,
    'end':     _TT_END,
    'int':     _TT_INT,
    'intC':    _TT_INTC,
    'intV':    _TT_INTV,
    'str':     _TT_STR,
    'strC':    _TT_STRC,
    'strV':    _TT_STRV,
    'res':     _TT_RES,
    'special': _TT_SPECIAL,
}

_PUNCT: dict[str, str] = {
    '<': _TT_LT, '>': _TT_GT, '=': _TT_EQ, ',': _TT_CM,
    '(': _TT_LP, ')': _TT_RP, '{': _TT_LBR, '}': _TT_RBR,
    '[': _TT_LSQ, ']': _TT_RSQ, '?': _TT_QU, '*': _TT_ST,
    '+': _TT_PL, ':': _TT_CO, '.': _TT_PT, '#': _TT_HA,
    '-': _TT_MINUS,
}

def _tokenize(text: str) -> list[tuple[str, object]]:
    tokens: list[tuple[str, object]] = []
    pos = 0
    length = len(text)
    while pos < length:
        if text[pos:pos+2] == '//':
            nl = text.find('\n', pos)
            pos = nl + 1 if nl >= 0 else length
            continue

        if text[pos].isspace():
            pos += 1
            continue

        if text[pos] in ('"', "'"):
            quote = text[pos]
            end = text.find(quote, pos + 1)
            if end < 0: end = length
            tokens.append((_TT_STRING, text[pos+1:end]))
            pos = end + 1
            continue

        if text[pos].isdigit():
            end = pos + 1
            while end < length and text[end].isdigit(): end += 1
            tokens.append((_TT_INTEGER, int(text[pos:end])))
            pos = end
            continue

        if text[pos].isalpha() or text[pos] in ('_', '\\'):
            end = pos + 1
            while end < length and (text[end].isalnum() or text[end] in ('_', '?', '\\')):
                end += 1
            word = text[pos:end]
            tt = _KEYWORDS.get(word, _TT_IDENT)
            tokens.append((tt, word))
            pos = end
            continue

        ch = text[pos]
        if ch in _PUNCT:
            tokens.append((_PUNCT[ch], ch))
            pos += 1
            continue

        pos += 1

    tokens.append((_TT_EOF, None))
    return tokens

# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------
class _Parser:
    def __init__(self, tokens: list[tuple[str, object]]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._modules: dict[str, int] = {}
        self.module_names: dict[int, str] = {}
        self.fndefs: dict[tuple[int, int, int, int], FnDef] = {}
        self.full_fndefs: list[FnDef] = []

    def _peek(self) -> tuple[str, object]:
        return self._tokens[self._pos]

    def _peek_type(self) -> str:
        return self._tokens[self._pos][0]

    def _consume(self, expected: str | None = None) -> tuple[str, object]:
        tok = self._tokens[self._pos]
        if expected is not None and tok[0] != expected:
            raise ValueError(f'KFN parse error: expected {expected}, got {tok[0]!r}')
        self._pos += 1
        return tok

    def _check(self, *types: str) -> bool:
        return self._tokens[self._pos][0] in types

    def _optional(self, tt: str) -> bool:
        if self._peek_type() == tt:
            self._consume()
            return True
        return False

    def parse(self) -> None:
        while not self._check(_TT_EOF):
            if self._check(_TT_MODULE):
                self._parse_module_def()
            elif self._check(_TT_VER):
                self._parse_ver_block()
            elif self._check(_TT_FUN):
                fd = self._parse_fun_def()
                self._register_fun(fd, ver_constraint=None)
            else:
                self._consume()
 
    def _parse_module_def(self) -> None:
        self._consume(_TT_MODULE)
        _, num = self._consume(_TT_INTEGER)
        if self._optional(_TT_EQ):
            _, name = self._consume(_TT_IDENT)
            self._modules[name] = num
            self.module_names[num] = name

    def _parse_ver_block(self) -> None:
        self._consume(_TT_VER)
        ver_constraint = self._parse_versions()
        fun_defs = []
        while self._check(_TT_FUN):
            fun_defs.append(self._parse_fun_def())
        self._consume(_TT_END)
        for fd in fun_defs:
            self._register_fun(fd, ver_constraint)

    def _parse_versions(self) -> list:
        versions = [self._parse_version()]
        while self._optional(_TT_CM):
            versions.append(self._parse_version())
        return versions

    def _parse_version(self) -> object:
        if self._check(_TT_IDENT):
            _, name = self._consume(_TT_IDENT)
            return ('class', name.lower())
        if self._optional(_TT_GT):
            if self._optional(_TT_EQ): return ('>=', self._parse_vstamp())
            return ('>', self._parse_vstamp())
        if self._optional(_TT_LT):
            if self._optional(_TT_EQ): return ('<=', self._parse_vstamp())
            return ('<', self._parse_vstamp())
        return ('any',)

    def _parse_vstamp(self) -> tuple:
        _, a = self._consume(_TT_INTEGER)
        if not self._optional(_TT_PT): return (a, 0, 0, 0)
        _, b = self._consume(_TT_INTEGER)
        if not self._optional(_TT_PT): return (a, b, 0, 0)
        _, c = self._consume(_TT_INTEGER)
        if not self._optional(_TT_PT): return (a, b, c, 0)
        _, d = self._consume(_TT_INTEGER)
        return (a, b, c, d)

    def _parse_fun_def(self) -> tuple:
        self._consume(_TT_FUN)
        ident1, ident2 = self._parse_ident()
        ccode_str, ccode_flags = self._parse_ccode()
        if not ccode_str and ident2 and ident2 != ident1:
            ccode_str = ident2
        fun_flags = self._parse_fun_flags()

        self._consume(_TT_LT)
        _, op_type = self._consume(_TT_INTEGER)
        self._consume(_TT_CO)
        op_module = self._parse_module_id()
        self._consume(_TT_CO)
        _, op_func = self._consume(_TT_INTEGER)
        self._consume(_TT_CM)
        _, overloads = self._consume(_TT_INTEGER)
        self._consume(_TT_GT)

        prototypes = self._parse_prototypes()
        all_flags = frozenset(ccode_flags + fun_flags)
        ident = ident1

        return (ident, ccode_str, all_flags, op_type, op_module, op_func, overloads, prototypes)

    def _parse_ident(self) -> tuple[str, str]:
        if self._check(_TT_END):
            self._consume()
            return ('end', 'end')
        if not self._check(_TT_IDENT):
            return ('', '')
        _, first = self._consume(_TT_IDENT)
        if self._check(_TT_IDENT):
            _, second = self._consume(_TT_IDENT)
            return (first, second)
        return (first, first)

    def _parse_ccode(self) -> tuple[str, list]:
        if not self._optional(_TT_LBR): return ('', [])
        
        flags = []
        if self._optional(_TT_ST):
            flags.append('textout')
            if self._optional(_TT_EQ):
                flags.extend(['nobrace', 'lbr'])
        elif self._optional(_TT_EQ):
            flags.append('nobrace')
            
        if self._check(_TT_RBR):
            self._consume(_TT_RBR)
            return ('__unnamed__', flags)
        
        if self._check(_TT_IDENT):
            _, name = self._consume(_TT_IDENT)
            self._consume(_TT_RBR)
            return (name, flags)
            
        return ('', [])

    def _parse_fun_flags(self) -> list[str]:
        if not self._optional(_TT_LP): return []
        flags = []
        while not self._check(_TT_RP, _TT_EOF):
            _, name = self._consume(_TT_IDENT)
            mapping = {'store': 'store', 'jump': 'jump', 'goto': 'goto', 'if': 'cond'}
            flags.append(mapping.get(name.lower(), name.lower()))
        self._consume(_TT_RP)
        return flags

    def _parse_module_id(self) -> int:
        if self._check(_TT_INTEGER):
            _, num = self._consume(_TT_INTEGER)
            return num
        _, name = self._consume(_TT_IDENT)
        num = self._modules.get(name)
        return num if num is not None else 0

    def _parse_prototypes(self) -> list:
        protos = []
        while self._check(_TT_QU, _TT_LP):
            if self._optional(_TT_QU): protos.append(None)
            else:
                self._consume(_TT_LP)
                params = self._parse_parameters()
                protos.append(params)
        return protos

    def _parse_parameters(self) -> list[FnParam]:
        params: list[FnParam] = []
        if self._optional(_TT_RP): return params
        params.append(self._parse_param())
        while self._optional(_TT_CM):
            params.append(self._parse_param())
        self._consume(_TT_RP)
        return params

    def _parse_param(self) -> FnParam:
        pre = self._parse_preparm()
        if self._check(_TT_STRING):
            _, tag = self._consume(_TT_STRING)
            post = self._parse_postparm()
            p = FnParam(ptype='intC', tag=tag)
        else:
            ptype, sub_params, special_defs = self._parse_typedef()
            post = self._parse_postparm()
            p = FnParam(ptype=ptype, sub_params=sub_params, special_defs=special_defs)

        for f in pre + post:
            if f == 'optional': p.optional = True
            elif f == 'uncount': p.uncount = True
            elif f == 'return':  p.is_return = True
            elif f == 'fake': p.fake = True
            elif f == 'textobj': p.text_obj = True
            elif f == 'argc': p.argc = True
            elif f.startswith('tag:'):  p.tag = f[4:]
        return p

    def _parse_preparm(self) -> list[str]:
        flags = []
        while True:
            if self._optional(_TT_HA): flags.append('textobj')
            elif self._optional(_TT_QU): flags.append('optional')
            elif self._optional(_TT_LT): flags.append('uncount')
            elif self._optional(_TT_GT): flags.append('return')
            elif self._optional(_TT_EQ): flags.append('fake')
            else: break
        return flags

    def _parse_postparm(self) -> list[str]:
        flags = []
        while True:
            if self._optional(_TT_PL): flags.append('argc')
            elif self._check(_TT_STRING):
                _, tag = self._consume(_TT_STRING)
                flags.append(f'tag:{tag}')
            else: break
        return flags

    def _parse_typedef(self) -> tuple[str, list, list]:
        tt = self._peek_type()
        if tt == _TT_INT: self._consume(); return ('int', [], [])
        if tt == _TT_INTC: self._consume(); return ('intC', [], [])
        if tt == _TT_INTV: self._consume(); return ('intV', [], [])
        if tt == _TT_STR: self._consume(); return ('str', [], [])
        if tt == _TT_STRC: self._consume(); return ('strC', [], [])
        if tt == _TT_STRV: self._consume(); return ('strV', [], [])
        if tt == _TT_RES: self._consume(); return ('res', [], [])
        if tt == _TT_SPECIAL:
            self._consume()
            self._consume(_TT_LP)
            sdefs = self._parse_special()
            self._consume(_TT_RP)
            return ('special', [], sdefs)
        if tt == _TT_LP:
            self._consume()
            sub = self._parse_complex()
            self._consume(_TT_RP)
            return ('complex', sub, [])
        return ('intC', [], [])

    def _parse_complex(self) -> list[FnParam]:
        params = [self._parse_compdef()]
        while self._optional(_TT_CM):
            params.append(self._parse_compdef())
        return params

    def _parse_compdef(self) -> FnParam:
        if self._check(_TT_STRING):
            _, tag = self._consume(_TT_STRING)
            return FnParam(ptype='intC', tag=tag)
        ptype, sub_params, special_defs = self._parse_typedef()
        tag = ''
        if self._check(_TT_STRING):
            _, tag = self._consume(_TT_STRING)
        return FnParam(ptype=ptype, tag=tag, sub_params=sub_params, special_defs=special_defs)

    def _parse_special(self) -> list:
        sdefs = [self._parse_specdef()]
        while self._optional(_TT_CM):
            sdefs.append(self._parse_specdef())
        return sdefs

    def _parse_specdef(self) -> tuple:
        _, sid = self._consume(_TT_INTEGER)
        
        # Accommodate 0-48: syntax
        if self._optional(_TT_MINUS):
            _, sid2 = self._consume(_TT_INTEGER)
            sid = ((sid + 1) << 8) | sid2
            
        self._consume(_TT_CO)
        no_parens = self._optional(_TT_HA)

        if self._check(_TT_IDENT):
            _, name = self._consume(_TT_IDENT)
            self._consume(_TT_LP)
            params = self._parse_complex()
            self._consume(_TT_RP)
            return (sid, 'named', name, params, no_parens)
        elif self._optional(_TT_LBR):
            params = self._parse_complex()
            self._consume(_TT_RBR)
            return (sid, 'complex', '', params, no_parens)
        else:
            return (sid, 'complex', '', [], no_parens)

    def _register_fun(self, fun_def: tuple, ver_constraint: object) -> None:
        ident, ccode_str, all_flags, op_type, op_module, op_func, overloads, prototypes = fun_def
        expected = overloads + 1
        if len(prototypes) != expected:
            if len(prototypes) < expected:
                prototypes = prototypes + [None] * (expected - len(prototypes))
            else:
                prototypes = prototypes[:expected]

        ccode = ident if ccode_str == '__unnamed__' else ccode_str

        fndef = FnDef(
            ident=ident if ident else '',
            flags=all_flags,
            ccode=ccode,
            prototypes=prototypes,
            op_type=op_type,
            op_module=op_module,
            op_code=op_func,
            targets=ver_constraint or [],
        )
        self.full_fndefs.append(fndef)

        for i, proto in enumerate(prototypes):
            key = (op_type, op_module, op_func, i)
            existing = self.fndefs.get(key)
            if ver_constraint is None or existing is None:
                self.fndefs[key] = FnDef(
                    ident=fndef.ident,
                    flags=fndef.flags,
                    ccode=fndef.ccode,
                    prototypes=[proto],
                    targets=fndef.targets,
                )
        global functions, ctrlcodes
        if fndef.ident:
            functions[fndef.ident] = fndef
        if fndef.ccode and fndef.ccode != '__unnamed__':
            ctrlcodes[fndef.ccode] = fndef

def load_kfn(path: str | Path) -> tuple[list, dict]:
    text = Path(path).read_text(encoding='utf-8')
    tokens = _tokenize(text)
    parser = _Parser(tokens)
    parser.parse()
    return parser.full_fndefs, parser.module_names

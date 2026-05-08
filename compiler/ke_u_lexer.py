import re
from typing import Tuple, Any, Optional

from . import ketypes
from .ketypes import *
from . import str_lexer

KEYWORDS = {
    "#file": ("DWITHEXPR", ("file", "Str")),
    "#resource": ("DWITHEXPR", ("resource", "Str")),
    "#base_res": ("DWITHEXPR", ("base_res", "Str")),
    "#entrypoint": ("DWITHEXPR", ("entrypoint", "Int")),
    "#character": ("DWITHEXPR", ("character", "Str")),
    "#val_0x2c": ("DWITHEXPR", ("val_0x2c", "Int")),
    "#kidoku_type": ("DWITHEXPR", ("kidoku_type", "Int")),
    "#print": ("DWITHEXPR", ("print", "None")),
    "#error": ("DWITHEXPR", ("error", "None")),
    "#warn": ("DWITHEXPR", ("warn", "None")),
    "#exclude": ("DWITHEXPR", ("exclude", "Int")),
    "#hiding": ("DHIDING", None),
    "#define": ("DDEFINE", "Define"),
    "#sdefine": ("DDEFINE", "DefineScoped"),
    "#undef": ("DUNDEF", None),
    "#redef": ("DDEFINE", "Redefine"),
    "#const": ("DDEFINE", "Const"),
    "#bind": ("DDEFINE", "Bind"),
    "#ebind": ("DDEFINE", "EBind"),
    "#set": ("DSET", None),
    "#target": ("DTARGET", None),
    "#version": ("DVERSION", None),
    "#inline": ("DINLINE", False),
    "#sinline": ("DINLINE", True),
    "#load": ("DLOAD", None),
    "eof": ("DEOF", None),
    "halt": ("DHALT", None),
    "op": ("OP", None),
    "return": ("RETURN", None),
    "_": ("USCORE", None),
    "int": ("INT", 32),
    "str": ("STR", None),
    "bit": ("INT", 1),
    "bit2": ("INT", 2),
    "bit4": ("INT", 4),
    "byte": ("INT", 8),
    "#if": ("DIF", None),
    "#ifdef": ("DIFDEF", True),
    "#ifndef": ("DIFDEF", False),
    "#else": ("DELSE", None),
    "#elseif": ("DELSEIF", None),
    "#endif": ("DENDIF", None),
    "#for": ("DFOR", None),
    "if": ("IF", None),
    "else": ("ELSE", None),
    "while": ("WHILE", None),
    "repeat": ("REPEAT", None),
    "till": ("TILL", None),
    "for": ("FOR", None),
    "case": ("CASE", None),
    "of": ("OF", None),
    "other": ("OTHER", None),
    "ecase": ("ECASE", None),
    "break": ("BREAK", None),
    "continue": ("CONTINUE", None),
    "raw": ("RAW", None),
    "endraw": ("ENDRAW", None),
    "$s": ("SPECIAL", "S"),
    "$pause": ("SPECIAL", "Pause"),
    "store": ("REG", 0xc8),
    # Variables mapping
    "strK": ("SVAR", 0x0a),
    "intL": ("VAR", 0x0b),
    "strM": ("SVAR", 0x0c),
    "strS": ("SVAR", 0x12),
    "intA": ("VAR", 0x00),
    "intB": ("VAR", 0x01),
    "intC": ("VAR", 0x02),
    "intD": ("VAR", 0x03),
    "intE": ("VAR", 0x04),
    "intF": ("VAR", 0x05),
    "intG": ("VAR", 0x06),
    "intZ": ("VAR", 0x19),
    "intAb": ("VAR", 0x1a),
    "intBb": ("VAR", 0x1b),
    "intCb": ("VAR", 0x1c),
    "intDb": ("VAR", 0x1d),
    "intEb": ("VAR", 0x1e),
    "intFb": ("VAR", 0x1f),
    "intGb": ("VAR", 0x20),
    "intZb": ("VAR", 0x33),
    "intA2b": ("VAR", 0x34),
    "intB2b": ("VAR", 0x35),
    "intC2b": ("VAR", 0x36),
    "intD2b": ("VAR", 0x37),
    "intE2b": ("VAR", 0x38),
    "intF2b": ("VAR", 0x39),
    "intG2b": ("VAR", 0x3a),
    "intZ2b": ("VAR", 0x4d),
    "intA4b": ("VAR", 0x4e),
    "intB4b": ("VAR", 0x4f),
    "intC4b": ("VAR", 0x50),
    "intD4b": ("VAR", 0x51),
    "intE4b": ("VAR", 0x52),
    "intF4b": ("VAR", 0x53),
    "intG4b": ("VAR", 0x54),
    "intZ4b": ("VAR", 0x67),
    "intA8b": ("VAR", 0x68),
    "intB8b": ("VAR", 0x69),
    "intC8b": ("VAR", 0x6a),
    "intD8b": ("VAR", 0x6b),
    "intE8b": ("VAR", 0x6c),
    "intF8b": ("VAR", 0x6d),
    "intG8b": ("VAR", 0x6e),
    "intZ8b": ("VAR", 0x81),
    "goto_on": ("GO_LIST", ("goto_on", "goto_on")),
    "goto_case": ("GO_CASE", ("goto_case", "goto_case")),
    "gosub_on": ("GO_LIST", ("gosub_on", "gosub_on")),
    "gosub_case": ("GO_CASE", ("gosub_case", "gosub_case")),
    "select_w": ("SELECT", ("select_w", 0)),
    "select": ("SELECT", ("select", 1)),
    "select_s2": ("SELECT", ("select_s2", 2)),
    "select_s": ("SELECT", ("select_s", 3)),
    "select_w2": ("SELECT", ("select_w2", 10)),
    "select_msgcancel": ("SELECT", ("select_msgcancel", 11)),
    "select_btncancel": ("SELECT", ("select_btncancel", 12)),
    "select_btnwkcancel": ("SELECT", ("select_btnwkcancel", 13)),
}

KEYWORDS = {k.lower(): v for k, v in KEYWORDS.items()}

def token_of_identifier(tkn: str) -> Tuple[str, Any]:
    for s, t in ketypes.gotofuncs:
        KEYWORDS[t.lower()] = ("GOTO", (s, t.lower()))
    ketypes.gotofuncs.clear()

    tkn_lower = tkn.lower()
    if tkn_lower in KEYWORDS:
        return KEYWORDS[tkn_lower]
    return ("IDENT", (tkn, tkn_lower))

def ml_num_of_kpg_num(s: str) -> str:
    if len(s) > 1:
        if s[1] == '#': s = '0b' + s[2:]
        elif s[1] == '%': s = '0o' + s[2:]
    if s.startswith('$'): return "0x" + s[1:]
    return s

def int_of_kpg_num(s: str) -> int:
    s = ml_num_of_kpg_num(s).replace('_', '')
    if s.lower().startswith(("0x", "0b", "0o")):
        return int(s, 0)
    return int(s, 10)

class KeULexerState:
    def __init__(self, text: str, loc: Location):
        self.text = text
        self.pos = 0
        self.length = len(text)
        self.loc = Location(loc.file, loc.line)

    def peek(self, offset=0) -> str:
        if self.pos + offset < self.length: return self.text[self.pos + offset]
        return ""

    def consume(self, count=1):
        self.pos += count

    def match_re(self, pattern: str) -> Optional[re.Match]:
        return re.match(pattern, self.text[self.pos:])

def skip_comment(st: KeULexerState):
    while st.pos < st.length:
        if st.text.startswith("-}", st.pos):
            st.consume(2)
            return
        if st.peek() == '\n':
            st.loc = Location(st.loc.file, st.loc.line + 1)
            st.consume()
        else:
            st.consume()
    error(st.loc, "unterminated comment")

def get_token(st: KeULexerState) -> Tuple[Tuple[str, Any], Location]:
    while st.pos < st.length:
        c = st.peek()
        
        # Whitespace and comments
        if c in ' \t\u3000':
            st.consume(); continue
        if c == '\r' and st.peek(1) == '\n':
            st.loc = Location(st.loc.file, st.loc.line + 1)
            st.consume(2); continue
        if c == '\n':
            st.loc = Location(st.loc.file, st.loc.line + 1)
            st.consume(); continue
            
        if st.text.startswith("//", st.pos):
            while st.pos < st.length and st.peek() != '\n':
                st.consume()
            if st.pos < st.length:
                st.loc = Location(st.loc.file, st.loc.line + 1)
                st.consume()
            continue
            
        if st.text.startswith("{-", st.pos):
            st.consume(2)
            skip_comment(st)
            continue

        # Lexer directives
        m_line = st.match_re(r'^#line[ \t]+([$0-9A-Fa-f_%#]+)')
        if m_line:
            val = int_of_kpg_num(m_line.group(1))
            st.loc = Location(st.loc.file, val - 1)
            st.consume(m_line.end())
            continue

        m_res = st.match_re(r'^#res[ \t\r\n]*<[ \t\r\n]*')
        if m_res:
            st.consume(m_res.end())
            str_st = str_lexer.StrLexerState(st.text, st.pos)
            lc, key = str_lexer.get_resstr_key(str_lexer.AuxT('ResStr', st.loc.file, st.loc.line, {}), str_st)
            if not key: error(st.loc, "anonymous resource string references not permitted in #res references")
            # Sync the outer lexer state to exactly where the inner lexer finished
            st.pos = str_st.pos
            return (("DRES", key), st.loc)

        # Symbols
        sym2 = st.text[st.pos:st.pos+2]
        sym3 = st.text[st.pos:st.pos+3]
        if sym3 in ("<<=", ">>="):
            st.consume(3); return (("SSHL" if sym3 == "<<=" else "SSHR", None), st.loc)
        if sym2 in ("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "==", "!=", "<=", ">=", "&&", "||", "->"):
            st.consume(2)
            mapping = {"+=": "SADD", "-=": "SSUB", "*=": "SMUL", "/=": "SDIV", "%=": "SMOD", "&=": "SAND", "|=": "SOR", "^=": "SXOR", "==": "EQU", "!=": "NEQ", "<=": "LTE", ">=": "GTE", "&&": "LAND", "||": "LOR", "->": "ARROW"}
            return ((mapping[sym2], None), st.loc)
        if sym2 in ("<<", ">>"):
            st.consume(2)
            return (("SHL" if sym2 == "<<" else "SHR", None), st.loc)
            
        if c in "()[]{}:;,.+-*/%&|^=<>!~":
            st.consume(1)
            mapping = {"(": "LPAR", ")": "RPAR", "[": "LSQU", "]": "RSQU", "{": "LCUR", "}": "RCUR", ":": "COLON", ";": "SEMI", ",": "COMMA", ".": "POINT", "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD", "&": "AND", "|": "OR", "^": "XOR", "=": "SET", "<": "LTN", ">": "GTN", "!": "NOT", "~": "TILDE"}
            return ((mapping[c], None), st.loc)

        # Literals
        if st.text.startswith("0x", st.pos):
            warning(st.loc, "Kepago uses $nnn rather than 0xnnn for hexadecimal constants")
            m_hex = st.match_re(r'^0x[0-9a-fA-F_]+')
            val = int(m_hex.group(0).replace('_', ''), 16)
            st.consume(m_hex.end())
            return (("INTEGER", val), st.loc)

        m_num = st.match_re(r'^(\$[0-9A-Fa-f_]+|\$#[01_]+|\$%[0-7_]+|[0-9][0-9_]*)')
        if m_num:
            s_val = m_num.group(0)
            val = int_of_kpg_num(s_val)
            st.consume(m_num.end())
            return (("INTEGER", val), st.loc)

        if c in "'\"":
            term = 'Single' if c == "'" else 'Double'
            s, nloc, consumed = str_lexer.get_string_tokens(term, st.loc, st.text[st.pos+1:])
            st.loc = nloc
            st.pos += 1 + consumed  # Use exact consumed length instead of regex!
            return (("STRING", s), st.loc)

        # Extended identifier regex to include non-ASCII characters
        m_ident = st.match_re(r'^[A-Za-z_?#$\u0080-\uffff][A-Za-z0-9_?#$\u0080-\uffff]*')
        if m_ident:
            ident = m_ident.group(0)
            st.consume(m_ident.end())
            if ident == "__file__": return (("STRING", [("Text", st.loc, "Sbcs", st.loc.file)]), st.loc)
            if ident == "__line__": return (("INTEGER", st.loc.line), st.loc)
            return (token_of_identifier(ident), st.loc)

        # Labels
        if c == '@':
            m_lbl = st.match_re(r'^@[A-Za-z0-9_?#$\u0080-\uffff]+')
            if m_lbl:
                lbl = m_lbl.group(0)[1:]
                st.consume(m_lbl.end())
                return (("LABEL", (lbl, lbl)), st.loc)

        error(st.loc, f"invalid character '{c}' in source file")

    return (("EOF", None), st.loc)

def call_parser_on_text(entrypoint, loc: Location, text: str):
    from . import ke_ast_parser
    st = KeULexerState(text, loc)
    parser = ke_ast_parser.KeAstParser(st)
    return getattr(parser, entrypoint)()

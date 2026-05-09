import re, os
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from . import ketypes
from .ketypes import *
from . import config
from . import app
from . import global_state
from . import ke_u_lexer
from . import ketypes

@dataclass
class AuxT:
    term: str  # 'Single', 'Double', 'ResStr'
    file: str
    line: int
    res: Dict[str, Tuple[List[Any], Location]]

def get_loc(aux: AuxT) -> Location:
    return Location(aux.file, aux.line)

def unterminated(aux: AuxT, msg: str = "") -> None:
    error(get_loc(aux), "unterminated string" + (f": {msg}" if msg else ""))

rewrites: List[Any] = []

class StrLexerState:
    def __init__(self, text: str, pos: int = 0):
        self.text = text
        self.pos = pos
        self.length = len(text)

    def eof(self) -> bool:
        return self.pos >= self.length

    def peek(self, offset: int = 0) -> str:
        if self.pos + offset < self.length:
            return self.text[self.pos + offset]
        return ""

    def consume(self, count: int = 1):
        self.pos += count

    def match_re(self, pattern: str) -> Optional[re.Match]:
        return re.match(pattern, self.text[self.pos:])

def skip_comment(aux: AuxT, st: StrLexerState):
    while not st.eof():
        if st.text.startswith("-}", st.pos):
            st.consume(2)
            return
        elif st.peek() == '\n':
            aux.line += 1
            st.consume()
        else:
            st.consume()
    error(get_loc(aux), "unterminated comment")

_anon_resstrs = -1
def get_anon_resstr_key() -> str:
    global _anon_resstrs
    _anon_resstrs += 1
    return f"__anon_resstr_{_anon_resstrs:04d}__"

def get_resstr_key(aux: AuxT, st: StrLexerState) -> Tuple[Location, str]:
    rv = []
    lc = get_loc(aux)
    
    def set_rv(v: str):
        nonlocal lc
        if not rv:
            lc = get_loc(aux)
        rv.append(v)

    def get_quoted_key(qchar: str):
        st.consume() # consume quote
        b = []
        while not st.eof():
            if st.peek() == qchar:
                st.consume()
                return "".join(b)
            elif st.peek() == '\\' and st.peek(1) in ('\r', '\n'):
                if st.peek(1) == '\r' and st.peek(2) == '\n':
                    st.consume(3)
                else:
                    st.consume(2)
                aux.line += 1
            elif st.peek() == '\\':
                b.append(st.peek(1))
                st.consume(2)
            elif st.peek() == '\n':
                unterminated(aux)
            else:
                b.append(st.peek())
                st.consume()
        unterminated(aux)

    while not st.eof():
        c = st.peek()
        if c in ' \t\u3000':
            st.consume()
            continue
        if c == '\n' or (c == '\r' and st.peek(1) == '\n'):
            aux.line += 1
            st.consume(1 if c == '\n' else 2)
            continue
        if c in "'\"":
            set_rv(get_quoted_key(c))
            continue
        
        m_int = st.match_re(r'^[0-9]+')
        if m_int:
            set_rv(str(int(m_int.group(0))))
            st.consume(m_int.end())
            continue
            
        m_hex = st.match_re(r'^\$[0-9A-Za-z]+')
        if m_hex:
            set_rv(str(int("0x" + m_hex.group(0)[1:], 16)))
            st.consume(m_hex.end())
            continue
            
        m_ident = st.match_re(r'^[^ \'\"\t\r\n>}]+')
        if m_ident:
            set_rv(m_ident.group(0))
            st.consume(m_ident.end())
            continue
            
        if c in '>}':
            st.consume()
            while not st.eof() and st.peek() in ' \t\u3000':
                st.consume()
            return lc, "".join(rv)
            
        ketypes.cli_error(f"inexhaustive match in get_resstr_key at offset {st.pos}")
        
    raise EOFError()

# A forward reference to KeULexer parser calls that will be injected from the compiler frame
call_parser_on_text = lambda loc, text: None
get_token_keulexer = lambda loc, st: None

def get_f_code(aux: AuxT, floc: Location, st: StrLexerState) -> List[Any]:
    carr = []
    bracelevel = 1
    curr_loc = floc
    from . import ke_u_lexer
    
    ke_st = ke_u_lexer.KeULexerState(st.text, curr_loc)
    ke_st.pos = st.pos
    
    while True:
        tkn, nloc = ke_u_lexer.get_token(ke_st)
        if tkn[0] == 'EOF' or (tkn[0] == 'RCUR' and bracelevel == 1):
            aux.line = nloc.line
            st.pos = ke_st.pos
            return carr
            
        carr.append((tkn, nloc))
        if tkn[0] == 'RCUR': bracelevel -= 1
        elif tkn[0] == 'LCUR': bracelevel += 1
        curr_loc = nloc

def get_token(aux: AuxT, st: StrLexerState) -> Any:
    def get_closed_tokens(restrict: bool, ident: str, context: str) -> List[Any]:
        tkns = []
        while True:
            tkn = get_token(aux, st)
            if tkn[0] == "EOS":
                unterminated(aux, f"expected '}}' in \\{ident} code")
            if tkn[0] == "RCur":
                return tkns
            if restrict and tkn[0] == "Speaker":
                error(get_loc(aux), f"\\{{}} is illegal in {context}")
            if restrict and tkn[0] == "Gloss":
                g = "g" if tkn[2] == "Gloss" else "ruby"
                error(get_loc(aux), f"\\{g}{{}} is illegal in {context}")
            tkns.append(tkn)

    while not st.eof():
        c = st.peek()
        
        # Terminators
        if c == "'":
            st.consume()
            return ("EOS",) if aux.term == 'Single' else ("Text", get_loc(aux), "Sbcs", "'")
        if c == '"':
            st.consume()
            return ("EOS",) if aux.term == 'Double' else ("DQuote", get_loc(aux))
        if c == '<':
            st.consume()
            return ("EOS",) if aux.term == 'ResStr' else ("Text", get_loc(aux), "Sbcs", "<")
            
        # Line breaks
        if c == '\r' and st.peek(1) != '\n':
            st.consume()
            continue
        m_space_nl = st.match_re(r'^[ \t\u3000]*\r?\n[ \t\u3000]*')
        if m_space_nl:
            aux.line += 1
            st.consume(m_space_nl.end())
            return ("Space", get_loc(aux), 1)
        m_esc_nl = st.match_re(r'^\\+[ \t\u3000]*\r?\n[ \t\u3000]*')
        if m_esc_nl:
            aux.line += 1
            st.consume(m_esc_nl.end())
            continue

        # Comments
        if st.text.startswith("{-", st.pos):
            if aux.term == 'ResStr':
                st.consume(2)
                skip_comment(aux, st)
                continue
            else:
                st.consume(2)
                return ("Text", get_loc(aux), "Sbcs", "{-")
        if st.text.startswith("//", st.pos):
            if aux.term == 'ResStr':
                while not st.eof() and st.peek() != '\n':
                    st.consume()
                if not st.eof():
                    st.consume()
                    aux.line += 1
                continue
            else:
                st.consume(2)
                return ("Text", get_loc(aux), "Sbcs", "//")
        if st.text.startswith("{/", st.pos):
            st.consume(2)
            return ("Text", get_loc(aux), "Sbcs", "{/")

        # Control codes
        if c == '}':
            st.consume()
            return ("RCur", get_loc(aux))
        if st.text.startswith("\\{", st.pos) or st.match_re(r'^\\name[ \t\u3000]*{'):
            m = st.match_re(r'^\\name[ \t\u3000]*{')
            st.consume(m.end() if m else 2)
            return ("Speaker", get_loc(aux))
            
        # \g and \ruby
        m_g = st.match_re(r'^\\g([ \t\u3000]*\{)?')
        if m_g:
            if not m_g.group(1): error(get_loc(aux), "expected '{' after \\g")
            gloc = get_loc(aux)
            st.consume(m_g.end())
            tkns = get_closed_tokens(True, "g", "a glossed term")
            
            # get_key
            st.match_re(r'^[ \t\u3000]*=[ \t\u3000]*') # ignore whitespaces before/after =
            eq_match = st.match_re(r'^[ \t\u3000]*=[ \t\u3000]*([<{])')
            if not eq_match:
                error(aux, "expected '=' after \\g{}")
            st.consume(eq_match.end() - 1)
            char = st.peek()
            st.consume()
            
            if char == '<':
                try: 
                    l, key = get_resstr_key(aux, st)
                    resstr_val = ("ResStr", l, key)
                except EOFError: 
                    unterminated(aux)
            else: # '{'
                l = get_loc(aux)
                k = get_anon_resstr_key()
                gloss_tkns = get_closed_tokens(False, "g", "")
                global resources
                global_state.resources[k] = (gloss_tkns, l)
                resstr_val = ("ResStr", l, k)
                
            return ("Gloss", gloc, "Gloss", tkns, resstr_val)

        m_ruby = st.match_re(r'^\\ruby([ \t\u3000]*\{)?')
        if m_ruby:
            if not m_ruby.group(1): error(get_loc(aux), "expected '{' after \\ruby")
            rloc = get_loc(aux)
            st.consume(m_ruby.end())
            tkns = get_closed_tokens(True, "ruby", "\\ruby{} base text")
            
            eq_match = st.match_re(r'^[ \t\u3000]*(=)?[ \t\u3000]*([<{])')
            if not eq_match:
                error(aux, "expected '=' after \\ruby{}")
            st.consume(eq_match.end() - 1)
            has_eq = eq_match.group(1) is not None
            char = st.peek()
            st.consume()
            
            if char == '<':
                if not has_eq: warning(get_loc(aux), r"the format \ruby{...}<id> is deprecated: use \ruby{...}=<id> instead")
                try: 
                    l, key = get_resstr_key(aux, st)
                    resstr_val = ("ResStr", l, key)
                except EOFError: 
                    unterminated(aux)
            else: # '{'
                l = get_loc(aux)
                if not has_eq: warning(l, r"the format \ruby{...}{...} is deprecated: use \ruby{...}={...} instead")
                gloss_tkns = get_closed_tokens(True, "ruby", "\\ruby{} glosses")
                resstr_val = ("Closed", l, gloss_tkns)
                
            return ("Gloss", rloc, "Ruby", tkns, resstr_val)

        if st.text.startswith("\\a", st.pos):
            m = st.match_re(r'^\\a[ \t\u3000]*\{')
            if m:
                st.consume(m.end())
                try:
                    l, key = get_resstr_key(aux, st)
                    return ("Add", get_loc(aux), (l, key))
                except EOFError:
                    unterminated(aux)
            else:
                st.consume(2)
                return ("Add", get_loc(aux), (get_loc(aux), ""))

        if st.text.startswith("\\d", st.pos):
            m = st.match_re(r'^\\d([ \t\u3000]*\{[ \t\u3000]*\})?')
            st.consume(m.end())
            return ("Delete", get_loc(aux))

        if st.text.startswith("\\res", st.pos):
            m = st.match_re(r'^\\res[ \t\u3000]*\{')
            if m:
                st.consume(m.end())
                try:
                    l, key = get_resstr_key(aux, st)
                    return ("ResRef", get_loc(aux), (l, key))
                except EOFError:
                    unterminated(aux)

        m_f = st.match_re(r'^\\f([ \t\u3000]*\{)?')
        if m_f:
            floc = get_loc(aux)
            st.consume(m_f.end())
            if m_f.group(1):
                code = get_f_code(aux, floc, st)
            else:
                # Default behavior fallback
                aline = aux.line
                def_str_func = ("VarOrFn", floc, "__DefStrFunc__", "__DefStrFunc__")
                # Requires memory lookups integrated from the frame, simplified here
                code = [] 
                aux.line = aline
            
            key = len(rewrites)
            rewrites.append(code)
            return ("Rewrite", floc, key)

        m_code = st.match_re(r'^\\([A-Za-z_]+)([ \t\u3000]*)([:{])')
        if m_code:
            codeloc = get_loc(aux)
            code_ident = m_code.group(1)
            char_ended = m_code.group(3)
            st.consume(m_code.end())
            
            optarg = None
            if char_ended == ':':
                # Read until '{' handling nested '('
                b_opt = []
                pc = 0
                while not st.eof():
                    c_opt = st.peek()
                    if c_opt == '{':
                        if pc > 0: b_opt.append(c_opt); pc += 1; st.consume()
                        else: st.consume(); break
                    elif c_opt == '(': b_opt.append(c_opt); pc += 1; st.consume()
                    elif c_opt == ')': b_opt.append(c_opt); pc = max(0, pc - 1); st.consume()
                    elif c_opt == '\n':
                        if aux.term != 'ResStr': unterminated(aux)
                        aux.line += 1; b_opt.append('\n'); st.consume()
                    elif c_opt == '\\':
                        b_opt.append('\\'); st.consume()
                        if st.peek() == '\n':
                            aux.line += 1; b_opt.append('\n'); st.consume()
                    else:
                        b_opt.append(c_opt); st.consume()

                optarg = ke_u_lexer.call_parser_on_text("just_expression", codeloc, "".join(b_opt))
                
            b_args = []
            bc = 0
            while not st.eof():
                c_arg = st.peek()
                if c_arg == '}':
                    if bc > 0: bc -= 1; b_args.append(c_arg); st.consume()
                    else: st.consume(); break
                elif c_arg == '{':
                    if st.text.startswith("{-", st.pos):
                        b_args.append("{-"); st.consume(2)
                    else:
                        bc += 1; b_args.append(c_arg); st.consume()
                elif c_arg == '\n':
                    if aux.term != 'ResStr': unterminated(aux)
                    aux.line += 1; b_args.append('\n'); st.consume()
                elif c_arg == '\\':
                    b_args.append('\\'); st.consume()
                    if st.peek() == '\n':
                        aux.line += 1; b_args.append('\n'); st.consume()
                else:
                    b_args.append(c_arg); st.consume()
            
            arglist = ke_u_lexer.call_parser_on_text("just_param_list", codeloc, "".join(b_args))
            
            if code_ident in ('l', 'm'):
                lg = 'Local' if code_ident == 'l' else 'Global'
                if not arglist: error(codeloc, f"expected argument to control code \\{code_ident}{{}}")

                def name_index_expr(expr: Any) -> Any:
                    if expr[0] != "VarOrFn":
                        return expr
                    loc, _, ident = expr[1], expr[2], expr[3]
                    if len(ident) > 2:
                        return expr

                    def getval(ch: str) -> int:
                        o = ord(ch)
                        if 0x61 <= o <= 0x7a:
                            return o - 0x61
                        if 0x41 <= o <= 0x5a:
                            return o - 0x41
                        if 0xff21 <= o <= 0xff3a:
                            return o - 0xff21
                        raise ValueError

                    try:
                        chars = list(ident)
                        idx = ((getval(chars[0]) + 1) * 26 + getval(chars[1])) if len(chars) == 2 else getval(chars[0])
                    except ValueError:
                        return expr
                    return ("Int", loc, idx)

                def arg_expr(p):
                    if p[0] != "Simple":
                        error(codeloc, f"expected expression as parameter to control code \\{code_ident}{{}}")
                    return name_index_expr(p[2])
                return ("Name", codeloc, lg, arg_expr(arglist[0]), arg_expr(arglist[1]) if len(arglist)>1 else None)
            
            return ("Code", codeloc, code_ident, optarg, arglist)

        m_basic_code = st.match_re(r'^\\([A-Za-z])')
        if m_basic_code:
            code_ident = m_basic_code.group(1)
            if code_ident.lower() in ketypes.ctrlcodes:
                st.consume(2)
                return ("Code", get_loc(aux), code_ident, None, [])

        m_spaces = st.match_re(r'^(\\_|[ \t\u3000])+')
        if m_spaces:
            spaces = m_spaces.group(0)
            count = sum(2 if ch in ('\u3000', '\t') else 1 for ch in spaces if ch != '\\')
            st.consume(m_spaces.end())
            return ("Space", get_loc(aux), count)

        # Escaped characters
        if st.text.startswith('\\"', st.pos):
            st.consume(2)
            return ("DQuote", get_loc(aux))
        if st.text.startswith('\\k', st.pos) and st.peek(2) not in ('\r', '\n'):
            st.consume(3)
            return ("Text", get_loc(aux), "Sbcs", st.text[st.pos-1])
        if st.text.startswith('\\', st.pos):
            st.consume(2)
            return ("Text", get_loc(aux), "Sbcs", st.text[st.pos-1])

        # Special DB characters (Japanese)
        c = st.peek()
        if c == '【':
            st.consume()
            return ("LLentic", get_loc(aux))
        if c == '】':
            st.consume()
            return ("RLentic", get_loc(aux))
        if c == '※':
            st.consume()
            return ("Asterisk", get_loc(aux))
        if c == '％':
            st.consume()
            return ("Percent", get_loc(aux))
        if c == '-':
            st.consume()
            return ("Hyphen", get_loc(aux))

        m_sbcs = st.match_re(r'^[\x00-\x08\x0b-\x0c\x0e-\x1f\x21\x23-\x26\x28-\x2c\x2e\x30-\x3b\x3d-\x5b\x5d-\x7c\x7e-\u02ff]+')
        if m_sbcs:
            val = m_sbcs.group(0)
            st.consume(m_sbcs.end())
            return ("Text", get_loc(aux), "Sbcs", val)
            
        m_dbcs = st.match_re(r'^[\u0300-\u2fff\u3001-\u300f\u3012-\uff04\uff06-\uff09\uff0b-\uffff]+')
        if m_dbcs:
            val = m_dbcs.group(0)
            st.consume(m_dbcs.end())
            return ("Text", get_loc(aux), "Dbcs", val)

        val = st.peek()
        st.consume()
        return ("Text", get_loc(aux), "Sbcs", val)
        
    return ("EOS",)

def get_string(aux: AuxT, st: StrLexerState) -> List[Any]:
    rv = []
    while True:
        tkn = get_token(aux, st)
        if tkn[0] == 'ResRef':
            l, (ll, t) = tkn[1], tkn[2]
            da, _ = global_state.get_base_resource(l, (t, t))
            rv.extend(da)
        elif tkn[0] == 'EOS':
            return rv
        else:
            rv.append(tkn)

def get_string_tokens(term: str, loc: Location, text: str) -> Tuple[List[Any], Location, int]:
    aux = AuxT(term=term, file=loc.file, line=loc.line, res={})
    st = StrLexerState(text)
    rv = get_string(aux, st)
    return rv, get_loc(aux), st.pos

def lex_resstr(aux: AuxT, st: StrLexerState) -> Tuple[Location, str, List[Any]]:
    startpos, key = get_resstr_key(aux, st)
    string_tokens = get_string(aux, st)
    if string_tokens and string_tokens[-1][0] == 'Space' and string_tokens[-1][2] == 1:
        string_tokens.pop()
    return startpos, key, string_tokens

def handle_resstr(aux: AuxT, st: StrLexerState, resstr: Tuple[Location, str, List[Any]]) -> str:
    startpos, ikey, istr = resstr
    key = get_anon_resstr_key() if not ikey else ikey
    
    if key in aux.res:
        eloc = aux.res[key][1]
        warning(startpos, f"duplicate resource string key <{key}> hides earlier definition at {eloc.file} line {eloc.line}")

    def getkey(t: str) -> str:
        if t: return t
        nested_resstr = lex_resstr(aux, st)
        return handle_resstr(aux, st, nested_resstr)

    resolved_str = []
    for tkn in istr:
        if tkn[0] == "Gloss" and tkn[4][0] == "ResStr":
            resolved_str.append(("Gloss", tkn[1], tkn[2], tkn[3], ("ResStr", tkn[4][1], getkey(tkn[4][2]))))
        elif tkn[0] == "Add":
            resolved_str.append(("Add", tkn[1], (tkn[2][0], getkey(tkn[2][1]))))
        elif tkn[0] == "Rewrite":
            key_id = tkn[2]
            code = rewrites[key_id]
            first = True
            for i, (spec, loc) in enumerate(code):
                if spec == ("SPECIAL", "S"):
                    if first: first = False
                    else: code[i] = (("DRES", getkey("")), loc)
            resolved_str.append(tkn)
        else:
            resolved_str.append(tkn)

    aux.res[key] = (resolved_str, startpos)
    return key

def load_resfile(floc: Location, fname: str, res_dict: Dict[str, Tuple[List[Any], Location]]) -> None:
    aux = AuxT(term='ResStr', file=fname, line=1, res=res_dict)
    
    if os.path.isabs(fname):
        fpath = fname
    else:
        if os.path.exists(fname):
            fpath = fname
        elif app.resdir and os.path.exists(os.path.join(app.resdir, fname)):
            fpath = os.path.join(app.resdir, fname)
        else:
            fpath = os.path.join(config.Config.init_prefix(), fname)
            
    if not os.path.exists(fpath):
        warning(floc, f"Resource file not found: {fpath}")
        return

    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        error(floc, str(e))
        return

    st = StrLexerState(text)
    
    # Process Header (simplified block matching the OCaml header processing)
    while not st.eof():
        c = st.peek()
        if c == '<':
            st.consume()
            break
        elif c in ' \t':
            st.consume()
        elif c == '\n' or (c == '\r' and st.peek(1) == '\n'):
            aux.line += 1
            st.consume(1 if c == '\n' else 2)
        elif st.text.startswith("//", st.pos):
            while not st.eof() and st.peek() != '\n': st.consume()
            if not st.eof():
                st.consume()
                aux.line += 1
        elif st.text.startswith("{-", st.pos):
            skip_comment(aux, st)
        elif st.text.startswith("#character", st.pos) or st.text.startswith("#resource", st.pos):
            is_char = st.text.startswith("#character", st.pos)
            m = st.match_re(r'^#(character|resource)[ \t\u3000]*')
            st.consume(m.end())
            
            if st.peek() in '"\'':
                q = st.peek()
                st.consume()
                b = []
                while not st.eof() and st.peek() != q:
                    b.append(st.peek())
                    st.consume()
                if not st.eof(): st.consume()
                s_val = "".join(b)
                if is_char:
                    global_state.dramatis_personae.append(s_val)
                else:
                    load_resfile(floc, s_val, global_state.base_res)
            else:
                error(get_loc(aux), "expected string literal")
        elif st.text.startswith("#", st.pos):
            error(aux, f"invalid directive in resource file header")
        else:
            if c == '\ufeff' and st.pos == 0:
                warning(get_loc(aux), "UTF-8 BOM (byte order mark)")
                st.consume()
            else:
                error(aux, f"invalid character {ord(c)} in resource file header")

    # Read strings
    while not st.eof():
        try:
            resstr = lex_resstr(aux, st)
            if not resstr[1]:
                error(resstr[0], "unmatched anonymous resource string")
            handle_resstr(aux, st, resstr)
        except EOFError:
            break

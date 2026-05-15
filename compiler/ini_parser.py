import os
import re
import sys
from typing import Dict, List, Optional, Tuple, Any

from . import config
from . import ketypes

curr_line: int = 1
curr_file: str = ""
_loaded_filename: str = ""
_loaded_mtime: float = -1.0

gameexe: Dict[str, List[Tuple[str, Any]]] = {}

def find(key: str) -> List[Tuple[str, Any]]:
    return gameexe[key.lower()]

def set_val(key: str, value: List[Tuple[str, Any]]) -> None:
    gameexe[key.lower()] = value

def unset(key: str) -> None:
    gameexe.pop(key.lower(), None)

def exists(key: str) -> bool:
    return key.lower() in gameexe

def set_int(key: str, value: int) -> None:
    set_val(key, [("Integer", value)])

def get(key: str) -> Optional[List[Tuple[str, Any]]]:
    return gameexe.get(key.lower())

def get_def(key: str, default: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    return gameexe.get(key.lower(), default)

def get_int(key: str, default: int) -> int:
    val = get(key)
    if val and len(val) > 0 and val[0][0] == "Integer":
        return val[0][1]
    return default

def get_pair(key: str, default: Tuple[int, int]) -> Tuple[int, int]:
    val = get(key)
    if val and len(val) >= 2 and val[0][0] == "Integer" and val[1][0] == "Integer":
        return val[0][1], val[1][1]
    return default

# Lexer and Parser for GAMEEXE.INI
class IniLexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.length = len(text)
        global curr_line
        curr_line = 1

    def get_token(self) -> Tuple[str, Any]:
        global curr_line
        while self.pos < self.length:
            c = self.text[self.pos]
            
            # Skip whitespace (including non-breaking and ideographic spaces) and comments
            if c in ' \t\r\xa0\u3000\v\f':
                self.pos += 1
                continue
            if c == '\n':
                curr_line += 1
                self.pos += 1
                continue
            if c == ';' or (c == '/' and self.pos + 1 < self.length and self.text[self.pos+1] == '/'):
                while self.pos < self.length and self.text[self.pos] != '\n':
                    self.pos += 1
                continue

            # Punctuation
            if c == '=':
                self.pos += 1; return ('EQ', None)
            if c == ',':
                self.pos += 1; return ('CM', None)
            if c == ':':
                self.pos += 1; return ('CO', None)
            if c == '(':
                self.pos += 1; return ('LP', None)
            if c == ')':
                self.pos += 1; return ('RP', None)
            if c == '.':
                self.pos += 1; return ('DOT', None)
            if c == '#':
                self.pos += 1; return ('HASH', None)

            # Strings
            if c == '"':
                start = self.pos + 1
                self.pos = start
                while self.pos < self.length and self.text[self.pos] != '"':
                    self.pos += 1
                val = self.text[start:self.pos]
                if self.pos < self.length:
                    self.pos += 1 # consume closing quote
                return ('STRING', val)

            # Identifiers and Integers (Longest match first to catch negatives correctly)
            match = re.match(r'^-?[0-9]+', self.text[self.pos:])
            if match:
                val = int(match.group(0))
                self.pos += match.end()
                return ('INT', val)

            if c == '-':
                self.pos += 1; return ('HY', None)

            match = re.match(r'^[A-Za-z_0-9\[\]]+', self.text[self.pos:])
            if match:
                val = match.group(0)
                self.pos += match.end()
                # Intercept whole words that are specific types
                if val == "U": return ('UN', True)
                if val == "N": return ('UN', False)
                if val in ("SHAKE", "SHAKEZOOM"): return ('SHAKE', val)
                if val == "DSTRACK": return ('DSTRACK', val)
                if val == "CDTRACK": return ('CDTRACK', val)
                if val == "NAMAE": return ('NAMAE', val)
                return ('IDENT', val)

            ketypes.cli_error(f"unexpected character '{c}' in GAMEEXE.INI at line {curr_line}")
        
        return ('EOF', None)

class IniParser:
    def __init__(self, lexer: IniLexer):
        self.lexer = lexer
        self.current_token = self.lexer.get_token()

    def advance(self):
        self.current_token = self.lexer.get_token()

    def accept(self, tok_type: str) -> bool:
        if self.current_token[0] == tok_type:
            self.advance()
            return True
        return False

    def expect(self, tok_type: str) -> Any:
        if self.current_token[0] == tok_type:
            val = self.current_token[1]
            self.advance()
            return val
        ketypes.cli_error(f"parsing GAMEEXE.INI: expected {tok_type} at line {curr_line}")

    def parse(self):
        while self.current_token[0] != 'EOF':
            if self.current_token[0] == 'HASH':
                self.advance()
                self.parse_definition()
            else:
                self.advance()

    def parse_definition(self):
        tok_type, tok_val = self.current_token
        
        if tok_type == 'IDENT':
            ident = tok_val
            self.advance()
            self.parse_ident_chain(ident)
        elif tok_type == 'SHAKE':
            shake_type = tok_val
            self.advance()
            self.expect('DOT')
            dot_int = self.expect('INT')
            self.expect('EQ')
            ranges = self.parse_ranges()
            set_val(f"{shake_type}.{dot_int:03d}", ranges)
        elif tok_type in ('DSTRACK', 'CDTRACK', 'NAMAE'):
            # Ignored for now per OCaml implementation
            while self.current_token[0] not in ('EOF', 'HASH'):
                self.advance()
        else:
            # Skip unhandled special directives
            while self.current_token[0] not in ('EOF', 'HASH'):
                self.advance()

    def parse_ident_chain(self, ident: str):
        chain = [ident]
        while self.current_token[0] == 'IDENT':
            # Some shipped GAMEEXE.INI files contain stray spaces inside key
            # names, e.g. "#SAVEMESSAGE_MESS _STR=...".
            chain[-1] += self.current_token[1]
            self.advance()
        while self.accept('DOT'):
            nxt_type, nxt_val = self.current_token
            if nxt_type == 'INT':
                chain.append(f"{nxt_val:03d}")
                self.advance()
                while self.current_token[0] == 'IDENT':
                    chain[-1] += self.current_token[1]
                    self.advance()
                if self.accept('CO'):
                    # Range generation: IDENT.DOTINT : INT = parameters
                    end_range = self.expect('INT')
                    self.expect('EQ')
                    params = self.parse_parameters()
                    base = ".".join(chain[:-1])
                    for i in range(int(nxt_val), int(end_range) + 1):
                        set_val(f"{base}.{i:03d}", params)
                    return
            elif nxt_type == 'IDENT':
                chain.append(nxt_val)
                self.advance()
                while self.current_token[0] == 'IDENT':
                    chain[-1] += self.current_token[1]
                    self.advance()
            elif nxt_type == 'LP':
                # IDENT.DOTINT.(range).DOTIDENT = parameters
                rng = self.parse_range()
                self.expect('DOT')
                dotident = self.expect('IDENT')
                while self.current_token[0] == 'IDENT':
                    dotident += self.current_token[1]
                    self.advance()
                self.expect('EQ')
                params = self.parse_parameters()
                base = ".".join(chain)
                for i in rng:
                    set_val(f"{base}.{i:03d}.{dotident}", params)
                return
            else:
                break
                
        self.expect('EQ')
        params = self.parse_parameters()
        set_val(".".join(chain), params)

    def parse_parameters(self) -> List[Tuple[str, Any]]:
        params = []
        while self.current_token[0] in ('INT', 'STRING', 'UN'):
            tok_type, tok_val = self.current_token
            self.advance()
            if tok_type == 'INT':
                params.append(("Integer", tok_val))
            elif tok_type == 'STRING':
                params.append(("String", tok_val))
            elif tok_type == 'UN':
                params.append(("Enabled", tok_val))
                
            if self.current_token[0] in ('CO', 'EQ', 'CM'):
                self.advance() # treat colons and equals like commas for now
            else:
                break
        return params

    def parse_ranges(self) -> List[Tuple[str, Any]]:
        ranges = []
        while self.current_token[0] == 'LP':
            ranges.append(("Range", self.parse_range()))
        return ranges

    def parse_range(self) -> List[int]:
        self.expect('LP')
        rng_elts = []
        rng_elts.append(self.expect('INT'))
        while self.accept('CM'):
            rng_elts.append(self.expect('INT'))
        self.expect('RP')
        return rng_elts

def init(srcdir: str, verbose: int, gameexe_path: str = ""):
    global curr_file, _loaded_filename, _loaded_mtime
    filename = ""
    
    if gameexe_path:
        if os.path.exists(gameexe_path) and os.path.isfile(gameexe_path):
            filename = gameexe_path
        else:
            ketypes.cli_error(f"'{gameexe_path}' is not a valid INI file")
    else:
        env_gameexe = os.environ.get("GAMEEXE")
        if env_gameexe and os.path.exists(env_gameexe):
            filename = env_gameexe
        else:
            candidates = [
                "GAMEEXE.INI", "gameexe.ini",
                os.path.join(os.pardir, "GAMEEXE.INI"),
                os.path.join(os.pardir, "gameexe.ini")
            ]
            for cand in candidates:
                cand_path = os.path.join(srcdir, cand)
                if os.path.exists(cand_path):
                    filename = cand_path
                    break

    if filename:
        filename = os.path.abspath(filename)
        mtime = os.path.getmtime(filename)
        if filename == _loaded_filename and mtime == _loaded_mtime:
            return

        curr_file = filename
        if verbose > 0:
            ketypes.cli_info(f"Reading INI: {filename}")
        try:
            with open(filename, 'r', encoding='cp932') as f:
                text = f.read()
            gameexe.clear()
            lexer = IniLexer(text)
            parser = IniParser(lexer)
            parser.parse()
            _loaded_filename = filename
            _loaded_mtime = mtime
        except Exception as e:
            ketypes.cli_error(f"Failed parsing INI: {e}")
    else:
        ketypes.cli_warning("unable to locate 'gameexe.ini': using default values")

import re
import sys
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict

@dataclass
class SubKey:
    offset: int
    length: int
    data: List[int]

@dataclass
class GameDef:
    id: str = ""
    title: str = ""
    by: str = ""
    seens: int = -1
    inherits: Optional[List[str]] = None
    target_engine: str = "RealLive"
    target_version: str = "Any"
    target_compiler: str = "Any"
    keys: List[SubKey] = field(default_factory=list)

_games: Dict[str, GameDef] = {}
_current_game_id: str = ""

def add_game(game: GameDef):
    if game.id in _games:
        print(f"Warning: Game '{game.id}' redefined.", file=sys.stderr)
    _games[game.id] = game

def get_game(game_id: str) -> Optional[GameDef]:
    return _games.get(game_id)

def set_current_game(game_id: str):
    global _current_game_id
    if game_id in _games:
        _current_game_id = game_id
    else:
        print(f"Error: unknown game '{game_id}'", file=sys.stderr)
        sys.exit(1)

def get_current_game() -> Optional[GameDef]:
    return _games.get(_current_game_id)

def get_current_keys() -> List[SubKey]:
    game = get_current_game()
    return game.keys if game else []

class Token:
    def __init__(self, type_: str, value: str, line: int):
        self.type = type_
        self.value = value
        self.line = line

class GameParser:
    KEYWORDS = {'game', 'by', 'with', 'seens', 'inherits', 'for', 'using', 'no', 'none', 'key', 'from', 'and'}
    
    def __init__(self, text: str):
        self.tokens = self._tokenize(text)
        self.pos = 0

    def _tokenize(self, text: str) -> List[Token]:
        token_specification = [
            ('HEX',      r'\$[0-9A-Fa-f]+|0x[0-9A-Fa-f]+'),
            ('INTEGER',  r'\d+'),
            ('STRING',   r'"[^"]*"|\'[^\']*\''),
            ('COMMENT',  r'(?:;|//|#)[^\n]*'),
            ('COMMA',    r','),
            ('COLON',    r':'),
            ('DOT',      r'\.'),
            ('IDENT',    r'[A-Za-z_][A-Za-z0-9_$?]*'),
            ('NEWLINE',  r'\n'),
            ('SKIP',     r'[ \t\r]+'),
            ('MISMATCH', r'.'),
        ]
        tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in token_specification)
        line_num = 1
        tokens = []
        for mo in re.finditer(tok_regex, text):
            kind = mo.lastgroup
            value = mo.group()
            if kind == 'NEWLINE':
                line_num += 1
            elif kind == 'SKIP' or kind == 'COMMENT':
                pass
            elif kind == 'MISMATCH':
                raise RuntimeError(f"Unexpected character {value!r} on line {line_num}")
            else:
                if kind == 'IDENT' and value.lower() in self.KEYWORDS:
                    kind = value.upper()
                elif kind == 'HEX':
                    val_str = value[1:] if value.startswith('$') else value[2:]
                    value = int(val_str, 16)
                    kind = 'INTEGER'
                elif kind == 'INTEGER':
                    value = int(value)
                elif kind == 'STRING':
                    value = value[1:-1] # Strip quotes
                tokens.append(Token(kind, value, line_num))
        tokens.append(Token('EOF', '', line_num))
        return tokens

    def _peek(self):
        return self.tokens[self.pos]

    def _consume(self, expected_type=None):
        tok = self.tokens[self.pos]
        if expected_type and tok.type != expected_type:
            raise SyntaxError(f"Expected {expected_type} but got {tok.type} at line {tok.line}")
        self.pos += 1
        return tok

    def _match(self, expected_type) -> bool:
        if self._peek().type == expected_type:
            self._consume()
            return True
        return False

    def _is_name_token(self, tok: Token) -> bool:
        return tok.type in ('IDENT', 'STRING', 'KEY')

    def parse(self):
        while self._peek().type != 'EOF':
            if self._peek().type == 'GAME':
                self.parse_game()
            else:
                self._consume()

    def parse_game(self):
        self._consume('GAME')
        game = GameDef()
        
        # IDENT
        game.id = self._consume('IDENT').value
        
        # [title]
        if self._is_name_token(self._peek()):
            game.title = self._consume().value
            
        # [by pub]
        if self._match('BY'):
            if self._is_name_token(self._peek()):
                game.by = self._consume().value
                
        # [with seens]
        if self._match('WITH'):
            game.seens = self._consume('INTEGER').value
            self._match('SEENS') # Optional
            
        # [inherits]
        if self._match('INHERITS'):
            if self._match('NONE'):
                game.inherits = None
            else:
                game.inherits = []
                game.inherits.append(self._consume('IDENT').value)
                while self._match('COMMA') or self._peek().type == 'IDENT':
                    if self._peek().type == 'COMMA': self._consume()
                    if self._peek().type == 'IDENT':
                        game.inherits.append(self._consume('IDENT').value)
                        
        # [for target]
        if self._match('FOR'):
            engine = self._consume('IDENT').value
            game.target_engine = engine.lower()
            # Parse version
            if self._peek().type == 'INTEGER':
                v_parts = [str(self._consume('INTEGER').value)]
                while self._match('DOT'):
                    v_parts.append(str(self._consume('INTEGER').value))
                game.target_version = ".".join(v_parts)
            # Parse compiler int
            if self._peek().type == 'INTEGER':
                game.target_compiler = str(self._consume('INTEGER').value)

        # [using key]
        if self._match('USING'):
            if self._match('NONE') or (self._match('NO') and self._match('KEY')):
                pass
            else:
                game.keys = self.parse_subkeys()
                
        add_game(game)

    def parse_subkeys(self) -> List[SubKey]:
        keys = []
        keys.append(self.parse_subkey())
        while self._match('AND') or self._match('COMMA'):
            keys.append(self.parse_subkey())
        return keys

    def parse_subkey(self) -> SubKey:
        self._consume('KEY')
        self._consume('FROM')
        offset = self._consume('INTEGER').value
        self._consume('FOR')
        length = self._consume('INTEGER').value
        self._consume('COLON')
        
        data = []
        while self._peek().type == 'INTEGER':
            data.append(self._consume('INTEGER').value)
            
        return SubKey(offset, length, data)

def load_games_file(filepath: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        parser = GameParser(f.read())
        parser.parse()

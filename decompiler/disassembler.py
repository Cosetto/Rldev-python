from __future__ import annotations
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .binarray import BinArray
from . import bytecode
from . import kfn
from . import config

# ---------------------------------------------------------------------------
# Variable name tables
# ---------------------------------------------------------------------------

IVAR: dict[int, str] = {
    0x00: 'intA',   0x01: 'intB',   0x02: 'intC',   0x03: 'intD',
    0x04: 'intE',   0x05: 'intF',   0x06: 'intG',   0x0b: 'intL',
    0x19: 'intZ',   0x1a: 'intAb',  0x1b: 'intBb',  0x1c: 'intCb',
    0x1d: 'intDb',  0x1e: 'intEb',  0x1f: 'intFb',  0x20: 'intGb',
    0x33: 'intZb',  0x34: 'intA2b', 0x35: 'intB2b', 0x36: 'intC2b',
    0x37: 'intD2b', 0x38: 'intE2b', 0x39: 'intF2b', 0x3a: 'intG2b',
    0x4d: 'intZ2b', 0x4e: 'intA4b', 0x4f: 'intB4b', 0x50: 'intC4b',
    0x51: 'intD4b', 0x52: 'intE4b', 0x53: 'intF4b', 0x54: 'intG4b',
    0x67: 'intZ4b', 0x68: 'intA8b', 0x69: 'intB8b', 0x6a: 'intC8b',
    0x6b: 'intD8b', 0x6c: 'intE8b', 0x6d: 'intF8b', 0x6e: 'intG8b',
    0x81: 'intZ8b',
}

SVAR: dict[int, str] = {
    0x0a: 'strK',
    0x0c: 'strM',
    0x12: 'strS',
}

_OP_STR: list[str] = ['+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>']

_CMP_STR: dict[int, str] = {
    0x28: '==', 0x29: '!=', 0x2a: '<=', 0x2b: '<', 0x2c: '>=', 0x2d: '>',
}

_BOOL_STR: dict[int, str] = {0x3c: '&&', 0x3d: '||'}

_ASSIGN_OPS: dict[int, str] = {
    0x14: '+=', 0x15: '-=', 0x16: '*=', 0x17: '/=', 0x18: '%=',
    0x19: '&=', 0x1a: '|=', 0x1b: '^=', 0x1c: '<<=', 0x1d: '>>=', 0x1e: '=',
}

def _prec(op: int) -> int:
    if op <= 0x09:
        return [4, 4, 5, 5, 5, 5, 4, 4, 6, 6][op]
    if op <= 0x29:
        return 2
    if op <= 0x2d:
        return 3
    if op == 0x3c:
        return 1
    if op == 0x3d:
        return 0
    return 0

_SEEN_END_SJS = bytes.fromhex('827282858285828e8264828e8284')

@dataclass
class Command:
    offset: int          
    text: str            
    is_jump: bool = False   
    hidden: bool = False    
    unhide: bool = False    
    pointers: set = field(default_factory=set)
    pushes_store: bool = False

_PTR_RE = re.compile(r'__PTR_([0-9A-Fa-f]{8})__')

def _ptr(offset: int) -> str:
    return f'__PTR_{offset:08X}__'

class _Reader:
    __slots__ = ('data', 'pos', 'end')

    def __init__(self, data: bytes | bytearray, start: int = 0, end: int | None = None) -> None:
        self.data = data
        self.pos  = start
        self.end  = end if end is not None else len(data)

    def eof(self) -> bool:
        return self.pos >= self.end

    def peek(self) -> int | None:
        return self.data[self.pos] if self.pos < self.end else None

    def read_byte(self) -> int:
        b = self.data[self.pos]
        self.pos += 1
        return b

    def rollback(self, n: int = 1) -> None:
        self.pos -= n

    def read_int16(self) -> int:
        v = struct.unpack_from('<h', self.data, self.pos)[0]
        self.pos += 2
        return v

    def read_uint16(self) -> int:
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def read_int32(self) -> int:
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def expect(self, byte_val: int, context: str) -> None:
        if self.eof():
            raise ValueError(f'{context}: unexpected EOF, expected 0x{byte_val:02x}')
        b = self.read_byte()
        if b != byte_val:
            raise ValueError(f'{context}: expected 0x{byte_val:02x}, got 0x{b:02x}')

    def peek_is(self, byte_val: int) -> bool:
        return self.peek() == byte_val

# ---------------------------------------------------------------------------
# Central Disassembler Class
# ---------------------------------------------------------------------------

class Disassembler:
    def __init__(self, outdir: str, options: dict, hdr, fndefs: dict, module_names: dict):
        self.outdir = Path(outdir)
        self.options = options
        self.separate_strings = not self.options.get('single_file', False)
        self.hdr = hdr
        self.fndefs = fndefs
        self.module_names = module_names
        self.mode = 'avg2000' if hdr.header_version == 1 else 'reallive'
        self.resstrs = []
        self.reshash = {} # Deduplication mapping
        self.use_excl = []
        self.commands = []
        self.errors = []

    def _variable_name(self, b: int) -> str:
        if b in IVAR: return IVAR[b]
        if b in SVAR: return SVAR[b]
        return f'VAR{b:02x}'

    def _read_expr_token(self, r: _Reader) -> str:
        if r.eof(): raise ValueError('unexpected EOF in _read_expr_token')
        b = r.read_byte()
        if b == 0xff: return str(r.read_int32())
        if b == 0xc8: return 'store'
        name = self._variable_name(b)
        r.expect(0x5b, '_read_expr_token') 
        idx = self._read_expression(r)
        r.expect(0x5d, '_read_expr_token') 
        return f'{name}[{idx}]'

    def _read_expr_term(self, r: _Reader) -> tuple:
        if r.eof(): raise ValueError('unexpected EOF in _read_expr_term')
        b = r.read_byte()
        if b == 0x24: return ('atom', self._read_expr_token(r))
        if b == 0x5c:
            op = r.read_byte()
            if op == 0x00: return self._read_expr_term(r)
            if op == 0x01: return ('neg', self._read_expr_term(r))
            raise ValueError(f'unexpected unary op 0x{op:02x} in _read_expr_term')
        if b == 0x28:
            inner = self._read_expr_bool(r)
            r.expect(0x29, '_read_expr_term')
            return inner
        r.rollback()
        raise ValueError(f'expected [$\\(] in _read_expr_term, found 0x{b:02x}')

    def _read_expr_arith(self, r: _Reader) -> tuple:
        def loop_hi(tok: tuple) -> tuple:
            if r.eof(): return tok
            p = r.peek()
            if p == 0x5c:
                r.read_byte()
                op = r.peek()
                if op is not None and 0x02 <= op <= 0x09:
                    r.read_byte()
                    rhs = self._read_expr_term(r)
                    return loop_hi(('binary', tok, op, rhs))
                r.rollback()
            return tok
        def loop_lo(tok: tuple) -> tuple:
            if r.eof(): return tok
            p = r.peek()
            if p == 0x5c:
                r.read_byte()
                op = r.peek()
                if op is not None and 0x00 <= op <= 0x01:
                    r.read_byte()
                    rhs = loop_hi(self._read_expr_term(r))
                    return loop_lo(('binary', tok, op, rhs))
                r.rollback()
            return tok
        return loop_lo(loop_hi(self._read_expr_term(r)))

    def _read_expr_cond(self, r: _Reader) -> tuple:
        def loop(tok: tuple) -> tuple:
            if r.eof(): return tok
            p = r.peek()
            if p == 0x5c:
                r.read_byte()
                op = r.peek()
                if op is not None and 0x28 <= op <= 0x2d:
                    r.read_byte()
                    rhs = self._read_expr_arith(r)
                    return loop(('binary', tok, op, rhs))
                r.rollback()
            return tok
        return loop(self._read_expr_arith(r))

    def _read_expr_bool(self, r: _Reader) -> tuple:
        def loop_and(tok: tuple) -> tuple:
            if r.eof(): return tok
            p = r.peek()
            if p == 0x5c:
                r.read_byte()
                op = r.peek()
                if op == 0x3c:
                    r.read_byte()
                    rhs = self._read_expr_cond(r)
                    return loop_and(('binary', tok, 0x3c, rhs))
                r.rollback()
            return tok
        def loop_or(tok: tuple) -> tuple:
            if r.eof(): return tok
            p = r.peek()
            if p == 0x5c:
                r.read_byte()
                op = r.peek()
                if op == 0x3d:
                    r.read_byte()
                    rhs = loop_and(self._read_expr_cond(r))
                    return loop_or(('binary', tok, 0x3d, rhs))
                r.rollback()
            return tok
        return loop_or(loop_and(self._read_expr_cond(r)))

    def _traverse(self, node: tuple) -> str:
        kind = node[0]
        if kind == 'atom': return node[1]
        if kind == 'neg':
            inner = node[1]
            s = self._traverse(inner)
            if inner[0] == 'atom': return f'-{s}'
            if inner[0] == 'neg': return self._traverse(inner[1])
            return f'-({s})'
        if kind == 'binary':
            _, lhs, op, rhs = node
            a = self._traverse(lhs)
            b = self._traverse(rhs)
            op_s = _OP_STR[op] if 0x00 <= op <= 0x09 else _CMP_STR.get(op, _BOOL_STR.get(op, f'[op{op:02x}]'))
            if op == 0x07 and b == '-1': return f'~{a if lhs[0] != "binary" else f"({a})"}'
            if op == 0x28 and b == '0': return f'!{a if lhs[0] != "binary" else f"({a})"}'
            if op == 0x29 and b == '0': return a
            b_par = b if b.startswith('~') else f'({b})' if rhs[0] == 'binary' and _prec(rhs[2]) <= _prec(op) else b
            a_par = f'({a})' if lhs[0] == 'binary' and _prec(lhs[2]) < _prec(op) else a
            return f'{a_par} {op_s} {b_par}'
        return '?'

    def _read_expression(self, r: _Reader) -> str:
        ast = self._read_expr_bool(r)
        return self._traverse(ast)

    def _is_sjis1(self, b: int) -> bool:
        return (0x81 <= b <= 0x9f) or (0xe0 <= b <= 0xfc)

    def _is_sjis_halfwidth(self, b: int) -> bool:
        return 0xa1 <= b <= 0xdf

    def _is_data_str_start(self, b: int) -> bool:
        return b == 0x22 or (0x41 <= b <= 0x5a) or (0x30 <= b <= 0x39) or b == 0x3f or b == 0x5f or self._is_sjis1(b)

    def _read_string_data(self, r: _Reader, sep_str: bool = False, raw_mode: bool = False) -> str:
        buf = bytearray()
        q = False

        def read_quot() -> None:
            nonlocal q
            while not r.eof():
                b = r.read_byte()
                if b == 0x22:
                    if q:
                        return
                    read_unquot()
                    return
                elif b == 0x5c:
                    buf.append(b)
                    if not r.eof(): buf.append(r.read_byte())
                elif self._is_sjis1(b):
                    buf.append(b)
                    if not r.eof(): buf.append(r.read_byte())
                else:
                    buf.append(b)

        def read_unquot() -> None:
            nonlocal q
            while not r.eof():
                b = r.peek()
                if b is None: break
                if b == 0x22:
                    r.read_byte()
                    q = (len(buf) == 0)
                    read_quot()
                    return
                elif self._is_sjis1(b):
                    buf.append(r.read_byte())
                    if not r.eof(): buf.append(r.read_byte())
                elif (0x41 <= b <= 0x5a) or (0x30 <= b <= 0x39) or b == 0x3f or b == 0x5f:
                    buf.append(r.read_byte())
                else:
                    break

        read_unquot()
        text = buf.decode('cp932')
        
        if raw_mode:
            return text

        has_jp = any(ord(c) > 0x7F for c in text)
        if sep_str or (self.options.get('separate_all', False) and self.separate_strings and has_jp):
            if not self.options.get('no_smart_resources', True) and text in self.reshash:
                return f'#res<{self.reshash[text]:04d}>'
            
            res_id = len(self.resstrs)
            self.resstrs.append(text)
            
            if not self.options.get('no_smart_resources', True):
                self.reshash[text] = res_id
                
            return f'#res<{res_id:04d}>'
        
        text = text.replace("'", "\\'")
        return f"'{text}'"

    def _read_data(self, r: _Reader, sep_str: bool = False) -> str:
        while not r.eof():
            b = r.peek()
            if b == 0x2c:
                r.read_byte()
                continue
            if b == 0x0a:
                r.read_byte(); r.read_int16()
                continue
            break
        if r.eof() or r.peek() is None: return ''
        b = r.peek()
        if self._is_data_str_start(b): return self._read_string_data(r, sep_str)
        if b == 0x61:
            r.read_byte()
            sid = r.read_byte()
            r.expect(0x28, '_read_data.special')
            buf = [f'__special[{sid}]({self._read_data(r)}']
            while not r.eof() and r.peek() != 0x29: buf.append(f', {self._read_data(r)}')
            r.expect(0x29, '_read_data.special')
            return ''.join(buf) + ')'
        return self._read_expression(r)

    def _read_textout_str(self, r: _Reader) -> str:
        """Reads raw textout bytes and returns the correctly escaped/formatted CP932 string."""
        _TEXTOUT_STOP = frozenset([0x00, 0x23, 0x24, 0x0a, 0x40, 0x21])
        buf = []
        esc = self.separate_strings and not self.options.get('raw_strings', False)
        
        while not r.eof():
            b = r.peek()
            if b is None or b in _TEXTOUT_STOP: break
            
            # EOF marker
            if b == 0x82 and r.pos + 14 <= r.end and r.data[r.pos:r.pos+14] == _SEEN_END_SJS:
                r.pos += 14
                while r.pos < r.end and r.data[r.pos] == 0xff: r.pos += 1
                return "eof"
                
            b = r.read_byte()
            
            if b == 0x22: # Literal double quote in textout
                buf.append('"')
                continue
            if b == 0x2c: # Comma
                continue
            if b == 0x5c: # Backslash
                buf.append("\\\\")
                continue
            if b == 0x27: # Single quote
                buf.append("'" if esc else "\\'")
                continue
            if b == 0x3c: # <
                buf.append("\\<" if esc else "<")
                continue
            
            # 2-byte specific logic
            if b == 0x81 and r.pos < r.end:
                b2 = r.peek()
                
                if b2 == 0x79:
                    r.read_byte()
                    buf.append("\\{" if esc else "{")
                    continue
                if b2 == 0x7a:
                    r.read_byte()
                    buf.append("}")
                    if r.pos + 2 < r.end and r.data[r.pos] == 0x20 and r.data[r.pos+1] in (0x22, 0x27):
                        r.pos += 2
                        buf.append(" " + chr(r.data[r.pos-1]))
                    continue
                    
                if b2 in (0x93, 0x96) and r.pos + 2 < r.end and r.data[r.pos+1] == 0x82:
                    b4 = r.data[r.pos+2]
                    if 0x60 <= b4 <= 0x79:
                        lm = 'l' if b2 == 0x93 else 'm'
                        c1 = chr(b4 - 0x1f)
                        c2 = ""
                        idx = -1
                        adv = 3
                        if r.pos + 4 < r.end and r.data[r.pos+3] == 0x82:
                            b6 = r.data[r.pos+4]
                            if 0x60 <= b6 <= 0x79:
                                c2 = chr(b6 - 0x1f)
                                adv = 5
                            elif 0x4f <= b6 <= 0x58:
                                idx = b6 - 0x4f
                                adv = 5
                        if idx == -1 and r.pos + adv + 1 < r.end and r.data[r.pos+adv] == 0x82:
                            b_idx = r.data[r.pos+adv+1]
                            if 0x4f <= b_idx <= 0x58:
                                idx = b_idx - 0x4f
                                adv += 2
                                
                        r.pos += adv
                        if idx != -1: buf.append(f"\\{lm}{{{c1}{c2}, {idx}}}")
                        else: buf.append(f"\\{lm}{{{c1}{c2}}}")
                        continue
                        
                if b2 == 0x94 and r.pos + 6 < r.end and r.data[r.pos+1] == 0x82 and r.data[r.pos+3] == 0x82 and r.data[r.pos+5] == 0x82:
                    code = "e" if r.data[r.pos+2] == 0x60 else "em"
                    em_idx = (r.data[r.pos+4] - 0x4f) * 10 + (r.data[r.pos+6] - 0x4f)
                    r.pos += 7
                    buf.append(f"\\{code}{{{em_idx}}}")
                    continue
                    
            r.rollback()
            
            if self._is_sjis1(r.peek()):
                sjis_bytes = r.data[r.pos:r.pos+2]
                r.pos += 2
                decoded = sjis_bytes.decode('cp932')
                if buf and buf[-1].endswith('/') and decoded.startswith('/'):
                    buf[-1] = buf[-1][:-1] + ('\\//' if esc else '//')
                elif buf and buf[-1].endswith('{') and decoded.startswith('-'):
                    buf[-1] = buf[-1][:-1] + ('{\\-' if esc else '{-')
                else:
                    buf.append(decoded)
            elif self._is_sjis_halfwidth(r.peek()):
                decoded = bytes([r.read_byte()]).decode('cp932')
                buf.append(decoded)
            else:
                c = chr(r.read_byte())
                if c == '/' and buf and buf[-1].endswith('/'):
                    buf[-1] = buf[-1][:-1] + ('\\//' if esc else '//')
                elif c == '-' and buf and buf[-1].endswith('{'):
                    buf[-1] = buf[-1][:-1] + ('{\\-' if esc else '{-')
                else:
                    buf.append(c)
                    
        return "".join(buf)

    # ---------------------------------------------------------------------------
    # Ruby and Textout Merging Logic
    # ---------------------------------------------------------------------------

    def _add_textout(self, text: str, offset: int) -> None:
        if not text:
            return

        last_cmd = None
        for cmd in reversed(self.commands):
            # OCaml logic ONLY skips hidden commands. It DOES NOT skip is_jump commands!
            # Skipping is_jump caused us to look past line terminators (like `click()`)
            # and accidentally concatenate to the previous line's #res ID.
            if not cmd.hidden:
                last_cmd = cmd
                break

        if last_cmd is not None:
            if self.separate_strings:
                m = re.match(r'^#res<(\d+)>$', last_cmd.text)
                if m:
                    idx = int(m.group(1))
                    # Only append if this is the most recently created resource!
                    if idx == len(self.resstrs) - 1:
                        old_text = self.resstrs[idx]
                        self.resstrs[idx] += text
                        
                        if not self.options.get('no_smart_resources', True):
                            if self.reshash.get(old_text) == idx:
                                del self.reshash[old_text]
                            self.reshash[self.resstrs[idx]] = idx
                        return
            else:
                if last_cmd.text.startswith("'") and last_cmd.text.endswith("'"):
                    inner = last_cmd.text[1:-1]
                    last_cmd.text = f"'{inner}{text}'"
                    return

        # Force a new textout
        if self.separate_strings:
            if not self.options.get('no_smart_resources', True) and text in self.reshash:
                self.commands.append(Command(offset, f'#res<{self.reshash[text]:04d}>'))
                return
                
            res_id = len(self.resstrs)
            self.resstrs.append(text)
            
            if not self.options.get('no_smart_resources', True):
                self.reshash[text] = res_id
                
            self.commands.append(Command(offset, f'#res<{res_id:04d}>'))
        else:
            self.commands.append(Command(offset, f"'{text}'"))

    def _read_ruby(self, r: _Reader, argc: int, offset: int) -> None:
        if argc == 0:
            self._add_textout(r"\ruby{", offset)
        elif argc == 1:
            r.expect(0x28, '_read_ruby')
            b = r.peek()
            if b == 0x24:
                r.read_byte() # consume '$'
                r.rollback()
                e = self._read_expression(r)
                arg = f"\\s{{{e}}}"
            else:
                if self._is_data_str_start(b):
                    arg = self._read_string_data(r, raw_mode=True)
                else:
                    arg = self._read_expression(r)
            r.expect(0x29, '_read_ruby')
            self._add_textout(f"}}={{{arg}}}", offset)
        else:
            self.commands.append(Command(offset, f"ruby_error({argc})"))

    def _read_goto_case(self, r: _Reader, to_or_sub: str, argc: int) -> tuple[str, set]:
        expr = self._read_expression(r)
        r.expect(0x7b, 'read_goto_case')
        parts = [f'go{to_or_sub}_case({expr}){{ ']
        ptrs: set[int] = set()
        for i in range(argc):
            b = r.peek()
            if b == 0x28:
                r.read_byte()
                b2 = r.peek()
                if b2 == 0x29:
                    r.read_byte()
                    label_txt = ('_:' if i == 0 else '; _:')
                else:
                    e = self._read_expression(r)
                    r.expect(0x29, 'read_goto_case')
                    label_txt = (f'{e}:' if i == 0 else f'; {e}:')
                target = r.read_int32()
                ptrs.add(target)
                parts.append(label_txt + _ptr(target))
            else: break
        r.expect(0x7d, 'read_goto_case')
        parts.append(' }')
        return ''.join(parts), ptrs

    def _read_goto_on(self, r: _Reader, to_or_sub: str, argc: int) -> tuple[str, set]:
        expr = self._read_expression(r)
        r.expect(0x7b, 'read_goto_on')
        parts = [f'go{to_or_sub}_on({expr}){{ ']
        ptrs: set[int] = set()
        for i in range(argc):
            target = r.read_int32()
            ptrs.add(target)
            parts.append(('' if i == 0 else ',') + _ptr(target))
        r.expect(0x7d, 'read_goto_on')
        parts.append(' }')
        return ''.join(parts), ptrs

    def _read_select(self, r: _Reader, opcode_func: int, argc: int) -> str:
        fn_names = {
            0: 'select_w',
            1: 'select',
            2: 'select_s2',
            3: 'select_s',
            10: 'select_cancel',
            11: 'select_msgcancel',
            12: 'select_btncancel',
            13: 'select_btnwkcancel',
        }
        fn = fn_names.get(opcode_func, f'select_{opcode_func:05d}')
        
        if r.peek_is(0x28):
            r.read_byte()
            args = []
            while not r.eof() and not r.peek_is(0x29):
                if r.peek_is(0x2c):
                    r.read_byte()
                    continue
                args.append(self._read_expression(r))
            r.expect(0x29, 'read_select')
            fn = f'{fn}[{", ".join(args)}]'

        if not r.peek_is(0x7b):
            return fn
            
        r.read_byte()

        def skip_debug_info():
            while not r.eof():
                b = r.peek()
                if b == 0x0a:
                    r.read_byte()
                    r.read_int32() if self.mode == 'avg2000' else r.read_int16()
                elif b == 0x2c: r.read_byte()
                else: break

        has_conds = False
        cases: list[str] = []
        for _ in range(argc):
            skip_debug_info()
            cond = ''
            if r.peek_is(0x28):
                has_conds = True
                r.read_byte()
                cond_parts = []
                while not r.eof() and not r.peek_is(0x29):
                    inner_cond = ''
                    if r.peek_is(0x28):
                        r.read_byte()
                        ec = self._read_expression(r)
                        r.expect(0x29, 'read_select.cond')
                        inner_cond = f' if {ec}'
                    func_byte = r.read_byte()
                    func_name_map = {0x30: 'colour', 0x31: 'title', 0x32: 'hide', 0x33: 'blank', 0x34: 'cursor'}
                    fspec = func_name_map.get(func_byte, f'fn{func_byte:02x}')
                    need_arg = func_byte in (0x30, 0x31, 0x34)
                    arg = ''
                    if need_arg and not r.eof() and r.peek() != 0x29:
                        b = r.peek()
                        if not (0x30 <= b <= 0x39): arg = f'({self._read_expression(r)})'
                    cond_parts.append(fspec + arg + inner_cond)
                r.expect(0x29, 'read_select.cond')
                cond = '; '.join(cond_parts) + ': '
            item = "''" if r.peek_is(0x0a) else self._read_data(r, sep_str=True)
            cases.append(cond + item)

        skip_debug_info()
        r.expect(0x7d, 'read_select')
        sep = (',\n    ' if has_conds else ', ')
        return f'{fn}(\n    {sep.join(cases)}\n)' if has_conds else f'{fn}({", ".join(cases)})'

    def _read_complex_param(self, r: _Reader, params: list, with_parens: bool, opens: str) -> str:
        parts: list[str] = []
        for p in params:
            b = r.peek()
            if b == 0x61 or (b == 0x29 and with_parens): break
            e = self._read_data(r)
            if parts and not (not parts and opens == '{' and e.startswith('-')): parts.append(', ')
            else:
                if parts or opens != '{' or not e.startswith('-'):
                    if parts: parts.append(', ')
            parts.append(e)
        return ''.join(parts)

    def _read_special_param(self, r: _Reader, sdefs: list) -> str:
        r.expect(0x61, '_read_special_param')
        sid = r.read_byte()
        if r.peek_is(0x61):
            r.read_byte()
            sid = ((r.read_byte() + 1) << 8) | sid
        sdef = next((sd for sd in sdefs if sd[0] == sid), None)

        if sdef is None:
            r.expect(0x28, '_read_special_param.unknown')
            parts = [self._read_data(r)]
            while not r.eof() and not r.peek_is(0x29):
                parts.append(', '); parts.append(self._read_data(r))
            r.expect(0x29, '_read_special_param.unknown')
            return f'__special[{sid}]({"".join(parts)})'

        _, kind, name, params, no_parens = sdef
        if kind == 'named':
            r.expect(0x28, '_read_special_param.named')
            inner = self._read_complex_param(r, params, True, f'{name}(')
            r.expect(0x29, '_read_special_param.named')
            return f'{name}({inner})'
        else:
            if no_parens:
                inner = self._read_complex_param(r, params, False, '')
                return inner
            else:
                r.expect(0x28, '_read_special_param.complex')
                inner = self._read_complex_param(r, params, True, '{')
                r.expect(0x29, '_read_special_param.complex')
                return f'{{{inner}}}'

    def _read_unknown_function(self, r: _Reader, opstr: str, argc: int) -> tuple[str, set]:
        if argc == 0 and not r.peek_is(0x28): 
            return opstr, set()
            
        while r.peek_is(0x0a):
            r.read_byte()
            r.read_int32() if self.mode == 'avg2000' else r.read_int16()
            
        try: r.expect(0x28, '_read_unknown_function')
        except ValueError: return opstr, set()

        parts, remaining = [], argc
        while not r.eof():
            b = r.peek()
            if b == 0x29: r.read_byte(); break
            if b == 0x0a: r.read_byte(); r.read_int16(); continue
            if b == 0x2c: r.read_byte(); continue
            parts.append(self._read_data(r))
            if remaining > 0: remaining -= 1
        return f'{opstr}({", ".join(parts)})', set()

    def _read_soft_function(self, r: _Reader, opcode_key: tuple, argc: int, fndef: kfn.FnDef, offset: int) -> tuple[str|None, set, bool, bool]:
        is_jump = 'jump' in fndef.flags or 'ret' in fndef.flags or 'skip' in fndef.flags
        pushes_store = 'store' in fndef.flags

        if not fndef.prototypes or fndef.prototypes[0] is None:
            text, ptrs = self._read_unknown_function(r, fndef.ident, argc)
            return text, ptrs, is_jump, pushes_store

        prototype = fndef.prototypes[0]
        pre = ''
        ptrs: set[int] = set()
        ptr_txt = ''

        if argc == 0 and (not prototype or not r.peek_is(0x28)):
            fake_parts = []
            if prototype:
                for p in prototype:
                    if p.fake: 
                        fake_parts.append(p.tag)
            param_str = ', '.join(fake_parts)
            if 'goto' in fndef.flags:
                try:
                    target = r.read_int32()
                    ptrs.add(target)
                    ptr_txt = _ptr(target)
                except: pass
        else:
            # Skip debug lines before checking for '('
            while r.peek_is(0x0a):
                r.read_byte()
                r.read_int32() if self.mode == 'avg2000' else r.read_int16()

            try: r.expect(0x28, f'_read_soft_function({fndef.ident})')
            except ValueError:
                text, ptrs = self._read_unknown_function(r, fndef.ident, argc)
                return text, ptrs, is_jump, pushes_store

            buf, remaining = [], argc
            param_list = list(prototype)
            i = 0

            while i < len(param_list):
                p = param_list[i]
                
                while r.peek_is(0x0a):
                    r.read_byte(); r.read_int16()

                if p.fake:
                    if buf: buf.append(', ')
                    buf.append(p.tag)
                    i += 1; continue

                if remaining == 0 and (p.optional or p.argc):
                    while r.peek_is(0x0a): r.read_byte(); r.read_int16()
                    break
                if r.peek_is(0x29): r.read_byte(); break
                if buf and not p.is_return: buf.append(', ')

                next_i = i if (p.argc and remaining > 1) else i + 1

                try:
                    if p.ptype == 'complex':
                        while r.peek_is(0x0a): r.read_byte(); r.read_int16()
                        r.expect(0x28, f'_read_soft_function.complex({fndef.ident})')
                        inner = self._read_complex_param(r, p.sub_params, True, '{')
                        r.expect(0x29, f'_read_soft_function.complex({fndef.ident})')
                        buf.append(f'{{{inner}}}')
                        if not p.uncount: remaining -= 1
                    elif p.ptype == 'special':
                        buf.append(self._read_special_param(r, p.special_defs))
                        if not p.uncount: remaining -= 1
                    else:
                        d = self._read_data(r, sep_str=(p.ptype == 'res'))
                        if p.is_return:
                            pre = f'{d} = '
                            if not p.uncount: remaining -= 1
                            i += 1; continue
                        else:
                            buf.append(d)
                            if not p.uncount: remaining -= 1
                except (ValueError, struct.error) as e:
                    buf.append(f'[err:{e}]')
                    while not r.eof() and not r.peek_is(0x29): r.read_byte()
                    break
                i = next_i

            if not r.eof() and r.peek_is(0x29): r.read_byte()
            elif not r.eof() and r.peek_is(0x0a):
                r.read_byte(); r.read_int16()
                if not r.eof() and r.peek_is(0x29): r.read_byte()

            if 'goto' in fndef.flags:
                try:
                    target = r.read_int32()
                    ptrs.add(target)
                    ptr_txt = _ptr(target)
                except: pass
            
            param_str = ''.join(buf)

        if self.options.get('control_codes', True) and fndef.ccode:
            if not param_str:
                suffix = "" if 'nobrace' in fndef.flags else "{}"
                ccode_str = f"\\{fndef.ccode}{suffix}"
            else:
                ccode_str = f"\\{fndef.ccode}{{{param_str}}}"

            merged = False
            last_cmd = None
            for cmd in reversed(self.commands):
                if not cmd.hidden:
                    last_cmd = cmd
                    break
                    
            if last_cmd is not None:
                if self.separate_strings:
                    m = re.match(r'^#res<(\d+)>$', last_cmd.text)
                    if m:
                        idx = int(m.group(1))
                        if idx == len(self.resstrs) - 1:
                            old_text = self.resstrs[idx]
                            self.resstrs[idx] += ccode_str
                            if not self.options.get('no_smart_resources', True):
                                if self.reshash.get(old_text) == idx:
                                    del self.reshash[old_text]
                                self.reshash[self.resstrs[idx]] = idx
                            merged = True
                else:
                    if last_cmd.text.startswith("'") and last_cmd.text.endswith("'"):
                        last_cmd.text = f"'{last_cmd.text[1:-1]}{ccode_str}'"
                        merged = True

            if merged:
                return None, ptrs, is_jump, pushes_store
                
            if 'textout' in fndef.flags:
                self._add_textout(ccode_str, offset)
                return None, ptrs, is_jump, pushes_store
        # ----------------------------------------

        text = f'{pre}{fndef.ident}({param_str}){ptr_txt}' if param_str else f'{pre}{fndef.ident}{ptr_txt}' if ptr_txt else f'{pre}{fndef.ident}'
        return text, ptrs, is_jump, pushes_store

    def _read_strcpy_strcat(self, r: _Reader, func: int, overload: int) -> tuple[str, set]:
        r.expect(0x28, '_read_strcpy_strcat')
        a, b = self._read_data(r), self._read_data(r)
        if overload == 1:
            c = self._read_data(r)
            r.expect(0x29, '_read_strcpy_strcat')
            return f'strcpy({a}, {b}, {c})', set()
        r.expect(0x29, '_read_strcpy_strcat')
        return f'{a} {"=" if func == 0 else "+="} {b}', set()

    def _read_assignment(self, r: _Reader, offset: int) -> Command:
        try:
            lhs = self._read_expr_token(r)
            b = r.read_byte()
            if b != 0x5c: raise ValueError(f'expected 0x5c, got 0x{b:02x}')
            op_b = r.read_byte()
            return Command(offset=offset, text=f'{lhs} {_ASSIGN_OPS.get(op_b, "=")} {self._read_expression(r)}')
        except (ValueError, struct.error) as e:
            return Command(offset=offset, text=f'[assignment parse error: {e}]')

    def _read_kidoku(self, r: _Reader, offset: int) -> Command:
        b = r.peek()
        if b == 0x21: self.use_excl.append(True)
        r.read_byte()
        idx = r.read_int32() if self.mode == 'avg2000' else r.read_uint16()
        if 0 <= idx < len(self.hdr.kidoku_lnums):
            ep_idx = self.hdr.kidoku_lnums[idx] - 1_000_000
            if ep_idx >= 0:
                return Command(offset=offset, text=f'\n#entrypoint {ep_idx:03d} // Z{ep_idx:02d}\n', hidden=False, unhide=True)
        return Command(offset=offset, text=f'{{- kidoku {idx:03d} -}}', hidden=True)

    def _read_command(self, r: _Reader) -> Command | None:
        if r.eof(): return None
        offset = r.pos
        b = r.read_byte()

        if b == 0x00: return Command(offset=offset, text='halt', is_jump=True)
        if b == 0x23:
            op_type, op_module, op_func, argc, op_overload = r.read_byte(), r.read_byte(), r.read_uint16(), r.read_uint16(), r.read_byte()
            key = (op_type, op_module, op_func, op_overload)
            opstr = f'op<{op_type}:{self.module_names.get(op_module, f"{op_module:03d}")}:{op_func:05d}, {op_overload}>'
            
            pushes_store = False

            if op_module == 1 and op_func == 3: text, ptrs = self._read_goto_on(r, 'to', argc); is_jump = True
            elif op_module == 1 and op_func == 4: text, ptrs = self._read_goto_case(r, 'to', argc); is_jump = True
            elif op_module == 1 and op_func == 8: text, ptrs = self._read_goto_on(r, 'sub', argc); is_jump = False
            elif op_module == 1 and op_func == 9: text, ptrs = self._read_goto_case(r, 'sub', argc); is_jump = False
            elif op_module == 5 and op_func == 3: text, ptrs = self._read_goto_on(r, 'to', argc); is_jump = True
            elif op_module == 5 and op_func == 4: text, ptrs = self._read_goto_case(r, 'to', argc); is_jump = True
            elif op_module == 5 and op_func == 8: text, ptrs = self._read_goto_on(r, 'sub', argc); is_jump = False
            elif op_module == 5 and op_func == 9: text, ptrs = self._read_goto_case(r, 'sub', argc); is_jump = False
            elif op_module == 3 and op_func == 120: 
                self._read_ruby(r, argc, offset)
                return None
            elif op_module == 10 and op_func == 0: text, ptrs = self._read_strcpy_strcat(r, 0, op_overload); is_jump = False
            elif op_module == 10 and op_func == 2: text, ptrs = self._read_strcpy_strcat(r, 2, op_overload); is_jump = False
            
            elif key in self.fndefs: 
                text, ptrs, is_jump, pushes_store = self._read_soft_function(r, key, argc, self.fndefs[key], offset)
                if text is None:
                    return None
            
            elif op_module == 2:
                text, ptrs, is_jump = self._read_select(r, op_func, argc), set(), False
                pushes_store = True
            else: text, ptrs = self._read_unknown_function(r, opstr, argc); is_jump = False
            
            return Command(offset=offset, text=text, is_jump=is_jump, pointers=ptrs, pushes_store=pushes_store)

        if b == 0x24: return self._read_assignment(r, offset)
        if b == 0x0a:
            ln = r.read_int32() if self.mode == 'avg2000' else r.read_int16()
            return Command(offset=offset, text=f'// #line {ln}', hidden=True)
        if b == 0x2c: return Command(offset=offset, text=',', hidden=True)
        if b in (0x40, 0x21):
            r.rollback()
            return self._read_kidoku(r, offset)

        r.rollback()
        text = self._read_textout_str(r)
        if text == "eof":
            return Command(offset=offset, text='eof', is_jump=True)
        if not text:
            return Command(offset=offset, text="''")
        
        self._add_textout(text, offset)
        return None

    def run(self, data: bytes) -> list[Command]:
        r = _Reader(data, start=self.hdr.data_offset, end=min(self.hdr.data_offset + self.hdr.uncompressed_size, len(data)))
        self.commands = []
        self.errors = []
        while not r.eof():
            try:
                cmd = self._read_command(r)
            except (ValueError, struct.error, IndexError) as e:
                self.errors.append((r.pos, str(e)))
                cmd = Command(offset=r.pos, text=f'{{- parse error: {e} -}}', hidden=False)
                if not r.eof(): r.read_byte()
            if cmd is not None:
                self.commands.append(cmd)
        return self.commands

# ---------------------------------------------------------------------------
# Output Writer
# ---------------------------------------------------------------------------

def _apply_labels(text: str, labels: dict[int, int]) -> str:
    def replace(m: re.Match) -> str:
        offset = int(m.group(1), 16)
        return f' @{labels[offset]}' if offset in labels else f' @unknown_{m.group(1)}'
    return _PTR_RE.sub(replace, text)

def _write_output(commands: list[Command], labels: dict[int, int], hdr, fname: str, oc, rc, d: Disassembler, target_encoding: str) -> None:
    annotate = d.options.get('annotate', False)
    data_offset = hdr.data_offset

    oc.write(f"{{-# cp {target_encoding} #- Disassembled with Kprl (Python) -}}\n\n#file '{fname}'\n")

    if oc is not rc:
        rc.write(f'// Resources for {fname}\n\n\n')
        oc.write(f"#resource '{Path(rc.name).name}'\n")

    oc.write('\n')
    if d.mode == 'avg2000': oc.write('#target AVG2000\n')
    if d.use_excl: oc.write('#kidoku_type 2\n')

    for name in hdr.dramatis_personae:
        rc.write(f"#character '{name}'\n")
    if rc is not oc and hdr.dramatis_personae:
        rc.write('\n')
        
    for i, res_str in enumerate(d.resstrs):
        prefix = "\\" if res_str.startswith(' ') or res_str.startswith('\u3000') else ""
        rc.write(f"<{i:04d}> {prefix}{res_str}\n")

    pending_labels = set(labels.keys())
    data_end_offset = hdr.uncompressed_size 

    skipping = False
    for cmd in commands:
        rel_offset = cmd.offset - hdr.data_offset
        if rel_offset in labels:
            oc.write(f'\n  @{labels[rel_offset]}\n')
            pending_labels.discard(rel_offset)
            skipping = False

        if cmd.unhide and skipping: skipping = False
        if not (skipping or cmd.hidden):
            line = _apply_labels(cmd.text, labels)
            if annotate: oc.write(f'{{-{rel_offset + data_offset:08x}-}} ')
            oc.write(f'{line}\n')
            
        if d.options.get('suppress_uncalled', False) and cmd.is_jump:
            skipping = True

    for offset in sorted(pending_labels):
        if offset == data_end_offset:
            oc.write(f'\n  @{labels[offset]}\n')

def disassemble_data(data: bytes | bytearray, fname: str, outdir: str | Path = '.', options: dict | None = None) -> list[Path]:
    if options is None: options = {}
    target_encoding = options.get('encoding', 'utf-8')
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    hdr = bytecode.read_full_header(BinArray(data))
    base = Path(fname).stem
    if base.endswith('.uncompressed'): base = base[:-len('.uncompressed')]
    
    ke_path  = outdir / (base + '.org')
    res_path = outdir / (base + '.utf')

    cached_kfn = options.get('kfn_cache')
    if cached_kfn is not None:
        fndefs_all, module_names = cached_kfn
    else:
        kfn_path = config.Config.lib_file("reallive.kfn")
        if os.path.exists(kfn_path):
            try:
                fndefs_all, module_names = kfn.load_kfn(kfn_path)
            except Exception as e:
                print(f'Warning: could not load {kfn_path}: {e}', file=sys.stderr)
                fndefs_all, module_names = {}, {}
        else:
            print('Warning: reallive.kfn not found; function names will be numeric', file=sys.stderr)
            fndefs_all, module_names = {}, {}

    d = Disassembler(str(outdir), options, hdr, fndefs_all, module_names)
    commands = d.run(data)
    for offset, message in d.errors:
        print(f"Error: {message} near 0x{offset:06x} in {fname}.", file=sys.stderr)

    ptrs = set()
    for cmd in commands:
        for m in _PTR_RE.finditer(cmd.text): ptrs.add(int(m.group(1), 16))
    ptrs.discard(0) 
    labels = {offset: idx + 1 for idx, offset in enumerate(sorted(ptrs))}

    final_commands = []
    for cmd in commands:
        if cmd.text.endswith("store") and ("=" in cmd.text):
            store_idx = -1
            for i in range(len(final_commands)-1, -1, -1):
                if not final_commands[i].hidden and not final_commands[i].is_jump:
                    store_idx = i
                    break
            
            if store_idx != -1 and getattr(final_commands[store_idx], 'pushes_store', False):
                target_cmd = final_commands[store_idx]
                assignment_part = cmd.text[:-5].strip() 
                if target_cmd.text.startswith("store = "):
                    target_cmd.text = f"{assignment_part} {target_cmd.text[8:]}"
                else:
                    target_cmd.text = f"{assignment_part} {target_cmd.text}"
                continue 
                
        final_commands.append(cmd)

    single_file = options.get('single_file', False)
    written = []
    
    with open(ke_path, 'w', encoding=target_encoding) as oc:
        # Even an empty resource string may be referenced by #res<>.
        has_resources = bool(d.resstrs)
        if single_file or not commands or not has_resources:
            rc = oc          # write everything to .org (no separate .utf)
        else:
            rc_file = open(res_path, 'w', encoding=target_encoding)
            rc = rc_file
        try:
            _write_output(final_commands, labels, hdr, f"{base}.TXT", oc, rc, d, target_encoding)
            written.append(ke_path)
            if rc is not oc: written.append(res_path)
        finally:
            if rc is not oc: rc.close()
    return written

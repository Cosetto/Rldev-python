from typing import Any, List

from .ketypes import Location, error, nowhere
from . import codegen
from . import function
from . import global_state
from . import keast
from . import memory
from . import meta
from . import text_encoding

_multi_message_pending = False

def begin_multi_message_payload():
    global _multi_message_pending
    _multi_message_pending = True


def _make_name(prefix: str, idx: int) -> str:
    if idx < 26:
        return prefix + "\x82" + chr(idx + 0x60)
    return prefix + "\x82" + chr(idx // 26 + 0x5f) + "\x82" + chr(idx % 26 + 0x60)


def _string_of_tokens(tokens: List[Any]) -> List[Any]:
    # The expression pass should already have resolved resource-string glosses.
    return tokens


def _call_real_function(loc: Location, funname: str, args: List[Any]):
    params = [("Simple", loc, arg) for arg in args]
    function.compile(("FuncCall", loc, None, funname, funname, params, None))


def finalise():
    if memory.defined("__DynamicLineationUsed__"):
        meta.parse_elt(("VarOrFn", nowhere, "__dynamic_textout_print", "__dynamic_textout_print"))


def compile_stub(tup: tuple):
    global _multi_message_pending
    loc, text, next_cmd = tup
    if text[0] != "Str":
        error(loc, "expected textout to be normalised to string literal")

    raw_multi_message = _multi_message_pending
    _multi_message_pending = False

    tokens = text[2]
    buf: List[str] = []
    quoted = False
    ignore_one_space = False

    def set_quotes(q: bool):
        nonlocal quoted
        if quoted != q:
            quoted = q
            buf.append('"')

    def flush():
        set_quotes(False)
        if buf:
            codegen.Output.add_code(nowhere if raw_multi_message else loc, "".join(buf))
            buf.clear()

    def append_text(s: str):
        if not raw_multi_message:
            set_quotes(True)
        buf.append(text_encoding.text_to_byte_string(s, loc, "textout"))

    def append_sjis_bytes(data: bytes):
        buf.append("".join(chr(b) for b in data))

    def parse_token(idx: int, t: Any):
        nonlocal ignore_one_space
        if ignore_one_space and t[0] != "Space":
            ignore_one_space = False

        tag = t[0]
        if tag in ("EOS", "Delete", "Rewrite", "ResRef"):
            raise AssertionError(tag)
        if tag == "DQuote":
            set_quotes(True)
            buf.append('\\"')
        elif tag == "RCur":
            set_quotes(False)
            append_sjis_bytes(b"\x81\x7a")
            ignore_one_space = True
        elif tag == "LLentic":
            append_sjis_bytes(b"\x81\x79")
        elif tag == "RLentic":
            append_sjis_bytes(b"\x81\x7a")
        elif tag == "Asterisk":
            append_sjis_bytes(b"\x81\x96")
        elif tag == "Percent":
            append_sjis_bytes(b"\x81\x93")
        elif tag == "Speaker":
            set_quotes(False)
            append_sjis_bytes(b"\x81\x79")
        elif tag == "Hyphen":
            append_text("-")
        elif tag == "Text":
            append_text(t[3])
        elif tag == "Space":
            count = t[2]
            if count > 0 and ignore_one_space:
                ignore_one_space = False
                count -= 1
            if count > 0:
                buf.append(" " * count)
        elif tag == "Name":
            _, l, locglob, expr, cidx = t
            set_quotes(False)
            prefix = "\x81\x93" if locglob == "Local" else "\x81\x96"
            try:
                name_idx = keast.int_of_normalised_expr(expr)
            except Exception:
                error(l, "name index must be constant in static text")
            buf.append(_make_name(prefix, name_idx))
            if cidx is not None:
                try:
                    char_idx = keast.int_of_normalised_expr(cidx)
                except Exception:
                    error(l, "name char index must be constant in static text")
                buf.append("\x82" + chr(char_idx + 0x4f))
        elif tag == "Gloss" and t[2] == "Gloss":
            error(t[1], "\\g{} is not implemented in unformatted text")
        elif tag == "Gloss" and t[2] == "Ruby":
            _, _, _, base, gloss = t
            if gloss[0] != "Closed":
                raise AssertionError("ruby gloss should be closed by expression normalisation")
            flush()
            _call_real_function(t[1], "__doruby", [])
            for base_token in base:
                parse_token(idx, base_token)
            flush()
            _call_real_function(t[1], "__doruby", [("Str", nowhere, _string_of_tokens(gloss[2]))])
        elif tag == "Code":
            _, l, ident, e_spec, params = t
            if ident in ("e", "em"):
                if len(params) == 1:
                    emoji_idx, size = params[0][2], None
                elif len(params) == 2:
                    emoji_idx, size = params[0][2], params[1][2]
                else:
                    error(l, f"incorrect parameters to code \\{ident}{{}}")
                try:
                    emoji_val = keast.int_of_normalised_expr(emoji_idx)
                except Exception:
                    error(l, "emoji index must be constant in static text")
                set_quotes(False)
                if size is not None:
                    flush()
                    meta.call("FontSize", [size])
                append_sjis_bytes(bytes([0x81, 0x94, 0x82, 0x60 if len(ident) == 1 else 0x61, 0x82, 0x4f + (emoji_val // 10 if emoji_val > 10 else 0), 0x82, 0x4f + emoji_val % 10]))
                if size is not None:
                    flush()
                    meta.call("FontSize", [])
            else:
                flush()
                if ident == "__line":
                    if e_spec is not None or len(params) != 1 or params[0][0] != "Simple":
                        error(l, r"expected one line number argument to \__line{}")
                    try:
                        line_no = keast.int_of_normalised_expr(params[0][2])
                    except Exception:
                        error(l, r"line number must be constant in \__line{}")
                    codegen.Output.add_line(Location(l.file, line_no), force=True)
                    return
                if e_spec is not None:
                    error(l, f"the control code \\{ident} cannot have a length specifier")
                function.compile(("FuncCall", l, None, ident, ident, params, None), is_code=True)
        elif tag == "Add":
            # Resource string addition is handled by OCaml's recursive textout path.
            # Keep base output valid for now by ignoring the queued addition here.
            pass
        else:
            raise AssertionError(tag)

    if not raw_multi_message:
        codegen.Output.add_kidoku(loc)
        set_quotes(True)
    for idx, token in enumerate(tokens):
        parse_token(idx, token)
    flush()
    if raw_multi_message:
        codegen.Output.add_code(nowhere, "}")

    if next_cmd != "No":
        kind, _ = next_cmd
        meta.call("pause" if kind == "Pause" else "page", [])

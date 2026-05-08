from typing import List, Any
from . import ketypes
from .ketypes import *
from . import codegen
from . import meta
from . import function
from . import memory
from . import keast

token_name_left   = "\x01"
token_name_right  = "\x02"
token_break       = "\x03"
token_setindent   = "\x04"
token_clearindent = "\x05"
token_quote       = "\x08"
token_emphasis    = "\x09"
token_regular     = "\x0a"
token_begingloss  = "\x1f"

def flatten_nested_glosses(rv: list, s: list) -> list:
    for elt in s:
        # Change elt[1] to elt[2] to properly check gloss_type
        if elt[0] == "Gloss" and elt[2] == "Gloss":
            # Unpack 5 elements including loc and type_
            _, loc, type_, tokens, closed_tup = elt
            
            rv.extend(tokens)
            rv.append(("Space", nowhere, 1))
            rv.append(("Text", nowhere, "Sbcs", "("))
            flatten_nested_glosses(rv, closed_tup[2])
            rv.append(("Text", nowhere, "Sbcs", ")"))
        else:
            rv.append(elt)
    return rv

def compile_vwf(tup: tuple, with_kidoku: bool = True, f_start: str = "__vwf_TextoutStart", f_append: str = "__vwf_TextoutAppend", f_display: str = "__vwf_TextoutDisplay"):
    loc, text, next_stmt = tup[0], tup[1], tup[2]
    
    if with_kidoku:
        start_lbl = codegen.unique_label(loc)
        codegen.Output.add_label(start_lbl)
        codegen.Output.add_kidoku(loc)
        meta.call("strout", [("VarOrFn", nowhere, "__rlb_empty", "__rlb_empty")])
        
    b = []
    ignore_one_space = False
    appending = False
    
    def flush(display: bool):
        nonlocal appending
        if display:
            if appending:
                appending = False
                meta.call(f_append, [("Str", nowhere, b.copy())])
                meta.call(f_display, [])
            else:
                meta.call(f_display, [("Str", nowhere, b.copy())])
        else:
            if appending:
                meta.call(f_append, [("Str", nowhere, b.copy())])
            else:
                appending = True
                meta.call(f_start, [("Str", nowhere, b.copy())])
        b.clear()

    def parse(elt):
        nonlocal ignore_one_space
        if ignore_one_space and elt[0] != "Space":
            ignore_one_space = False
            
        if elt[0] in ("EOS", "Delete", "Rewrite", "ResRef"):
            raise AssertionError()
        elif elt[0] == "Add":
            pass # Handled differently in python port or queues
        elif elt[0] in ("Text", "Hyphen", "LLentic", "RLentic"):
            b.append(elt)
        elif elt[0] == "DQuote":
            b.append(("Text", elt[1], "Sbcs", token_quote))
        elif elt[0] == "Space":
            l, i = elt[1], elt[2]
            j = i - 1 if (i > 0 and ignore_one_space) else i
            if ignore_one_space: ignore_one_space = False
            b.append(("Space", l, j))
        elif elt[0] == "RCur":
            b.append(("Text", elt[1], "Sbcs", token_name_right))
            ignore_one_space = True
        elif elt[0] in ("Asterisk", "Percent"):
            b.append(elt)
            flush(True)
        elif elt[0] == "Speaker":
            b.append(("Text", elt[1], "Sbcs", token_name_left))
        elif elt[0] == "Code" and elt[2] in ("e", "em"):
            l, id_, e_spec, params = elt[1], elt[2], elt[3], elt[4]
            idx, size = None, None
            if len(params) == 1:
                idx = params[0][2]
            elif len(params) == 2:
                idx, size = params[0][2], params[1][2]
            else:
                error(l, f"incorrect parameters to code \\{id_}{{}}")
                
            if size:
                flush(True)
                meta.call("FontSize", [size])
                
            b.append(("Text", l, "Dbcs", chr(5 + len(id_)))) # mapped from 5 + Text.length id
            
            try:
                i_val = keast.int_of_normalised_expr(idx)
                b.append(("Text", l, "Sbcs", f"{i_val:02d}"))
            except Exception:
                flush(False)
                memory.open_scope()
                svar = memory.get_temp_str()
                meta.call("itoa", [idx, meta.int_val(2)], rv=svar)
                meta.call(f_append, [svar])
                memory.close_scope()
                
            if size:
                flush(True)
                meta.call("FontSize", [])
                
        elif elt[0] == "Code" and elt[2] == "s":
            l, id_, e_spec, p = elt[1], elt[2], elt[3], elt[4]
            parm = p[0][2]
            if parm[0] != "SVar": error(l, f"Oops, expected string variable but found {parm[0]}")
            if e_spec is not None: error(l, "the control code \\s{} cannot have a length specifier")
            flush(False)
            meta.call(f_append, [parm])
            
        elif elt[0] == "Code" and elt[2] == "i":
            l, id_, e_spec, p = elt[1], elt[2], elt[3], elt[4]
            parm = p[0][2]
            if keast.normalised_expr_is_const(parm):
                val = keast.int_of_normalised_expr(parm)
                padding = keast.int_of_normalised_expr(e_spec) if e_spec else 0
                s = global_state.int32_to_string_padded(padding, val)
                b.append(("Text", l, "Sbcs", s))
            else:
                length_list = [e_spec] if e_spec else []
                flush(False)
                memory.open_scope()
                svar = memory.get_temp_str()
                meta.call("itoa", [parm] + length_list, rv=svar)
                meta.call(f_append, [svar])
                memory.close_scope()
                
        elif elt[0] == "Code" and elt[2] in ("n", "r"):
            l, id_, e_spec, p = elt[1], elt[2], elt[3], elt[4]
            if e_spec is not None: error(l, f"the control code \\{id_} cannot have a length specifier")
            if p: error(l, f"the control code \\{id_} does not take any parameters")
            if id_ == "r": b.append(("Text", l, "Sbcs", token_clearindent))
            b.append(("Text", l, "Sbcs", token_break))
            
        elif elt[0] == "Code" and elt[2] == "b":
            b.append(("Text", elt[1], "Sbcs", token_emphasis))
        elif elt[0] == "Code" and elt[2] == "u":
            b.append(("Text", elt[1], "Sbcs", token_regular))
            
        elif elt[0] == "Code":
            l, id_, e_spec, params = elt[1], elt[2], elt[3], elt[4]
            flush(True)
            if e_spec is not None: error(l, f"the control code \\{id_} cannot have a length specifier")
            function.compile(("FuncCall", l, None, id_, id_, params, None), is_code=True)
            
        elif elt[0] == "Name":
            l, lg, i, w = elt[1], elt[2], elt[3], elt[4]
            lg_str = "\x81\x93" if lg == "Local" else "\x81\x96"
            try:
                i_val = keast.int_of_normalised_expr(i)
            except Exception:
                error(l, "name index must be constant in rlBabel-formatted text")
                
            # Maps to string rendering
            import str_lexer # Make name token
            # Equivalent logic to StrTokens.make_name mapped back into binary 
            b.append(("Text", l, "Dbcs", f"__NAME_{lg}_{i_val}__"))
            if w is not None:
                try:
                    w_val = keast.int_of_normalised_expr(w)
                    b.append(("Text", l, "Dbcs", chr(0x1ff10 + w_val)))
                except Exception:
                    flush(False)
                    memory.open_scope()
                    svar = memory.get_temp_str()
                    meta.call("itoa_w", [w, meta.int_val(2)], rv=svar)
                    meta.call(f_append, [svar])
                    memory.close_scope()
                    
        elif elt[0] == "Gloss" and elt[2] == "Ruby":
            l, tokens = elt[1], elt[3]
            warning(l, "not implemented: \\ruby{} in rlBabel-formatted text")
            for t in tokens: parse(t)
            
        elif elt[0] == "Gloss" and elt[2] == "Gloss":
            l, tokens, str_tup = elt[1], elt[3], elt[4]
            if memory.defined("__EnableGlosses__"):
                gloss_loc, gloss_str = str_tup[1], flatten_nested_glosses([], str_tup[2])
                b.append(("Text", l, "Sbcs", token_begingloss))
                for t in tokens: parse(t)
                flush(True)
                compile_vwf((gloss_loc, gloss_str, None), with_kidoku=False, f_start="__vwf_GlossTextStart", f_append="__vwf_GlossTextAppend", f_display="__vwf_GlossTextSet")
                meta.call("__vwf_EndGloss", [])
            else:
                warning(l, "__EnableGlosses__ not defined - ignoring \\g{}")
                for t in tokens: parse(t)
                
    for t in text:
        parse(t)
    flush(True)
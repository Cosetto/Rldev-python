import os
import sys
from typing import List, Any, Optional

from . import ketypes
from .ketypes import *
from . import config
from . import ini_parser
from .kfn import init as kfn_init
from . import global_state
from . import memory
from . import codegen
from . import expr as expr_mod
from . import func_asm
from . import function
from . import intrinsic
from . import directive
from . import variables
from . import goto
from . import rl_babel
from . import select_stmt
from . import textout
from . import str_lexer
from . import ke_u_lexer
from . import bytecode_gen
from . import app
from . import keast

break_stack: List[str] = []
continue_stack: List[str] = []
_kfn_loaded = False

def _reset_compile_state():
    break_stack.clear()
    continue_stack.clear()

    codegen.Output = codegen.OutputState()

    memory.staticvars = [{} for _ in range(13)]
    memory.symbols.clear()
    memory.scope.clear()
    memory.defines.clear()
    memory.open_scope()

    global_state.dramatis_personae.clear()
    global_state.val_0x2c = 0
    global_state.kidoku_type = 0
    global_state.resources.clear()
    global_state.base_res.clear()
    global_state.gloss_count = 0

    str_lexer.rewrites.clear()
    str_lexer._anon_resstrs = -1

def _ensure_kfn_loaded():
    global _kfn_loaded
    if not _kfn_loaded:
        kfn_init()
        _kfn_loaded = True

def get_ast_of_string(s: str, file: str = "generated code", line: int = -1) -> Any:
    return ke_u_lexer.call_parser_on_text("program", Location(file, line), s)

def get_ast_of_file(file: str) -> Any:
    try:
        with open(file, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        raise IOError(f"Cannot load file {file}: {e}")
        
    return ke_u_lexer.call_parser_on_text("program", Location(os.path.basename(file), 1), text)

def disambiguate(elt: Any) -> Any:
    if elt[0] == "VarOrFn":
        loc, s, t = elt[1], elt[2], elt[3]
        if s in ["pause", "spause", "page"] and not memory.defined("__DynamicLineationUsed__"):
            memory.define("__DynamicLineationUsed__", ("Integer", 1), scoped=False)
            
        if memory.defined(t):
            return ("Hiding", loc, t, memory.get_as_code(id_=t, loc=loc, s=s))
        else:
            return ("FuncCall", loc, None, s, t, [], None)
            
    elif elt[0] == "FuncCall" and elt[2] is None and memory.defined(elt[4]):
        loc, s, t, params = elt[1], elt[3], elt[4], elt[5]
        def mf(p):
            if p[0] == "Simple": return p[2]
            error(p[1], "expected expression as parameter to inline expansion")
        args_mapped = [mf(p) for p in params]
        
        if elt[2] is None:
            return ("Hiding", loc, t, memory.get_as_code(id_=t, loc=loc, s=s, args=args_mapped))
        else:
            return ("Assign", loc, elt[2], "Set", memory.get_as_expression(id_=t, loc=loc, s=s, args=args_mapped))
            
    return elt

def parse(ast: List[Any]):
    for i in range(len(ast)):
        if ast[i][0] == "Select" and ast[i][2][0] == "Store" and i < len(ast) - 1:
            nxt = ast[i + 1]
            if nxt[0] == "Assign" and nxt[3] == "Set" and nxt[4][0] == "Store":
                ast[i] = ("Select", ast[i][1], nxt[2], ast[i][3], ast[i][4], ast[i][5], ast[i][6])
                ast[i + 1] = ("Null",)

        elt = disambiguate(ast[i])
        if elt[0] == "Return" and not elt[2]:
            next_cmd = "No"
            if i < len(ast) - 1:
                nxt = ast[i+1]
                if nxt[0] == "FuncCall" and nxt[2] is None and not nxt[5]:
                    if nxt[4] == "pause": next_cmd = ("Pause", nxt[1])
                    elif nxt[4] == "page": next_cmd = ("Page", nxt[1])
                elif nxt[0] == "VarOrFn":
                    if nxt[3] == "pause": next_cmd = ("Pause", nxt[1])
                    elif nxt[3] == "page": next_cmd = ("Page", nxt[1])
            
            if next_cmd != "No":
                ast[i+1] = ("Null",)
                if not memory.defined("__DynamicLineationUsed__"):
                    memory.define("__DynamicLineationUsed__", ("Integer", 1), scoped=False)
                    
            handle_textout(next_cmd, elt)
        elif elt[0] == "Null":
            continue
        else:
            parse_elt(elt)

def handle_textout(next_cmd: Any, elt: Any):
    ret = expr_mod.normalise(elt)
    if ret[0] == "Single" and ret[1][0] == "Return":
        ret_val = ret[1][3]
    elif ret[0] == "Multiple":
        elts = ret[1]
        last = elts[-1]
        elts.pop()
        parse(elts)
        memory.close_scope()
        ret_val = last[3] if last[0] == "Return" else last
    else:
        raise AssertionError("Unhandled return in handle_textout")

    if keast.type_of_normalised_expr(ret_val) == "int":
        error(elt[1], "textout expressions must be strings. If you did not intend this expression to be displayed, you should precede it with the 'return' keyword")
        
    if not memory.defined("__DynamicLineation__") or memory.get_as_expression("__DynamicLineation__") == ("Int", nowhere, 0):
        textout.compile_stub((elt[1], ret_val, next_cmd))
    else:
        if memory.defined("__TEXTOUT_KH__"):
            pass
        elif memory.defined("__RLBABEL_KH__"):
            select_stmt.compile_vwf(elt)
        else:
            error(elt[1], "__DynamicLineation__ defined, but no recognised dynamic lineation library loaded")

def parse_elt(elt: Any):
    disambiguated = disambiguate(elt)
    
    if disambiguated[0] in ("Seq", "Hiding", "Block", "If", "While", "Repeat", "For", "Case", "DFor", "DIf"):
        parse_struct(disambiguated)
        return
        
    if disambiguated[0] == "Return" and not disambiguated[2]:
        handle_textout("No", disambiguated)
        return
        
    norm = expr_mod.normalise(disambiguated)
    if norm[0] == "Nothing":
        pass
    elif norm[0] == "Single":
        parse_norm_elt(norm[1])
    elif norm[0] == "Multiple":
        elts = norm[1]
        last = elts[-1]
        elts.pop()
        for e in elts:
            parse_norm_elt(e)
        if last[0] in ("LoadFile", "DConst", "Define"):
            memory.close_scope()
            parse_norm_elt(last)
        else:
            parse_norm_elt(last)
            memory.close_scope()

def parse_struct(s: Any):
    if s[0] == "Seq":
        parse(s[1])
    elif s[0] == "Hiding":
        loc, t, e = s[1], s[2], s[3]
        try:
            sym = memory.pull_sym(t)
        except KeyError:
            error(loc, f"cannot hide '{t}': symbol not defined")
        memory.define("__INLINE_CALL__", ("Macro", ("Int", nowhere, 0)), scoped=False)
        memory.define("__CALLER_FILE__", ("Macro", ("Str", nowhere, [("Text", nowhere, "Sbcs", loc.file)])), scoped=False)
        memory.define("__CALLER_LINE__", ("Macro", ("Int", nowhere, loc.line)), scoped=False)
        parse_elt(e)
        memory.undefine(nowhere, "__INLINE_CALL__", "__INLINE_CALL__")
        memory.undefine(nowhere, "__CALLER_FILE__", "__CALLER_FILE__")
        memory.undefine(nowhere, "__CALLER_LINE__", "__CALLER_LINE__")
        memory.replace_sym(t, sym)
    elif s[0] == "Block":
        memory.open_scope()
        parse(s[2])
        memory.close_scope()
    elif s[0] == "If":
        loc, e, smt, elsesmt = s[1], s[2], s[3], s[4]
        lendif = codegen.unique_label(nowhere)
        lelse = lendif if elsesmt is None else codegen.unique_label(nowhere)
        try:
            val = expr_mod.normalise_and_get_int(e, abort_on_fail=False)
            if val != 0: parse_elt(smt)
            elif elsesmt is not None: parse_elt(elsesmt)
        except Exception:
            parse_elt(("FuncCall", nowhere, None, "goto_unless", "goto_unless", [("Simple", loc, e)], lelse))
            parse_elt(smt)
            if elsesmt is not None:
                parse_elt(("FuncCall", nowhere, None, "goto", "goto", [], lendif))
                parse_elt(("Label", lelse))
                parse_elt(elsesmt)
            parse_elt(("Label", lendif))
    elif s[0] == "While":
        loc, e, smt = s[1], s[2], s[3]
        loop_lbl = codegen.unique_label(nowhere)
        skip_lbl = codegen.unique_label(nowhere)
        break_stack.append(skip_lbl)
        continue_stack.append(loop_lbl)
        parse_elt(("Label", loop_lbl))
        parse_elt(("FuncCall", nowhere, None, "goto_unless", "goto_unless", [("Simple", nowhere, e)], skip_lbl))
        parse_elt(smt)
        parse_elt(("FuncCall", nowhere, None, "goto", "goto", [], loop_lbl))
        parse_elt(("Label", skip_lbl))
        break_stack.pop()
        continue_stack.pop()
    elif s[0] == "Case":
        loc, e, ofs, other = s[1], s[2], s[3], s[4]
        if not ofs:
            parse_elt(("Assign", loc, ("Store", nowhere), "Set", e))
            if other is not None:
                skip_lbl = codegen.unique_label(nowhere)
                break_stack.append(skip_lbl)
                memory.define("__ConstantCase__", ("Macro", ("Int", nowhere, 1)), warnings=False)
                parse(other)
                memory.undefine(nowhere, "__ConstantCase__", "__ConstantCase__")
                parse_elt(("Label", skip_lbl))
                break_stack.pop()
        else:
            skip_lbl = codegen.unique_label(nowhere)
            break_stack.append(skip_lbl)
            selected = None
            is_constant_case = False
            try:
                select_value = expr_mod.normalise_and_get_int(e, abort_on_fail=False)
                for match_expr, smts in ofs:
                    if expr_mod.normalise_and_get_int(match_expr, abort_on_fail=False) == select_value:
                        selected = smts
                        break
                is_constant_case = True
            except Exception:
                pass

            if is_constant_case:
                selected_stmts = None
                if selected is not None:
                    selected_idx = next(i for i, (_, smts) in enumerate(ofs) if smts is selected)
                    selected_stmts = []
                    for _, case_stmts in ofs[selected_idx:]:
                        case_list = list(case_stmts)
                        if case_list and case_list[-1][0] == "Break":
                            selected_stmts.extend(case_list[:-1])
                            break
                        selected_stmts.extend(case_list)
                    else:
                        if other is not None:
                            selected_stmts.extend(other)
                elif other is not None:
                    selected_stmts = list(other)
                else:
                    error(loc, f"unable to find a case matching {select_value}, and no other clause was given")

                memory.define("__ConstantCase__", ("Macro", ("Int", nowhere, 1)), warnings=False)
                parse(selected_stmts)
                memory.undefine(nowhere, "__ConstantCase__", "__ConstantCase__")
                parse_elt(("Label", skip_lbl))
                break_stack.pop()
                return

            olbl = skip_lbl if other is None else codegen.unique_label(nowhere)
            cases = [("Default", olbl)]
            if other is not None:
                cases_stmts = [("Label", olbl)] + other
            else:
                cases_stmts = []
                
            for match_expr, smts in reversed(ofs):
                l = codegen.unique_label(nowhere)
                cases.insert(0, ("Match", match_expr, l))
                cases_stmts = [("Label", l)] + smts + cases_stmts
                
            memory.define("__ConstantCase__", ("Macro", ("Int", nowhere, 0)), warnings=False)
            parse_elt(("GotoCase", loc, ("goto_case", "goto_case"), e, cases))
            for c_stmt in cases_stmts:
                parse_elt(c_stmt)
            memory.undefine(nowhere, "__ConstantCase__", "__ConstantCase__")
            parse_elt(("Label", skip_lbl))
            break_stack.pop()
    elif s[0] == "DIf":
        loc, e, iftrue, iffalse = s[1], s[2], s[3], s[4]
        try:
            val = expr_mod.normalise_and_get_int(e, abort_on_fail=True)
            cond = (val != 0)
        except Exception:
            cond = False
            
        if not cond:
            if iffalse[0] == "DEndif": pass
            elif iffalse[0] == "DElse": parse(iffalse[2])
            elif iffalse[0] == "DIf": parse_struct(iffalse)
        else:
            parse(iftrue)
    elif s[0] == "Repeat":
        loc, smts, e = s[1], s[2], s[3]
        loop_lbl = codegen.unique_label(nowhere)
        skip_lbl = codegen.unique_label(nowhere)
        cont_lbl = codegen.unique_label(nowhere)
        
        break_stack.append(skip_lbl)
        continue_stack.append(cont_lbl)
        memory.open_scope()
        
        parse_elt(("Label", loop_lbl))
        parse_elt(("Seq", smts))
        parse_elt(("Label", cont_lbl))
        parse_elt(("FuncCall", nowhere, None, "goto_unless", "goto_unless", [("Simple", loc, e)], loop_lbl))
        parse_elt(("Label", skip_lbl))
        
        memory.close_scope()
        break_stack.pop()
        continue_stack.pop()
        
    elif s[0] == "For":
        loc, pre, e, inc, smt = s[1], s[2], s[3], s[4], s[5]
        loop_lbl = codegen.unique_label(nowhere)
        skip_lbl = codegen.unique_label(nowhere)
        
        break_stack.append(skip_lbl)
        continue_stack.append(loop_lbl)
        memory.open_scope()
        
        parse_elt(("Seq", pre))
        parse_elt(("Label", loop_lbl))
        parse_elt(("FuncCall", nowhere, None, "goto_unless", "goto_unless", [("Simple", loc, e)], skip_lbl))
        
        body = ("Seq", smt[1]) if smt[0] == "Block" else smt
        parse_elt(body)
        parse_elt(("Seq", inc))
        parse_elt(("FuncCall", nowhere, None, "goto", "goto", [], loop_lbl))
        parse_elt(("Label", skip_lbl))
        
        memory.close_scope()
        break_stack.pop()
        continue_stack.pop()
        
    elif s[0] == "DFor":
        loc, s_str, t, start, finish, smt = s[1], s[2], s[3], s[4], s[5], s[6]
        start_val = expr_mod.normalise_and_get_int(start)
        finish_val = expr_mod.normalise_and_get_int(finish)
        
        step = 1 if finish_val >= start_val else -1
        for i in range(start_val, finish_val + step, step):
            memory.define(t, ("Macro", ("Int", loc, i)), loc=loc)
            parse_elt(smt)
            memory.undefine(loc, s_str, t)

def parse_norm_elt(elt: Any):
    if elt[0] == "Null": raise AssertionError()
    if elt[0] == "Return": pass
    if elt[0] in ("VarOrFn", "Seq", "Hiding", "Block", "If", "While", "Repeat", "For", "Case", "DFor", "DIf"): raise AssertionError()
    
    if elt[0] == "Decl":
        variables.allocate(elt)
    elif elt[0] in ("Directive", "DTarget", "Define", "DConst", "DInline", "DUndef", "DSet", "DVersion"):
        directive.compile_directive(elt)
    elif elt[0] == "Halt":
        codegen.Output.add_code(elt[1], "\000")
    elif elt[0] == "Break":
        try:
            parse_elt(("FuncCall", nowhere, None, "goto", "goto", [], break_stack[-1]))
        except IndexError:
            error(elt[1], "break outside breakable structure")
    elif elt[0] == "Continue":
        try:
            parse_elt(("FuncCall", nowhere, None, "goto", "goto", [], continue_stack[-1]))
        except IndexError:
            error(elt[1], "continue outside loop")
    elif elt[0] == "Label":
        codegen.Output.add_label(elt[1])
    elif elt[0] == "GotoOn":
        goto.goto_on(elt)
    elif elt[0] == "GotoCase":
        goto.goto_case(elt)
    elif elt[0] == "Assign":
        codegen.Output.add_code(elt[1], codegen.code_of_assignment(elt))
    elif elt[0] == "FuncCall":
        l, d, s, t, p, lbl = elt[1], elt[2], elt[3], elt[4], elt[5], elt[6]
        if intrinsic.is_builtin(t):
            parse_elt(intrinsic.eval_as_code((l, d, s, t, p, lbl)))
        else:
            function.compile(elt)
    elif elt[0] == "Select":
        dynalin = "__DynamicLineation__"
        if not memory.defined(dynalin) or memory.get_as_expression(dynalin) == ("Int", nowhere, 0) or memory.defined("__TEXTOUT_KH__"):
            select_stmt.compile(elt)
        elif memory.defined("__RLBABEL_KH__"):
            rl_babel.compile_vwf(elt)
        else:
            error(elt[1], "__DynamicLineation__ defined, but no recognised dynamic lineation library loaded")
    elif elt[0] == "UnknownOp":
        function.compile_unknown(elt)
    elif elt[0] == "LoadFile":
        file_val = "".join([t[3] for t in global_state.expr__normalise_and_get_str(elt[2]) if t[0] == "Text"])
        
        # Build path fallbacks
        prefixes = [
            file_val, 
            f"{file_val}.kh", 
            os.path.join(config.Config.init_prefix(), file_val), 
            os.path.join(config.Config.init_prefix(), f"{file_val}.kh"),
            os.path.join(config.Config.init_prefix(), "lib", file_val),
            os.path.join(config.Config.init_prefix(), "lib", f"{file_val}.kh")
        ]
        ast = None
        for p in prefixes:
            if os.path.exists(p):
                ast = get_ast_of_file(p)
                break
        if ast:
            parse_elt(ast)
        else:
            error(elt[1], f"Cannot load '{file_val}'")
    elif elt[0] == "RawCode":
        for c in elt[2]:
            if c[0] == "Bytes": codegen.Output.add_code(elt[1], c[1])
            elif c[0] == "Int": codegen.Output.add_code(elt[1], codegen.code_of_int32(c[1]))
            elif c[0] == "Ident": error(elt[1], "not implemented: anything to do with identifiers in raw blocks")

def compile(file: str):
    _reset_compile_state()

    fdir = os.path.dirname(file)
    fname = os.path.basename(file)
    srcdir = "." if fname == "-" else fdir
    if not app.outdir: app.outdir = srcdir

    _ensure_kfn_loaded()

    ini_parser.init(srcdir, app.verbose, app.gameexe)
    
    ast = []
    
    macro_def = f"#define __RLC__,\n__Optimisation__ = {app.opt_level},\n__Compiler__ = '{app.name}',\n__RlcVersion__ = {int(app.version * 100)}\n"
    if not app.debug_info: macro_def += ", __NoDebug__"
    if not app.assertions: macro_def += ", __NoAssert__"
    if app.array_bounds: macro_def += ", __SafeArrays__"
    
    ast.append(get_ast_of_string(macro_def))
    
    if app.verbose > 0: ketypes.cli_info("Loading Kepago/RealLive RTL")
    sys_kh = config.Config.lib_file("system.kh")
    if os.path.exists(sys_kh):
        ast.append(get_ast_of_file(sys_kh))

    oldcwd = os.getcwd()
    if app.resdir and not os.path.isabs(app.resdir):
        app.resdir = os.path.join(oldcwd, app.resdir)
        
    os.chdir(srcdir if srcdir else ".")
    
    bname = os.path.splitext(fname)[0]
    if len(bname) == 8 and bname[:4].lower() == "seen":
        idx = int(bname[4:8])
        nam = f"global{idx:04d}.kh"
        if os.path.exists(nam):
            if app.verbose > 0: ketypes.cli_info("Loading seen header")
            ast.append(get_ast_of_file(nam))
        elif os.path.exists("global.kh"):
            if app.verbose > 0: ketypes.cli_info("Loading project header")
            ast.append(get_ast_of_file("global.kh"))

    if app.verbose > 0: ketypes.cli_info("Lexing and parsing")
    
    if fname == "-":
        pass # Stdin logic
    else:
        ast.append(get_ast_of_file(fname))

    if app.verbose > 0: ketypes.cli_info("Compiling")
    
    global_state.compilerFrame__parse = parse
    for a in ast:
        parse([a])

    textout.finalise()

    if app.debug_info:
        codegen.Output.add_code(nowhere,
            b"\x82\x72\x82\x85\x82\x85\x82\x8e\x82\x64\x82\x8e\x82\x84\xff\xff\xff\xff\xff"
            b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
            b"\xff\xff\xff\xff\xff\xff\xff\xff"
        )
    else:
        codegen.Output.add_code(nowhere, b"\x00")

    assert len(memory.scope) == 1

    os.chdir(oldcwd)
    
    if app.verbose > 0: ketypes.cli_info("Assembling")
    bytecode_gen.generate()
    if app.verbose > 0: ketypes.cli_info("")

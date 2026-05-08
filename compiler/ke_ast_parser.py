from typing import List, Tuple, Any, Optional
from . import ketypes
from .ketypes import *
from . import ke_u_lexer
from . import keast

class KeAstParser:
    def __init__(self, lexer_state: ke_u_lexer.KeULexerState):
        self.lexer = lexer_state
        self.current_token, self.current_loc = ke_u_lexer.get_token(self.lexer)

    def advance(self):
        self.current_token, self.current_loc = ke_u_lexer.get_token(self.lexer)

    def check(self, *tok_types: str) -> bool:
        return self.current_token[0] in tok_types

    def accept(self, tok_type: str) -> bool:
        if self.check(tok_type):
            self.advance()
            return True
        return False

    def expect(self, tok_type: str) -> Any:
        if self.check(tok_type):
            val = self.current_token[1]
            self.advance()
            return val
        error(self.current_loc, f"expected {tok_type}, got {self.current_token[0]}")

    # Entry points
    def program(self):
        stmts = self.statements()
        if not self.check("EOF", "DEOF"):
            error(self.current_loc, "expected EOF")
        return ("Seq", stmts)

    def just_statements(self):
        stmts = self.statements()
        if not self.check("EOF", "DEOF"):
            error(self.current_loc, "expected EOF")
        return stmts

    def just_expression(self):
        e = self.expr()
        if not self.check("EOF", "DEOF"):
            error(self.current_loc, "expected EOF")
        return e

    def just_param_list(self):
        p = self.clist(self.fn_param)
        if not self.check("EOF", "DEOF"):
            error(self.current_loc, "expected EOF")
        return p

    def statements(self) -> List[Any]:
        stmts = []
        stop_tokens = {
            "EOF", "DEOF", "RCUR", "SEMI", "ECASE", "OTHER", 
            "TILL", "DELSE", "DELSEIF", "DENDIF", "OF"
        }
        while self.current_token[0] not in stop_tokens:
            self.accept("COMMA")
            if self.current_token[0] in stop_tokens:
                break
            stmts.append(self.statement())
        return stmts

    def statement(self):
        loc = self.current_loc
        if self.accept("IF"):
            cond = self.expr()
            if self.check("COMMA"): self.advance()
            whentrue = self.statement()
            if self.accept("ELSE"):
                whenfalse = self.statement()
                return ("If", loc, cond, whentrue, whenfalse)
            return ("If", loc, cond, whentrue, None)

        if self.accept("WHILE"):
            cond = self.expr()
            if self.check("COMMA"): self.advance()
            body = self.statement()
            return ("While", loc, cond, body)

        if self.accept("FOR"):
            self.expect("LPAR")
            init = ("Seq", self.statements())
            if self.check("SEMI"): self.advance()
            elif self.check("RPAR") and self.lexer.peek() == '(': self.advance(); self.advance()
            cond = self.expr()
            if self.check("SEMI"): self.advance()
            elif self.check("RPAR") and self.lexer.peek() == '(': self.advance(); self.advance()
            incr = ("Seq", self.statements())
            self.expect("RPAR")
            if self.check("COMMA"): self.advance()
            body = self.statement()
            return ("For", loc, init, cond, incr, body)

        if self.accept("DFOR"):
            ident = self.expect("IDENT")
            self.expect("SET")
            init = self.expr()
            self.expect("POINT"); self.expect("POINT")
            fini = self.expr()
            body = self.statement()
            return ("DFor", loc, ident[0], ident[1], init, fini, body)

        if self.check("DINLINE"):
            itype = self.expect("DINLINE")
            ident = self.expect("IDENT")
            self.expect("LPAR")
            parms = self.clist(self.inline_elt)
            self.expect("RPAR")
            body = self.statement()
            return ("DInline", loc, ident[0], ident[1], itype, parms, body)

        if self.accept("DHIDING"):
            ident = self.expect("IDENT")
            if self.check("COMMA"): self.advance()
            body = self.statement()
            return ("Hiding", loc, ident[1], body)
            
        if self.accept("COLON"):
            body = self.statements()
            self.expect("SEMI")
            return ("Block", loc, body)

        if self.accept("REPEAT"):
            body = self.statements()
            self.expect("TILL")
            cond = self.expr()
            return ("Repeat", loc, body, cond)

        if self.accept("CASE"):
            sel = self.expr()
            ofs = []
            while self.accept("OF"):
                val = self.expr()
                if self.check("COMMA"): self.advance()
                b = self.statements()
                ofs.append((val, b))
            other = self.statements() if self.accept("OTHER") else None
            self.expect("ECASE")
            return ("Case", loc, sel, ofs, other)

        if self.accept("DIF"):
            cond = self.expr()
            body = self.statements()
            chain = self.condelseorend()
            return ("DIf", loc, cond, body, chain)

        if self.check("DIFDEF"):
            is_ifdef = self.expect("DIFDEF")
            defs = self.expr()
            body = self.statements()
            chain = self.condelseorend()
            
            def leaf_map(leaf):
                if isinstance(leaf, tuple) and leaf[0] == "VarOrFn":
                    f = ("Func", leaf[1], "defined?", "defined?", [("Simple", leaf[1], leaf)], None)
                    return f if is_ifdef else ("Unary", nowhere, "Not", f)
                return leaf
                
            defs_mapped = keast.map_expr_leaves(leaf_map, defs)
            return ("DIf", loc, defs_mapped, body, chain)

        # other_statement
        if self.check("LABEL"):
            l = self.expect("LABEL")
            if self.check("COMMA"): self.advance()
            return ("Label", (loc, l[0], l[1]))
        if self.accept("DHALT"): return ("Halt", loc)
        if self.accept("BREAK"): return ("Break", loc)
        if self.accept("CONTINUE"): return ("Continue", loc)
        if self.accept("RETURN"): return ("Return", loc, True, self.expr())
        if self.accept("RAW"):
            elts = []
            while not self.check("ENDRAW", "EOF"):
                if self.check("IDENT"): elts.append(("Ident", self.expect("IDENT")))
                elif self.check("INTEGER"): elts.append(("Int", self.expect("INTEGER")))
                elif self.accept("COMMA"): elts.append(("Bytes", ","))
                elif self.accept("LPAR"): elts.append(("Bytes", "("))
                elif self.accept("RPAR"): elts.append(("Bytes", ")"))
                elif self.accept("LCUR"): elts.append(("Bytes", "{"))
                elif self.accept("RCUR"): elts.append(("Bytes", "}"))
                elif self.accept("LSQU"): elts.append(("Bytes", "["))
                elif self.accept("RSQU"): elts.append(("Bytes", "]"))
                elif self.check("REG", "VAR", "SVAR"): 
                    tok_type = self.current_token[0]
                    val = self.current_token[1]
                    self.advance()
                    elts.append(("Bytes", chr(val)))
                else: error(self.current_loc, "invalid raw element")
            self.expect("ENDRAW")
            return ("RawCode", loc, elts)
            
        if self.check("OP"): return self.unknown_op()
        if self.check("GO_LIST", "GO_CASE"): return self.gotofunction()
        
        # Directives
        if self.check("DWITHEXPR"):
            dir_val = self.expect("DWITHEXPR")
            return ("Directive", loc, dir_val[0], dir_val[1], self.expr())
        if self.accept("DLOAD"): return ("LoadFile", loc, self.expr())
        if self.accept("DTARGET"): return ("DTarget", loc, self.expect("IDENT")[1])
        if self.accept("DVERSION"):
            v = self.clist(self.expr, sep="POINT")
            nil = ("Int", nowhere, 0)
            a, b, c, d = v[0], v[1] if len(v)>1 else nil, v[2] if len(v)>2 else nil, v[3] if len(v)>3 else nil
            return ("DVersion", loc, a, b, c, d)
        if self.accept("DUNDEF"):
            idents = self.clist(lambda: self.expect("IDENT"))
            return ("DUndef", loc, [(self.current_loc, i[0], i[1]) for i in idents])
        if self.check("DDEFINE"):
            dir_type = self.expect("DDEFINE")
            idents = self.clist(self.idelt)
            seq = []
            for l, (id_str, id_text), val_opt in idents:
                if dir_type in ("Define", "DefineScoped"):
                    seq.append(("Define", l, id_str, id_text, dir_type == "DefineScoped", val_opt or ("Int", nowhere, 1)))
                elif dir_type in ("Const", "Bind", "EBind"):
                    if not val_opt: error(l, f"cannot define '{id_str}' without an initial value")
                    seq.append(("DConst", l, id_str, id_text, dir_type, val_opt))
                elif dir_type == "Redefine":
                    if not val_opt: error(l, f"cannot redefine '{id_str}' without a new value")
                    seq.append(("DSet", l, id_str, id_text, False, val_opt))
            return ("Seq", seq)
        if self.accept("DSET"):
            idents = self.clist(self.setelt)
            seq = []
            for l, (id_str, id_text), op, val in idents:
                expr = val if op == "Set" else ("Op", l, ("VarOrFn", l, id_str, id_text), op, val)
                seq.append(("DSet", l, id_str, id_text, True, expr))
            return ("Seq", seq)

        # Declarations
        if self.check("INT", "STR"):
            vtype = ("Int", self.expect("INT")) if self.check("INT") else ("Str",) if self.accept("STR") else None
            dirs = []
            if self.accept("LPAR"):
                dirs = self.clist(lambda: self.expect("IDENT"))
                self.expect("RPAR")
            variables = self.clist(self.variable_decl)
            mapped_vars = []
            for v in variables:
                v_loc, v_id, v_arr, v_init = v
                mapped_vars.append((v_loc, v_id[0], v_id[1], v_arr, v_init[0], v_init[1]))
            return ("Decl", loc, vtype, dirs, mapped_vars)

        # Assignment / Top Expr
        expr = self.top_expr()
        if self.check("SADD", "SSUB", "SMUL", "SDIV", "SMOD", "SAND", "SOR", "SXOR", "SSHL", "SSHR", "SET"):
            op_map = {"SADD": "Add", "SSUB": "Sub", "SMUL": "Mul", "SDIV": "Div", "SMOD": "Mod", "SAND": "And", "SOR": "Or", "SXOR": "Xor", "SSHL": "Shl", "SSHR": "Shr", "SET": "Set"}
            op = op_map[self.current_token[0]]
            self.advance()
            return ("Assign", loc, expr, op, self.expr())
            
        match expr:
            case ("VarOrFn", _, _, _): return expr
            case ("Func", l, s, t, p, d): return ("FuncCall", l, None, s, t, p, d)
            case ("SelFunc", l, s, i, w, p): return ("Select", l, ("Store", l), s, i, w, p)
            case _: return ("Return", loc, False, expr)

    def condelseorend(self):
        if self.accept("DENDIF"): return ("DEndif", self.current_loc)
        if self.accept("DELSE"): return ("DElse", self.current_loc, self.statements(), self.expect("DENDIF"))
        if self.accept("DELSEIF"): return ("DIf", self.current_loc, self.expr(), self.statements(), self.condelseorend())

    def inline_elt(self):
        loc = self.current_loc
        if self.accept("LSQU"):
            ident = self.expect("IDENT")
            self.expect("RSQU")
            return (loc, ident[0], ident[1], "Optional")
        ident = self.expect("IDENT")
        if self.accept("SET"): return (loc, ident[0], ident[1], ("Some", self.expr()))
        return (loc, ident[0], ident[1], "None")

    def idelt(self):
        loc = self.current_loc
        if self.accept("LSQU"):
            ident = self.expect("IDENT"); self.expect("RSQU")
            return (loc, ident, "Optional")
        ident = self.expect("IDENT")
        if self.accept("SET"): return (loc, ident, self.expr())
        return (loc, ident, None)

    def setelt(self):
        loc = self.current_loc
        ident = self.expect("IDENT")
        if self.check("SADD", "SSUB", "SMUL", "SDIV", "SMOD", "SAND", "SOR", "SXOR", "SSHL", "SSHR", "SET"):
            op_map = {"SADD": "Add", "SSUB": "Sub", "SMUL": "Mul", "SDIV": "Div", "SMOD": "Mod", "SAND": "And", "SOR": "Or", "SXOR": "Xor", "SSHL": "Shl", "SSHR": "Shr", "SET": "Set"}
            op = op_map[self.current_token[0]]
            self.advance()
            return (loc, ident, op, self.expr())
        error(loc, f"cannot mutate '{ident[0]}' without a new value")

    def variable_decl(self):
        loc = self.current_loc
        ident = self.expect("IDENT")
        array = "None"
        if self.accept("LSQU"):
            if self.accept("RSQU"):
                array = "Auto"
            else:
                array = ("Some", self.expr())
                self.expect("RSQU")
        
        ad = None
        vd = "None"
        
        if self.accept("ARROW"):
            e1 = self.expr()
            self.expect("POINT")
            e2 = self.expr()
            ad = (e1, e2)
        elif self.accept("SET"):
            param = self.fn_param()
            if param[0] == "Simple": vd = ("Scalar", param[2])
            elif param[0] == "Complex": vd = ("Array", param[2])
            else: error(loc, "Parse error in valdecl")
            
        if ad is None and self.accept("ARROW"):
            e1 = self.expr()
            self.expect("POINT")
            e2 = self.expr()
            ad = (e1, e2)
            
        if vd == "None" and self.accept("SET"):
            param = self.fn_param()
            if param[0] == "Simple": vd = ("Scalar", param[2])
            elif param[0] == "Complex": vd = ("Array", param[2])
            else: error(loc, "Parse error in valdecl")
            
        return (loc, ident, array, (vd, ad))

    def unknown_op(self):
        loc = self.current_loc
        self.expect("OP")
        self.expect("LTN")
        op_type = self.expect("INTEGER")
        
        def expect_sep():
            if self.current_token[0] in ("COLON", "COMMA", "POINT", "SEMI", "SUB", "DIV"):
                self.advance()
            else:
                error(self.current_loc, f"expected separator, got {self.current_token[0]}")
        
        expect_sep()
        op_module = self.expect("INTEGER") if self.check("INTEGER") else self.expect("IDENT")[1]
        expect_sep()
        op_code = self.expect("INTEGER")
        expect_sep()
        op_over = self.expect("INTEGER")
        self.expect("GTN")
        
        params = []
        if self.accept("LPAR"):
            params = self.clist(self.fn_param)
            self.expect("RPAR")
            
        id_str = ketypes.ident_of_opcode(op_type, op_module if isinstance(op_module, int) else 0, op_code, op_over)
        if id_str in ketypes.functions:
            return ("FuncCall", loc, None, id_str, id_str, params, None)
        def_op = ketypes.FuncDef(id_str, [], op_type, op_module if isinstance(op_module, int) else 0, op_code, [], [])
        return ("UnknownOp", loc, def_op, op_over, params)

    def gotofunction(self):
        loc = self.current_loc
        if self.check("GO_LIST"):
            func = self.expect("GO_LIST")
            sel = self.expr()
            self.expect("LCUR")
            labels = self.clist(lambda: self.expect("LABEL"))
            self.expect("RCUR")
            return ("GotoOn", loc, func, sel, [(loc, l[0], l[1]) for l in labels])
        if self.check("GO_CASE"):
            func = self.expect("GO_CASE")
            sel = self.expr()
            self.expect("LCUR")
            cases = self.clist(self.case, sep="SEMI")
            self.accept("SEMI") # Optional trailing
            self.expect("RCUR")
            return ("GotoCase", loc, func, sel, cases)

    def case(self):
        if self.accept("USCORE"):
            self.expect("COLON")
            l = self.expect("LABEL")
            return ("Default", (self.current_loc, l[0], l[1]))
        cond = self.expr()
        self.expect("COLON")
        l = self.expect("LABEL")
        return ("Match", cond, (self.current_loc, l[0], l[1]))

    
    PRECEDENCE = {
        "LOR": 1, "LAND": 2, 
        "EQU": 3, "NEQ": 3, "LTE": 3, "LTN": 3, "GTE": 3, "GTN": 3,
        "OR": 4, "XOR": 4, "AND": 4,
        "ADD": 5, "SUB": 5,
        "MUL": 6, "DIV": 6, "MOD": 6,
        "SHL": 7, "SHR": 7
    }
    
    OP_MAP = {
        "LOR": "LOr", "LAND": "LAnd", "EQU": "Equ", "NEQ": "Neq", "LTE": "Lte", "LTN": "Ltn", "GTE": "Gte", "GTN": "Gtn",
        "OR": "Or", "XOR": "Xor", "AND": "And", "ADD": "Add", "SUB": "Sub", "MUL": "Mul", "DIV": "Div", "MOD": "Mod",
        "SHL": "Shl", "SHR": "Shr"
    }

    def expr(self, min_prec=0):
        loc = self.current_loc
        # Parse Unary or Leaf
        if self.check("SUB", "NOT", "TILDE"):
            op = {"SUB": "Sub", "NOT": "Not", "TILDE": "Inv"}[self.current_token[0]]
            self.advance()
            left = ("Unary", loc, op, self.expr(8)) # UNARY prec
        else:
            left = self.leaf_expr()

        # Parse Binary
        while True:
            tok_type = self.current_token[0]
            if tok_type not in self.PRECEDENCE or self.PRECEDENCE[tok_type] < min_prec:
                break
            prec = self.PRECEDENCE[tok_type]
            op = self.OP_MAP[tok_type]
            op_loc = self.current_loc
            self.advance()
            right = self.expr(prec + 1) # Left-associative
            
            node_type = "LogOp" if op in ("Equ", "Neq", "Lte", "Ltn", "Gte", "Gtn") else "AndOr" if op in ("LOr", "LAnd") else "Op"
            left = (node_type, op_loc, left, op, right)

        return left

    def top_expr(self):
        e = self.expr()
        if self.accept("ADD"):
            return ("Op", self.current_loc, e, "Add", self.expr(6))
        return e

    def leaf_expr(self):
        loc = self.current_loc
        if self.check("STRING"): return ("Str", loc, self.expect("STRING"))
        if self.check("DRES"): return ("Res", loc, self.expect("DRES"))
        if self.check("INTEGER"): return ("Int", loc, self.expect("INTEGER"))
        if self.accept("LPAR"):
            e = self.expr()
            self.expect("RPAR")
            return ("Parens", loc, e)
            
        # Variables and Functions
        if self.accept("REG"): return ("Store", loc)
        if self.check("VAR"):
            v = self.expect("VAR")
            self.expect("LSQU"); e = self.expr(); self.expect("RSQU")
            return ("IVar", loc, v, e)
        if self.check("SVAR"):
            v = self.expect("SVAR")
            self.expect("LSQU"); e = self.expr(); self.expect("RSQU")
            return ("SVar", loc, v, e)
            
        if self.check("IDENT"):
            ident = self.expect("IDENT")
            if self.accept("LSQU"):
                e = self.expr()
                self.expect("RSQU")
                return ("Deref", loc, ident[0], ident[1], e)
            if self.accept("LPAR"):
                args = self.clist(self.fn_param)
                self.expect("RPAR")
                return ("Func", loc, ident[0], ident[1], args, None)
            return ("VarOrFn", loc, ident[0], ident[1])
            
        if self.check("GOTO"):
            func = self.expect("GOTO")
            args = []
            if self.accept("LPAR"):
                args = self.clist(self.fn_param)
                self.expect("RPAR")
            l = self.expect("LABEL")
            return ("Func", loc, func[0], func[1], args, (loc, l[0], l[1]))
            
        if self.check("SELECT"):
            func = self.expect("SELECT")
            wind = None
            if self.accept("LSQU"):
                wind_args = [self.expr()]
                while self.accept("COMMA"):
                    wind_args.append(self.expr())
                wind = wind_args if len(wind_args) > 1 else wind_args[0]
                self.expect("RSQU")
            args = []
            if self.accept("LPAR"):
                args = self.clist(self.sel_param)
                self.expect("RPAR")
            return ("SelFunc", loc, func[0], func[1], wind, args)
            
        error(loc, f"unexpected token in expression: {self.current_token[0]}")

    def fn_param(self):
        loc = self.current_loc
        if self.accept("LCUR"):
            p = self.clist(self.expr)
            self.expect("RCUR")
            return ("Complex", loc, p)
        return ("Simple", loc, self.expr())

    def sel_cond_rest(self):
        loc = self.current_loc
        e = self.expr()
        if self.accept("IF"):
            cond = self.expr()
            if e[0] == "Func" and len(e[4]) == 1 and e[4][0][0] == "Simple" and e[5] is None:
                return ("Cond", loc, e[2], e[3], e[4][0][2], cond)
            elif e[0] == "VarOrFn":
                return ("Cond", loc, e[2], e[3], None, cond)
            else:
                error(loc, "Parse error in sel_cond")
        else:
            if e[0] == "Func" and len(e[4]) == 1 and e[4][0][0] == "Simple" and e[5] is None:
                return ("NonCond", loc, e[2], e[3], e[4][0][2])
            elif e[0] == "VarOrFn":
                return ("Flag", loc, e[2], e[3])
            else:
                error(loc, "Parse error in sel_cond")

    def sel_param(self):
        loc = self.current_loc
        e = self.expr()
        
        if self.accept("IF"):
            cond = self.expr()
            if e[0] == "Func" and len(e[4]) == 1 and e[4][0][0] == "Simple" and e[5] is None:
                c = ("Cond", loc, e[2], e[3], e[4][0][2], cond)
            elif e[0] == "VarOrFn":
                c = ("Cond", loc, e[2], e[3], None, cond)
            else:
                error(loc, "Parse error in sel_cond")
                
            conds = [c]
            while self.accept("SEMI"):
                conds.append(self.sel_cond_rest())
            self.expect("COLON")
            return ("Special", loc, conds, self.expr())
            
        elif self.accept("SEMI"):
            if e[0] == "Func" and len(e[4]) == 1 and e[4][0][0] == "Simple" and e[5] is None:
                c = ("NonCond", loc, e[2], e[3], e[4][0][2])
            elif e[0] == "VarOrFn":
                c = ("Flag", loc, e[2], e[3])
            else:
                error(loc, "Parse error in sel_cond")
                
            conds = [c]
            while True:
                conds.append(self.sel_cond_rest())
                if not self.accept("SEMI"):
                    break
            self.expect("COLON")
            return ("Special", loc, conds, self.expr())
            
        elif self.accept("COLON"):
            if e[0] == "Func" and len(e[4]) == 1 and e[4][0][0] == "Simple" and e[5] is None:
                c = ("NonCond", loc, e[2], e[3], e[4][0][2])
            elif e[0] == "VarOrFn":
                c = ("Flag", loc, e[2], e[3])
            else:
                error(loc, "Parse error in sel_cond")
                
            return ("Special", loc, [c], self.expr())
            
        else:
            return ("Always", loc, e)

    def clist(self, func, sep="COMMA"):
        res = []
        if self.check("RPAR", "RCUR", "EOF"): return res
        res.append(func())
        while self.accept(sep):
            res.append(func())
        return res

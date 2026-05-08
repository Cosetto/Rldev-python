import os
from typing import Any, List, Optional, Tuple

from .ketypes import Location, error, warning, nowhere
from . import app
from . import expr as expr_mod
from . import keast
from . import memory
from . import meta


def _dir_name(d: Any) -> str:
    if isinstance(d, tuple):
        return str(d[1]).lower()
    return str(d).lower()


def _has_dir(directives: List[Any], name: str) -> bool:
    return any(_dir_name(d) == name for d in directives)


def _get_elements(var: tuple) -> int:
    loc, str_id, _, array_length, init_value, _ = var
    if array_length == "None":
        return 1
    if array_length == "Auto":
        if isinstance(init_value, tuple) and init_value[0] == "Array":
            if not init_value[1]:
                error(loc, f"`{str_id}[]' must either be given an explicit length, or the initial value array must contain at least one element")
            return len(init_value[1])
        error(loc, f"array `{str_id}[]' must be given a length, either explicitly or by providing an initial value array")
    if isinstance(array_length, tuple) and array_length[0] == "Some":
        try:
            return expr_mod.normalise_and_get_int(array_length[1], abort_on_fail=False)
        except Exception:
            error(keast.loc_of_expr(array_length[1]), f"array length for `{str_id}[]' must evaluate to a constant integer")
    raise AssertionError(f"unknown array length node {array_length!r}")


def _get_block_size(vartype: tuple, elt_count: int) -> int:
    if vartype[0] == "Str":
        return elt_count
    bits = vartype[1]
    return (elt_count * bits - 1) // 32 + 1


def _find_block(loc: Location, space: int, first: int, length: int, max_idx: Optional[int] = None) -> int:
    try:
        vidx = memory.varidx(space)
    except KeyError:
        error(loc, f"cannot allocate variables in block 0x{space:02x}")
    idx = memory.find_unused_block(loc, memory.staticvars[vidx], first, length)
    if max_idx is not None and idx + length > max_idx:
        error(loc, "unable to allocate block")
    return idx


def _get_address(loc: Location, vartype: tuple, str_id: str, block_size: int, fixed_address: Any) -> Tuple[int, int]:
    if fixed_address is None:
        if vartype[0] == "Str":
            space, first, max_idx = memory.temp_str_spc(), memory.temp_str_min(), memory.temp_str_max()
        else:
            space, first, max_idx = memory.temp_int_spc(), memory.temp_int_min(), memory.temp_int_max()
        return space, _find_block(loc, space, first, block_size, max_idx)

    sp, addr = fixed_address
    try:
        return (
            expr_mod.normalise_and_get_int(sp, abort_on_fail=False),
            expr_mod.normalise_and_get_int(addr, abort_on_fail=False),
        )
    except Exception:
        error(keast.loc_of_expr(sp), f"fixed address for {str_id} must evaluate to a pair of constant integers")


def _get_real_address(vartype: tuple, space: int, address: int, address_is_access: bool) -> Tuple[int, int, int]:
    if vartype[0] == "Int" and vartype[1] == 1:
        typed_space, eltmod = space + 26, 32
    elif vartype[0] == "Int" and vartype[1] == 2:
        typed_space, eltmod = space + 52, 16
    elif vartype[0] == "Int" and vartype[1] == 4:
        typed_space, eltmod = space + 78, 8
    elif vartype[0] == "Int" and vartype[1] == 8:
        typed_space, eltmod = space + 104, 4
    else:
        typed_space, eltmod = space, 1

    if address_is_access:
        return typed_space, address, address // eltmod
    return typed_space, address * eltmod, address


def _setrng(fn: str, str_id: str, txt_id: str, vartype: tuple, first: int, length: int, init: Any = None):
    lhs_type = "SVar" if vartype[0] == "Str" else "IVar"
    args = [
        ("Deref", nowhere, str_id, txt_id, ("Int", nowhere, first)),
        ("Deref", nowhere, str_id, txt_id, ("Int", nowhere, length - 1)),
    ]
    if init is not None:
        args.append(init)
    meta.call(fn, args)


def _write_flag_labels(variables: list, spaces_addresses_counts: list):
    if not app.flag_labels:
        return
    fn = os.path.join(os.path.dirname(app.gameexe), "flag.ini")
    with open(fn, "a", encoding="utf-8") as fh:
        for (_, str_id, _, array_length, _, _), (_, typed_space, _, access_address, elt_count, _) in zip(variables, spaces_addresses_counts):
            label = str_id if array_length == "None" else f"{str_id}[{elt_count}]"
            fh.write(f"{keast.variable_name(typed_space, prefix=False)}[{access_address}]:0:{label}\n")


def allocate(decl: tuple):
    _, loc, vartype, directives, variables = decl
    if not variables:
        raise AssertionError("empty declaration")

    is_block = _has_dir(directives, "block")
    is_zero = _has_dir(directives, "zero")
    is_str = vartype[0] == "Str"
    elements = [_get_elements(v) for v in variables]

    spaces_addresses_counts = []
    if is_block:
        elt_total = sum(elements)
        block_size = _get_block_size(vartype, elt_total)
        fixed_address = variables[0][5]
        for var in variables[1:]:
            if var[5] is not None:
                error(var[0], "when the `block' directive is specified, only the first variable in a declaration may have an address specifier")
        space, base_address = _get_address(loc, vartype, "block allocation", block_size, fixed_address)
        memory.allocate_block(loc, space, base_address, block_size)

        if vartype[0] == "Int" and vartype[1] == 1:
            address = base_address * 32
        elif vartype[0] == "Int" and vartype[1] == 2:
            address = base_address * 16
        elif vartype[0] == "Int" and vartype[1] == 4:
            address = base_address * 8
        elif vartype[0] == "Int" and vartype[1] == 8:
            address = base_address * 4
        else:
            address = base_address

        elt_accum = 0
        for elt_count in elements:
            blocks_required = _get_block_size(vartype, elt_count)
            typed_space, access_address, alloc_address = _get_real_address(vartype, space, address + elt_accum, True)
            spaces_addresses_counts.append((space, typed_space, alloc_address, access_address, elt_count, blocks_required))
            elt_accum += elt_count
    else:
        for var, elt_count in zip(variables, elements):
            vloc, str_id, _, _, _, fixed_addr = var
            blocks_required = _get_block_size(vartype, elt_count)
            space, address = _get_address(vloc, vartype, str_id, blocks_required, fixed_addr)
            typed_space, access_address, alloc_address = _get_real_address(vartype, space, address, fixed_addr is not None)
            memory.allocate_block(vloc, space, alloc_address, blocks_required)
            spaces_addresses_counts.append((space, typed_space, alloc_address, access_address, elt_count, blocks_required))

    scoped = not _has_dir(directives, "ext")
    for var, item in zip(variables, spaces_addresses_counts):
        _, _, txt_id, array_length, _, _ = var
        space, typed_space, alloc_address, access_address, elt_count, blocks_required = item
        memory.define(
            txt_id,
            ("StaticVar", typed_space, access_address, elt_count if array_length != "None" else None, memory.varidx(space), alloc_address, blocks_required),
            scoped=scoped,
        )

    if _has_dir(directives, "label") or _has_dir(directives, "labelled") or memory.check_def("__AllLabelled__")():
        _write_flag_labels(variables, spaces_addresses_counts)

    for var, elt_count in zip(variables, elements):
        vloc, str_id, txt_id, array_length, init_value, _ = var
        is_array = array_length != "None"

        if init_value == "None":
            if not is_zero:
                continue
            if not is_str and not is_array:
                meta.assign(("VarOrFn", nowhere, str_id, txt_id), "Set", meta.zero)
            elif is_str and not is_array:
                meta.call("strclear", [("VarOrFn", nowhere, str_id, txt_id)])
            elif not is_str:
                _setrng("setrng", str_id, txt_id, vartype, 0, elt_count)
            else:
                _setrng("strclear", str_id, txt_id, vartype, 0, elt_count)

        elif isinstance(init_value, tuple) and init_value[0] == "Scalar":
            init_expr = init_value[1]
            if not is_array:
                meta.assign(("VarOrFn", nowhere, str_id, txt_id), "Set", init_expr)
            elif is_str:
                memory.open_scope()
                idx = memory.get_temp_int()
                meta.parse([
                    ("For", nowhere,
                     ("Seq", [("Assign", nowhere, idx, "Set", meta.zero)]),
                     ("LogOp", nowhere, idx, "Ltn", meta.int_val(elt_count)),
                     ("Seq", [("Assign", nowhere, idx, "Add", meta.int_val(1))]),
                     ("Assign", nowhere, ("Deref", nowhere, str_id, txt_id, idx), "Set", init_expr)),
                ])
                memory.close_scope()
            else:
                _setrng("setrng", str_id, txt_id, vartype, 0, elt_count, init_expr)

        elif isinstance(init_value, tuple) and init_value[0] == "Array":
            init_values = init_value[1]
            if len(init_values) > elt_count:
                error(vloc, f"too many values supplied to initialise {str_id}[]")
            if is_str:
                for i, init_expr in enumerate(init_values):
                    meta.assign(("Deref", nowhere, str_id, txt_id, meta.int_val(i)), "Set", init_expr)
            else:
                meta.call("setarray", [("Deref", nowhere, str_id, txt_id, meta.zero)] + init_values)

            if len(init_values) < elt_count:
                if is_zero:
                    _setrng("strclear" if is_str else "setrng", str_id, txt_id, vartype, len(init_values), elt_count)
                else:
                    warning(vloc, f"not enough values supplied for {str_id}[]: the last {elt_count - len(init_values)} elements will hold undefined values")

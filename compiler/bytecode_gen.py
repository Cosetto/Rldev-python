import time
import struct, os
from typing import Tuple, List, Dict, Any

from . import ketypes
from .ketypes import *
from . import global_state
from . import codegen
from . import app
from . import config
from . import text_encoding
from .binarray import BinArray
from .rlcmp import _lz_compress_raw, apply_mask

def code_to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    out = bytearray()
    for ch in value:
        o = ord(ch)
        if o <= 0xff:
            out.append(o)
        else:
            out.extend(text_encoding.encode_text(ch, context="bytecode"))
    return bytes(out)

def build_metadata_string(enc: str, target_version: Tuple[int, int, int, int]) -> bytes:
    ident = b"RLdev"
    ver_int = int(round(app.version * 100))
    
    transform_byte = b'\x00'
    if enc == 'CHINESE': transform_byte = b'\x01'
    elif enc == 'WESTERN': transform_byte = b'\x02'
    elif enc == 'KOREAN': transform_byte = b'\x03'
    
    a, b, c, d = target_version
    target_bytes = bytes([a, b, c, d])
    
    core = struct.pack('<I', len(ident)) + ident + b'\x00' + struct.pack('<I', ver_int) + target_bytes + transform_byte
    return struct.pack('<I', len(core) + 4) + core

def create_reallive(bytecode: bytes, bytecode_length: int, compressed_length: int, entrypoints: List[int], kidoku_table: List[int], compiler_version: int) -> Tuple[bytearray, int]:
    dramatis_table = bytearray()
    if app.debug_info:
        for s in global_state.dramatis_personae:
            encoded = text_encoding.encode_text(s, context="character name")
            dramatis_table.extend(struct.pack('<I', len(encoded) + 1))
            dramatis_table.extend(encoded)
            dramatis_table.append(0)

    metadata_bytes = build_metadata_string(text_encoding.metadata_transform_name(), ketypes.global_version) if app.metadata else b''
    
    dramatis_offset = 0x1d0 + len(kidoku_table) * 4
    bytecode_offset = dramatis_offset + len(dramatis_table) + len(metadata_bytes)
    
    file_length = compressed_length + len(dramatis_table) + len(metadata_bytes) + len(kidoku_table) * 4 + 0x1d0
    file_buf = bytearray(file_length)
    
    struct.pack_into('<I', file_buf, 0x00, 0x1d0 if app.compress else int.from_bytes(b"KPRL", "little"))
    struct.pack_into('<I', file_buf, 0x04, compiler_version)
    struct.pack_into('<I', file_buf, 0x08, 0x1d0) # Offset of kidoku_table
    struct.pack_into('<I', file_buf, 0x0c, len(kidoku_table))
    struct.pack_into('<I', file_buf, 0x10, len(kidoku_table) * 4) # table_1 size
    struct.pack_into('<I', file_buf, 0x14, dramatis_offset)
    struct.pack_into('<I', file_buf, 0x18, len(global_state.dramatis_personae) if app.debug_info else 0)
    struct.pack_into('<I', file_buf, 0x1c, len(dramatis_table))
    struct.pack_into('<I', file_buf, 0x20, bytecode_offset)
    struct.pack_into('<I', file_buf, 0x24, bytecode_length)
    struct.pack_into('<I', file_buf, 0x28, compressed_length)
    struct.pack_into('<I', file_buf, 0x2c, global_state.val_0x2c) # Z-1
    struct.pack_into('<I', file_buf, 0x30, global_state.val_0x2c + 3) # Z-2
    
    for i, v in enumerate(entrypoints):
        struct.pack_into('<I', file_buf, 0x34 + i * 4, v)
        
    file_buf[0x1c4:0x1c4+12] = b'\x00' * 12
    
    for i, v in enumerate(kidoku_table):
        struct.pack_into('<I', file_buf, 0x1d0 + i * 4, v)
        
    if app.debug_info:
        file_buf[dramatis_offset:dramatis_offset+len(dramatis_table)] = dramatis_table
    if app.metadata:
        file_buf[dramatis_offset+len(dramatis_table):dramatis_offset+len(dramatis_table)+len(metadata_bytes)] = metadata_bytes
        
    return file_buf, bytecode_offset

def create_avg2000(bytecode: bytes, bytecode_length: int, compressed_length: int, entrypoints: List[int], kidoku_table: List[int], compiler_version: int) -> Tuple[bytearray, int]:
    file_length = bytecode_length + len(kidoku_table) * 4 + 0x1cc
    file_buf = bytearray(file_length)
    bytecode_offset = 0x1cc + len(kidoku_table) * 4
    
    struct.pack_into('<I', file_buf, 0x00, 0x1cc if app.compress else int.from_bytes(b"KP2K", "little"))
    struct.pack_into('<I', file_buf, 0x04, 10002)
    
    tm = time.localtime()
    struct.pack_into('<H', file_buf, 0x08, tm.tm_year)
    struct.pack_into('<H', file_buf, 0x0a, tm.tm_mon)
    struct.pack_into('<H', file_buf, 0x0c, (tm.tm_wday + 1) % 7) # Adjust wday mapping
    struct.pack_into('<H', file_buf, 0x0e, tm.tm_mday)
    struct.pack_into('<H', file_buf, 0x10, tm.tm_hour)
    struct.pack_into('<H', file_buf, 0x12, tm.tm_min)
    struct.pack_into('<H', file_buf, 0x14, tm.tm_sec)
    file_buf[0x16:0x16+10] = b'\x00' * 10
    
    struct.pack_into('<I', file_buf, 0x20, len(kidoku_table))
    struct.pack_into('<I', file_buf, 0x24, bytecode_length)
    struct.pack_into('<I', file_buf, 0x28, global_state.val_0x2c) # Z-1
    struct.pack_into('<I', file_buf, 0x2c, global_state.val_0x2c + 5) # Z-2
    
    for i, v in enumerate(entrypoints):
        struct.pack_into('<I', file_buf, 0x30 + i * 4, v)
        
    file_buf[0x1c0:0x1c0+12] = b'\x00' * 12
    
    for i, v in enumerate(kidoku_table):
        struct.pack_into('<I', file_buf, 0x1cc + i * 4, v)
        
    return file_buf, bytecode_offset

def generate():
    tgt = ketypes.global_target
    is_avg2k = (tgt == 'avg2000')
    kidoku_len = 4 if is_avg2k else 2
    lineno_len = 4 if is_avg2k else 2
    kidoku_to_str = ketypes.str_of_int if is_avg2k else ketypes.str16_of_int
    lineno_to_str = ketypes.str_of_int if is_avg2k else ketypes.str16_of_int
    use_lz77 = not is_avg2k
    create_file = create_avg2000 if is_avg2k else create_reallive

    entrypoints = [-1] * 100
    for idx, elt in enumerate(codegen.Output.bytecode):
        if elt[0] == "Entrypoint":
            i = elt[1]
            if entrypoints[i] != -1:
                codegen.Output.bytecode[entrypoints[i]] = ("Code", b"")
            entrypoints[i] = idx

    labels = {}
    ep_array = [0] * 100
    kidoku_table = []
    
    acc = 0
    for elt in codegen.Output.bytecode:
        if elt[0] == "Code":
            acc += len(code_to_bytes(elt[1]))
        elif elt[0] == "LabelRef":
            acc += 4
        elif elt[0] == "Label":
            labels[elt[1]] = acc
        elif elt[0] == "Kidoku":
            kidoku_table.append(elt[1] if app.debug_info else 0)
            acc += 1 + kidoku_len
        elif elt[0] == "Entrypoint":
            ep_array[elt[1]] = acc
            kidoku_table.append(elt[1] + 1_000_000)
            acc += 1 + kidoku_len
        elif elt[0] == "Lineref":
            acc += 1 + lineno_len

    bytecode_length = acc
    buffer_len = (bytecode_length * 9 // 8 + 9) if use_lz77 else (bytecode_length + 9)
    buffer = bytearray(buffer_len)
    
    ct = global_state.kidoku_type
    ct = ct if ct > 0 else 2 if ketypes.global_version > (1, 2, 5, 0) else 1
    entrypoint_char = b'!' if ct == 2 else b'@'

    kidoku_idx = 0
    idx = 8
    
    for elt in codegen.Output.bytecode:
        if elt[0] == "Code":
            b = code_to_bytes(elt[1])
            buffer[idx:idx+len(b)] = b
            idx += len(b)
        elif elt[0] == "LabelRef":
            loc, t = elt[1], elt[2]
            if t not in labels:
                error(loc, f"reference to undefined label @{t}")
            struct.pack_into('<I', buffer, idx, labels[t])
            idx += 4
        elif elt[0] == "Label":
            pass
        elif elt[0] == "Kidoku":
            b = b'@' + kidoku_to_str(kidoku_idx)
            buffer[idx:idx+len(b)] = b
            kidoku_idx += 1
            idx += 1 + kidoku_len
        elif elt[0] == "Entrypoint":
            b = entrypoint_char + kidoku_to_str(kidoku_idx)
            buffer[idx:idx+len(b)] = b
            kidoku_idx += 1
            idx += 1 + kidoku_len
        elif elt[0] == "Lineref":
            b = b'\x0a' + lineno_to_str(elt[1])
            buffer[idx:idx+len(b)] = b
            idx += 1 + lineno_len

    if app.compress:
        if use_lz77:
            if app.verbose > 0: ketypes.cli_info("Compressing and encrypting")
            
            raw_bc = bytearray(buffer[8:8+bytecode_length])
            compressed_block = _lz_compress_raw(raw_bc)
            compressed_length = len(compressed_block) + 8
            
            # Pack the 8-byte RL buffer header explicitly
            struct.pack_into('<I', buffer, 0, compressed_length)
            struct.pack_into('<I', buffer, 4, bytecode_length)
            buffer[8:8+len(compressed_block)] = compressed_block
            
            bytecode_bytes = bytearray(buffer[:compressed_length])
            apply_mask(bytecode_bytes, 0)
            bytecode_bytes = bytes(bytecode_bytes)
        else:
            if app.verbose > 0: ketypes.cli_info("Encrypting")
            bytecode_bytes = bytearray(buffer[8:8+bytecode_length])
            
            apply_mask(bytecode_bytes, 0)
            compressed_length = bytecode_length
            bytecode_bytes = bytes(bytecode_bytes)
    else:
        compressed_length = bytecode_length
        bytecode_bytes = bytes(buffer[8:8+bytecode_length])

    if app.verbose > 0: ketypes.cli_info("Writing output")
    file_buf, bytecode_offset = create_file(bytecode_bytes, bytecode_length, compressed_length, ep_array, kidoku_table, ketypes.compiler_version)
    file_buf[bytecode_offset:bytecode_offset+compressed_length] = bytecode_bytes
    
    if app.outfile == "-":
        import sys
        sys.stdout.buffer.write(file_buf)
    else:
        fname = "rlas_output" if not app.outfile else app.outfile.rsplit('.', 1)[0]
        ext = ".TXT" if app.compress else ".TXT.rl"
        out_path = f"{app.outdir}/{fname}{ext}" if app.outdir else f"{fname}{ext}"
        try:
            import os
            if app.outdir and not os.path.exists(app.outdir):
                os.makedirs(app.outdir, 0o750)
            with open(out_path, 'wb') as f:
                f.write(file_buf)
        except Exception as e:
            ketypes.cli_error(str(e))

from __future__ import annotations

import ctypes
from pathlib import Path

_DLL = None
_LOAD_ERROR: Exception | None = None


def _load():
    global _DLL, _LOAD_ERROR
    if _DLL is not None or _LOAD_ERROR is not None:
        return _DLL

    dll_path = Path(__file__).resolve().parent / "lib" / "lzcomp.dll"
    try:
        dll = ctypes.CDLL(str(dll_path))
        dll.rldev_free.argtypes = [ctypes.c_void_p]
        dll.rldev_free.restype = None
        dll.rldev_apply_mask.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        dll.rldev_apply_mask.restype = ctypes.c_int
        dll.rldev_lz_decompress.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        dll.rldev_lz_decompress.restype = ctypes.c_int
        dll.rldev_lz_compress.argtypes = dll.rldev_lz_decompress.argtypes
        dll.rldev_lz_compress.restype = ctypes.c_int
        _DLL = dll
    except Exception as exc:
        _LOAD_ERROR = exc
    return _DLL


def available() -> bool:
    return _load() is not None


def apply_mask(data: bytearray, offset: int) -> bool:
    dll = _load()
    if dll is None:
        return False
    if not data:
        return True
    buf = (ctypes.c_uint8 * len(data)).from_buffer(data)
    return dll.rldev_apply_mask(buf, len(data), offset) == 0


def _call_allocating(func_name: str, data: bytes | bytearray) -> bytes | None:
    dll = _load()
    if dll is None:
        return None

    src = bytes(data)
    if src:
        src_buf = (ctypes.c_uint8 * len(src)).from_buffer_copy(src)
        src_ptr = src_buf
    else:
        src_buf = None
        src_ptr = ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_uint8))

    out_ptr = ctypes.c_void_p()
    out_len = ctypes.c_size_t()
    func = getattr(dll, func_name)
    rc = func(src_ptr, len(src), ctypes.byref(out_ptr), ctypes.byref(out_len))
    if rc != 0:
        if out_ptr.value:
            dll.rldev_free(out_ptr)
        return None
    try:
        return ctypes.string_at(out_ptr, out_len.value)
    finally:
        dll.rldev_free(out_ptr)


def lz_decompress(data: bytes | bytearray) -> bytes | None:
    return _call_allocating("rldev_lz_decompress", data)


def lz_compress(data: bytes | bytearray) -> bytes | None:
    return _call_allocating("rldev_lz_compress", data)

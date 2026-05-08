import os
import struct
import sys
from typing import List, Tuple, Dict, Optional

from .binarray import BinArray
from . import rlcmp
from . import bytecode
from . import game

EMPTY_ARC = b"\x00Empty RealLive archive"

class Archiver:
    @staticmethod
    def get_subfile_info(arr: BinArray, idx: int) -> Tuple[int, int]:
        """Reads the offset and length of file `idx` from the 80,000-byte header."""
        if arr.dim() >= 24 and arr.read(0, 24).startswith(EMPTY_ARC):
            return 0, 0
        offset = arr.get_int32(idx * 8)
        length = arr.get_int32(idx * 8 + 4)
        return offset, length

    @staticmethod
    def seen_count(arr: BinArray) -> int:
        """Counts the number of valid bytecode files inside the archive."""
        if arr.dim() >= 24 and arr.read(0, 24).startswith(EMPTY_ARC):
            return 0
        if arr.dim() < 80000:
            return -1

        count = 0
        for i in range(10000):
            pos, length = Archiver.get_subfile_info(arr, i)
            if length == 0:
                continue
            if pos + length <= arr.dim() and bytecode.is_bytecode(arr, pos):
                count += 1
            else:
                return -1 if count == 0 else -count
        return count

    @staticmethod
    def try_extract(arr: BinArray, verbose: bool = False, fname: str = "") -> Tuple[bool, bytearray]:
        magic = arr.read(0, 4)
        if bytecode.uncompressed_header(magic):
            return False, bytearray(arr.data)
        else:
            if verbose:
                print(f"Decompressing {fname}...")
                
            current_game = game.get_current_game()
            game_keys = current_game.keys if current_game else []
                
            final_data = rlcmp.decompress_file(arr.data, game_keys=game_keys)
            
            return True, bytearray(final_data)

    @staticmethod
    def extract_archive(arc_path: str, outdir: str, extract_list: List[int], decompress: bool = True):
        arr = BinArray.from_file(arc_path)
        count = Archiver.seen_count(arr)
        if count == -1:
            print(f"Error: {arc_path} is not a valid RealLive archive", file=sys.stderr)
            return

        if not os.path.exists(outdir):
            os.makedirs(outdir)

        print(f"Extracting from {arc_path} ({count} files found)...")
        
        for i in range(10000):
            if extract_list and i not in extract_list:
                continue

            pos, length = Archiver.get_subfile_info(arr, i)
            if length > 0:
                fname = f"SEEN{i:04d}.TXT"
                sub_data = arr.read(pos, length)
                
                if decompress:
                    sub_arr = BinArray(sub_data)
                    was_compressed, final_data = Archiver.try_extract(sub_arr, True, fname)
                    ext = ".rl" if not was_compressed else ".uncompressed"
                    out_name = os.path.join(outdir, f"SEEN{i:04d}{ext}")
                else:
                    final_data = sub_data
                    out_name = os.path.join(outdir, fname)

                with open(out_name, 'wb') as f:
                    f.write(final_data)

    @staticmethod
    def pack_archive(arc_path: str, files_to_add: Dict[int, str]):
        """Packs a list of compiled SEEN files back into a Seen.txt container."""
        header_size = 80000
        
        if os.path.exists(arc_path):
            arr = BinArray.from_file(arc_path)
            if Archiver.seen_count(arr) == -1:
                print(f"Error: {arc_path} is not a valid RealLive archive", file=sys.stderr)
                return
        else:
            arr = BinArray(b'\x00' * header_size)

        new_arc = bytearray(b'\x00' * header_size)
        current_offset = header_size
        
        current_game = game.get_current_game()
        game_keys = current_game.keys if current_game else []
        
        for i in range(10000):
            if i in files_to_add:
                with open(files_to_add[i], 'rb') as f:
                    file_data = f.read()
                
                if bytecode.uncompressed_header(file_data[0:4]):
                    file_data = rlcmp.compress(file_data, game_keys=game_keys)

                length = len(file_data)
                struct.pack_into('<II', new_arc, i * 8, current_offset, length)
                new_arc.extend(file_data)
                current_offset += length
            else:
                old_offset, old_length = Archiver.get_subfile_info(arr, i)
                if old_length > 0:
                    old_data = arr.read(old_offset, old_length)
                    struct.pack_into('<II', new_arc, i * 8, current_offset, old_length)
                    new_arc.extend(old_data)
                    current_offset += old_length

        with open(arc_path, 'wb') as f:
            f.write(new_arc)
        print(f"Archive {arc_path} rebuilt successfully.")

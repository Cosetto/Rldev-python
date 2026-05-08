import argparse
import sys
import os
import glob

from decompiler import config
from decompiler import game
from decompiler.archiver import Archiver
from decompiler import binarray
from decompiler import disassembler
from decompiler import kfn

def setup_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kprl",
        description="RealLive archiver and disassembler (Python Port by Cosetto)",
        epilog="Usage: kprl [options] <files or ranges>"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-d", "--disassemble", action="store_true", help="disassemble RealLive bytecode")
    group.add_argument("-x", "--extract", action="store_true", help="extract and decompress files")
    group.add_argument("-b", "--break-arc", action="store_true", help="extract files without decompressing them")
    group.add_argument("-c", "--compress", action="store_true", help="compress files without archiving them")
    group.add_argument("-a", "--add", action="store_true", help="add to or update files in archive")
    group.add_argument("-l", "--list", action="store_true", help="list archive contents")

    parser.add_argument("-o", "--outdir", default=".", help="place output files in DIR")
    parser.add_argument("-e", "--encoding", default="UTF-8", help="output text encoding")
    parser.add_argument("-s", "--single-file", action="store_true", help="don't put text into a separate resource file")
    parser.add_argument("-Z", "--separate-all", action="store_true", help="put all Japanese text in the resource file")
    parser.add_argument("-G", "--game", default="LB", help="Game ID (LB, CFV, FIVE, SNOW)")

    parser.add_argument("files", nargs="+", help="Files or archive ranges to process. Prefix range with '!' to exclude.")
    return parser

def main():
    parser = setup_argparser()
    args = parser.parse_args()

    expanded_files = []
    for f in args.files:
        if '*' in f or '?' in f:
            expanded_files.extend(glob.glob(f))
        else:
            expanded_files.append(f)
    args.files = expanded_files

    config.Config.init_prefix()

    game_cfg_path = config.Config.lib_file("game.cfg")
    if os.path.exists(game_cfg_path):
        game.load_games_file(game_cfg_path)
    game.set_current_game(args.game)

    kfn_cache = None
    kfn_path = config.Config.lib_file("reallive.kfn")
    if os.path.exists(kfn_path):
        try:
            kfn_cache = kfn.load_kfn(kfn_path)
        except Exception as e:
            print(f"Warning: could not load {kfn_path}: {e}", file=sys.stderr)
            kfn_cache = ({}, {})
    else:
        kfn_cache = ({}, {})

    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    target_file = args.files[0]
    ranges = []
    negated_ranges = []

    if not args.add and not args.compress:
        if len(args.files) > 1:
            for r_str in args.files[1:]:
                try:
                    is_negated = r_str.startswith('!')
                    clean_r = r_str[1:] if is_negated else r_str
                    target_list = negated_ranges if is_negated else ranges
                    if '-' in clean_r:
                        start, end = map(int, clean_r.split('-'))
                        target_list.extend(range(start, end + 1))
                    else:
                        target_list.append(int(clean_r))
                except ValueError:
                    pass

    is_archive = False
    if os.path.exists(target_file) and os.path.isfile(target_file):
        try:
            arr = binarray.BinArray.from_file(target_file)
            if Archiver.seen_count(arr)!= -1:
                is_archive = True
        except Exception:
            pass

    if args.list:
        if not is_archive:
            print(f"{target_file} is not a valid archive.", file=sys.stderr)
            return
        count = Archiver.seen_count(arr)
        print(f"Archive {target_file} contains {count} valid SEEN files.")
        for i in range(10000):
            pos, length = Archiver.get_subfile_info(arr, i)
            if length > 0:
                print(f" SEEN{i:04d}.TXT: offset {pos:8d}, size {length:8d}")

    elif args.extract or args.break_arc:
        if is_archive:
            valid_ranges = [r for r in ranges if r not in negated_ranges] if ranges else [i for i in range(10000) if i not in negated_ranges]
            Archiver.extract_archive(target_file, args.outdir, valid_ranges, decompress=args.extract)
        else:
            print("Extract requires a Seen.txt archive.", file=sys.stderr)

    elif args.add:
        files_to_pack = {}
        for f in args.files[1:]:
            base = os.path.basename(f)
            if base.lower().startswith('seen') and (base.lower().endswith('.txt') or base.lower().endswith('.rl')):
                idx = int(base[4:8])
                files_to_pack[idx] = f
        Archiver.pack_archive(target_file, files_to_pack)

    elif args.compress:
        print("Compress mode not implemented in this cleaned build.", file=sys.stderr)

    elif args.disassemble:
        options = {
            'single_file': args.single_file,
            'annotate': False,
            'separate_all': args.separate_all,
            'no_smart_resources': True,
            'encoding': args.encoding,
            'kfn_cache': kfn_cache,
        }

        if is_archive:
            valid_ranges = [r for r in ranges if r not in negated_ranges] if ranges else [i for i in range(10000) if i not in negated_ranges]
            for i in range(10000):
                if i not in valid_ranges:
                    continue
                pos, length = Archiver.get_subfile_info(arr, i)
                if length > 0:
                    sub_data = arr.read(pos, length)
                    sub_arr = binarray.BinArray(sub_data)
                    fname = f"SEEN{i:04d}.TXT"

                    _, decomp_data = Archiver.try_extract(sub_arr, True, fname)
                    print(f"Disassembling {fname} to {args.outdir}...")

                    disassembler.disassemble_data(decomp_data, fname, args.outdir, options)
        else:
            for f in args.files:
                f_arr = binarray.BinArray.from_file(f)
                _, decomp_data = Archiver.try_extract(f_arr, True, f)
                print(f"Disassembling {f} to {args.outdir}...")
                disassembler.disassemble_data(decomp_data, f, args.outdir, options)

if __name__ == "__main__":
    main()

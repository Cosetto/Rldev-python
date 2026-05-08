import argparse
import glob
import os
import sys

from compiler import app
from compiler import ketypes
from compiler import compiler_frame
from compiler import game
from compiler import config
from compiler import text_encoding

def setup_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=app.exe_name,
        description=app.description,
        usage=app.usage
    )

    # General Options
    parser.add_argument("-v", "--verbose", type=int, default=0, help="describe what Rlc is doing; level 2 is very verbose")
    parser.add_argument("-o", "--output", help="override output filename")
    parser.add_argument("-d", "--outdir", help="place output file in DIR")
    parser.add_argument("-r", "--resdir", help="a directory containing resource files")
    parser.add_argument("-i", "--ini", help="specify GAMEEXE.INI to use at compile-time")

    # Text Encoding and Transformation
    parser.add_argument("-e", "--encoding", default="UTF-8", help="input text encoding")
    parser.add_argument("-x", "--transform-output", help="target bytecode text encoding (default: cp932)")
    parser.add_argument("--force-transform", action="store_true", help="don't abort when input can't be represented in output encoding")
    parser.add_argument("-t", "--target", help="specify target as RealLive, AVG2000, or Kinetic")
    parser.add_argument("-f", "--target-version", help="specify interpreter version or filename")
    
    # Low-level Compiler Options
    parser.add_argument("-u", "--uncompressed", action="store_true", help="don't compress and encrypt output")
    parser.add_argument("-g", "--no-debug", action="store_true", help="strip debugging information")
    parser.add_argument("--no-metadata", action="store_true", help="strip RLdev metadata (not recommended)")
    parser.add_argument("--no-assert", action="store_true", help="disable runtime assertions")
    parser.add_argument("--safe-arrays", action="store_true", help="enable runtime bounds-checking for arrays")
    parser.add_argument("--flag-labels", action="store_true", help="append labelled variable names to flag.ini")
    
    # Game-specific Encryption
    parser.add_argument("-G", "--game", default="LB", help="game ID")
    parser.add_argument("-c", "--compiler", type=int, help="compiler version (default: 10002, CLANNAD FV and LB: 110002, etc.)")
    parser.add_argument("-k", "--key", help="decoder key for compiler version 110002")
    
    parser.add_argument("-F", "--from-line", type=int, dest="start_line", help="line number of script file at which to begin compilation")
    parser.add_argument("-T", "--to-line", type=int, dest="end_line", help="line number of script file at which to end compilation")
    
    parser.add_argument("--kfn", default="reallive.kfn", help="specify the RealLive Function Definition File to use")
    parser.add_argument("--ext", default="org", help="script file extension")

    parser.add_argument("files", nargs="+", help="Input file(s) to compile")
    return parser

def main():
    parser = setup_argparser()
    args = parser.parse_args()

    # Map args to global app state
    app.verbose = args.verbose
    if args.output: app.outfile = args.output
    if args.outdir: app.outdir = args.outdir
    if args.resdir: app.resdir = args.resdir
    if args.ini: app.gameexe = args.ini
    app.enc = args.encoding.upper()
    if args.transform_output:
        text_encoding.set_output_encoding(args.transform_output)
    else:
        text_encoding.set_output_encoding("cp932")
    app.force_transform = args.force_transform
    if args.uncompressed: app.compress = False
    if args.no_debug: app.debug_info = False
    if args.no_metadata: app.metadata = False
    if args.no_assert: app.assertions = False
    if args.safe_arrays: app.array_bounds = True
    if args.flag_labels: app.flag_labels = True
    if args.game: app.game_id = args.game
    if args.compiler: ketypes.compiler_version = args.compiler
    
    if args.start_line: app.start_line = args.start_line
    if args.end_line: app.end_line = args.end_line
    if args.kfn: app.kfn_file = args.kfn
    if args.ext: app.src_ext = args.ext

    game_cfg_path = config.Config.lib_file(app.game_file)
    if os.path.exists(game_cfg_path):
        game.load_games_file(game_cfg_path)
        
    if app.game_id:
        game.set_current_game(app.game_id)
        g = game.get_current_game()
        if g and g.target_version and g.target_version != "Any":
            parts = g.target_version.split(".")
            a = int(parts[0]) if len(parts) > 0 else 0
            b = int(parts[1]) if len(parts) > 1 else 0
            c = int(parts[2]) if len(parts) > 2 else 0
            d = int(parts[3]) if len(parts) > 3 else 0
            ketypes.global_version = (a, b, c, d)
            
            if g.target_engine:
                ketypes.global_target = ketypes.target_t_of_string(g.target_engine)

    # Target assignment
    if args.target:
        ketypes.global_target = ketypes.target_t_of_string(args.target)
        ketypes.target_forced = True
        
    target_interpreter = ""
    auto_target = True
    if args.target_version:
        auto_target = False
        s = args.target_version
        try:
            parts = s.split(".")
            a = int(parts[0]) if len(parts) > 0 else 0
            b = int(parts[1]) if len(parts) > 1 else 0
            c = int(parts[2]) if len(parts) > 2 else 0
            d = int(parts[3]) if len(parts) > 3 else 0
            ketypes.global_version = (a, b, c, d)
        except Exception:
            if os.path.exists(s):
                target_interpreter = s
            else:
                ketypes.cli_error("target version must be specified as either an interpreter filename or up to four decimal integers separated by points")

    if app.outdir and not os.path.exists(app.outdir):
        try:
            os.makedirs(app.outdir, 0o755)
        except OSError as e:
            ketypes.cli_error(f"cannot create directory '{app.outdir}': {e}")

    if args.output and len(args.files) > 1:
        ketypes.cli_error("--output can only be used when compiling one input file")

    input_files = []
    for f in args.files:
        if '*' in f or '?' in f:
            matches = sorted(glob.glob(f))
            input_files.extend(matches if matches else [f])
        else:
            input_files.append(f)

    requested_outfile = app.outfile

    try:
        for input_file in input_files:
            app.outfile = requested_outfile
            if not input_file.endswith(f".{app.src_ext}"):
                input_file = f"{input_file}.{app.src_ext}"

            out_name = os.path.splitext(os.path.basename(input_file))[0] + ".TXT"
            print(f"Compiling {out_name}...", file=sys.stderr)

            if auto_target or target_interpreter:
                if target_interpreter:
                    pass # Load interpreter version here in a full PE parsing implementation
                else:
                    # Autodetect interpreter from directory
                    d = os.path.dirname(input_file) or "."
                    try:
                        for f in os.listdir(d):
                            if f.lower() in ("reallive.exe", "kinetic.exe", "avg2000.exe", "siglusengine.exe"):
                                target_interpreter = os.path.join(d, f)
                                break
                    except Exception:
                        pass

            compiler_frame.compile(input_file)
    except Exception as e:
        ketypes.cli_error(str(e))
        
if __name__ == "__main__":
    main()

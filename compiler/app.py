from . import config

exe_name = "RLC python port by Cosetto"
name = "Rlc"
usage = "<options> file"
description = "RealLive-compatible compiler"
version = 1.45

start_line = -1
end_line = -1

verbose = 0
compress = True
outdir = ""
outfile = ""
gameexe = ""
enc = config.Config.DEFAULT_ENCODING
output_encoding = "cp932"
force_transform = False
old_vars = False
with_rtl = True
assertions = True
debug_info = True
metadata = True
array_bounds = False
flag_labels = False
opt_level = 1

kfn_file = "reallive.kfn"
cast_file = ""
game_file = "game.cfg"
game_id = "LB"

src_ext = "org"
resdir = ""
runtime_trace = 0

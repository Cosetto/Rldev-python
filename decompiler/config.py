import os
import sys

class Config:
    DEFAULT_ENCODING = "UTF-8"
    PREFIX = ""
    VERSION = "1.0"

    @classmethod
    def init_prefix(cls):
        if cls.PREFIX:
            return cls.PREFIX
        home = os.environ.get("HOME", os.path.dirname(sys.argv[0]))
        rldir = os.environ.get("RLDEV", ".")

        possible_paths = [
            os.path.join(rldir, "lib"),
            rldir,
            home,
            os.path.join(home, "rldev"),
            os.path.join(home, ".rldev"),
            os.path.join(home, "share", "rldev"),
            os.path.join(home, "lib"),
            os.path.join(home, "rldev", "lib"),
            os.path.join(home, "share", "rldev", "lib"),
            os.path.join(home, ".rldev", "lib"),
            "/usr/share/rldev",
            "/usr/local/share/rldev",
            "/usr/share/rldev/lib",
            "/usr/local/share/rldev/lib"
        ]

        for path in possible_paths:
            if os.path.exists(os.path.join(path, "reallive.kfn")):
                cls.PREFIX = path
                return cls.PREFIX

        print("Error: unable to locate reallive.kfn. Try setting $RLDEV to your RLDev installation directory", file=sys.stderr)
        sys.exit(1)

    @classmethod
    def lib_file(cls, fname):
        if os.path.isabs(fname) or fname.startswith(("/", "\\")):
            return fname
        return os.path.join(cls.init_prefix(), fname)

Config.init_prefix()
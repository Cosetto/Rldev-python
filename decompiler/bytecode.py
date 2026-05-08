from .binarray import BinArray

class Metadata:
    def __init__(self, compiler_name="", compiler_version=0, target_version=(0, 0, 0, 0), text_transform='None'):
        self.compiler_name = compiler_name
        self.compiler_version = compiler_version
        self.target_version = target_version
        self.text_transform = text_transform

    @staticmethod
    def read(arr: BinArray, idx: int):
        metadata_len = arr.get_int32(idx)
        id_len = arr.get_int32(idx + 4) + 1
        
        if metadata_len < id_len + 17:
            print("Warning: RLdev metadata malformed")
            return Metadata()

        idx2 = idx + 8 + id_len
        # The compiler identifier is usually an ASCII string like "RLdev"
        compiler_name = arr.read_sz_string(idx + 8, encoding='ascii')
        compiler_version = arr.get_int32(idx2)
        
        target_version = (
            arr.data[idx2 + 4], 
            arr.data[idx2 + 5], 
            arr.data[idx2 + 6], 
            arr.data[idx2 + 7]
        )
        
        transform_map = {0: 'None', 1: 'Chinese', 2: 'Western', 3: 'Korean'}
        text_transform = transform_map.get(arr.data[idx2 + 8], 'None')

        return Metadata(compiler_name, compiler_version, target_version, text_transform)


class FileHeader:
    def __init__(self):
        self.header_version = 0
        self.compiler_version = 0
        self.data_offset = 0
        self.uncompressed_size = 0
        self.compressed_size = None
        self.int_0x2c = 0
        self.entry_points = []
        self.kidoku_lnums = []
        self.dramatis_personae = []
        self.rldev_metadata = Metadata()
        self.archived = False


def is_bytecode(arr: BinArray, idx: int = 0) -> bool:
    magic = arr.read(idx, 4)
    if magic in [b"RDRL", b"RD2K", b"RDRM"]:
        return True
    if magic in [b"KPRL", b"KP2K", b"KPRM", b"\xd0\x01\x00\x00", b"\xcc\x01\x00\x00", b"\xb8\x01\x00\x00"]:
        comp_ver = arr.get_int32(idx + 4)
        if comp_ver in [10002, 110002, 1110002]:
            return True
    return False

def uncompressed_header(magic: bytes) -> bool:
    return magic in [b"KPRL", b"KP2K", b"KPRM", b"RDRL", b"RD2K", b"RDRM"]


def read_file_header(arr: BinArray, archived: bool = False) -> FileHeader:
    """Reads the basic file offsets and compression sizes."""
    if not is_bytecode(arr, 0):
        raise ValueError("Not a valid bytecode file")

    hdr = FileHeader()
    hdr.archived = archived
    magic = arr.read(0, 4)

    # Determine compiler version
    if arr.read(0, 2) == b"RD":
        hdr.compiler_version = 110002 if arr.read(2, 2) == b"RM" else 10002
    else:
        hdr.compiler_version = arr.get_int32(4)

    # Parse version 1 headers (KP2K / AVG2000)
    if magic in [b"KP2K", b"RD2K", b"\xcc\x01\x00\x00"]:
        hdr.header_version = 1
        hdr.data_offset = 0x1cc + arr.get_int32(0x20) * 4
        hdr.uncompressed_size = arr.get_int32(0x24)
        hdr.int_0x2c = arr.get_int32(0x28)

    # Parse version 2 headers (KPRL / RealLive)
    elif magic in [b"KPRL", b"RDRL", b"KPRM", b"RDRM", b"\xd0\x01\x00\x00"]:
        hdr.header_version = 2
        hdr.data_offset = arr.get_int32(0x20)
        hdr.uncompressed_size = arr.get_int32(0x24)
        hdr.compressed_size = arr.get_int32(0x28)
        hdr.int_0x2c = arr.get_int32(0x2c)
    else:
        raise ValueError(f"Unsupported header format: {magic}")

    return hdr


def read_full_header(arr: BinArray, archived: bool = False) -> FileHeader:
    hdr = read_file_header(arr, archived)

    if hdr.header_version == 1:
        hdr.entry_points = [arr.get_int32(0x30 + i * 4) for i in range(100)]
        kidoku_count = arr.get_int32(0x20)
        hdr.kidoku_lnums = [arr.get_int32(0x1cc + i * 4) for i in range(kidoku_count)]

    elif hdr.header_version == 2:
        hdr.entry_points = [arr.get_int32(0x34 + i * 4) for i in range(100)]
        
        t1_offset = arr.get_int32(0x08)
        kidoku_count = arr.get_int32(0x0c)
        hdr.kidoku_lnums = [arr.get_int32(t1_offset + i * 4) for i in range(kidoku_count)]

        offset = arr.get_int32(0x14)
        dp_count = arr.get_int32(0x18)
        
        for _ in range(dp_count):
            length = arr.get_int32(offset)
            idx = offset + 4
            hdr.dramatis_personae.append(arr.read_sz_string(idx, encoding='cp932'))
            offset = idx + length

        # Check for RLdev Metadata appended at the end of the DP block
        dp_end = arr.get_int32(0x14) + arr.get_int32(0x1c)
        if dp_end != hdr.data_offset:
            hdr.rldev_metadata = Metadata.read(arr, dp_end)

    return hdr

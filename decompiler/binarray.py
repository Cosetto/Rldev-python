import struct

class BinArray:
    def __init__(self, data: bytes = b''):
        self.data = bytearray(data)

    @classmethod
    def from_file(cls, filename: str):
        with open(filename, 'rb') as f:
            return cls(f.read())

    def to_file(self, filename: str):
        with open(filename, 'wb') as f:
            f.write(self.data)

    def read(self, idx: int, length: int) -> bytes:
        return bytes(self.data[idx:idx+length])

    def read_sz(self, idx: int) -> bytes:
        end = self.data.find(b'\x00', idx)
        if end == -1:
            return bytes(self.data[idx:])
        return bytes(self.data[idx:end])

    def read_sz_string(self, idx: int, encoding='cp932') -> str:
        return self.read_sz(idx).decode(encoding)

    def write(self, idx: int, data: bytes):
        end = idx + len(data)
        if end > len(self.data):
            self.data.extend(b'\x00' * (end - len(self.data)))
        self.data[idx:end] = data

    def get_i16(self, idx: int) -> int:
        return struct.unpack_from('<H', self.data, idx)[0]

    def get_int32(self, idx: int) -> int:
        return struct.unpack_from('<I', self.data, idx)[0]

    def put_i16(self, idx: int, value: int):
        struct.pack_into('<H', self.data, idx, value)

    def put_int32(self, idx: int, value: int):
        struct.pack_into('<I', self.data, idx, value)

    def dim(self) -> int:
        return len(self.data)
    
    def fill(self, value: int):
        for i in range(len(self.data)):
            self.data[i] = value
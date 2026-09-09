class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 4); self.bin = 0
    def reset(self):
        self.bin = 0
    def step(self, i):
        out = {"bin": self.bin, "gray": self.bin ^ (self.bin >> 1)}
        if i["en"]:
            self.bin = (self.bin + 1) & ((1 << self.W) - 1)
        return out

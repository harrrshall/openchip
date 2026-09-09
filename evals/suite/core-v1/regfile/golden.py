class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 8); self.D = params.get("DEPTH", 4); self.r = [0] * self.D
    def reset(self):
        self.r = [0] * self.D
    def step(self, i):
        out = {"rdata0": self.r[i["raddr0"] % self.D], "rdata1": self.r[i["raddr1"] % self.D]}
        if i["we"]:
            self.r[i["waddr"] % self.D] = i["wdata"] & ((1 << self.W) - 1)
        return out

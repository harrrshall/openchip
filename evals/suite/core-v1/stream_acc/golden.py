class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 16); self.MAX = (1 << self.W) - 1
        self.acc = 0; self.pending = 0; self.val = 0
    def reset(self):
        self.acc = 0; self.pending = 0; self.val = 0
    def step(self, i):
        out = {"in_ready": int(not self.pending), "out_valid": int(self.pending), "out_data": self.val if self.pending else 0}
        if i["clear"]:
            self.acc = 0; self.pending = 0; self.val = 0
        elif self.pending:
            if i["out_ready"]:
                self.pending = 0; self.val = 0
        elif i["in_valid"]:
            s = min(self.acc + i["in_data"], self.MAX)
            if i["in_last"]:
                self.pending = 1; self.val = s; self.acc = 0
            else:
                self.acc = s
        return out

def stimulus(rng, cycle, params, prev):
    W = params.get("WIDTH", 16)
    big = rng.random() < 0.2
    data = rng.randint((1 << W) * 3 // 4, (1 << W) - 1) if big else rng.getrandbits(W)
    return {"in_valid": int(rng.random() < 0.7), "in_data": data, "in_last": int(rng.random() < 0.2),
            "out_ready": int(rng.random() < 0.6), "clear": int(rng.random() < 0.03)}

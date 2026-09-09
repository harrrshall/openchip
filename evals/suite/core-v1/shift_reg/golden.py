class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 8); self.q = 0
    def reset(self):
        self.q = 0
    def step(self, i):
        out = {"q": self.q, "sout": (self.q >> (self.W - 1)) & 1}
        if i["load"]:
            self.q = i["din"] & ((1 << self.W) - 1)
        elif i["shift_en"]:
            self.q = ((self.q << 1) | (i["sin"] & 1)) & ((1 << self.W) - 1)
        return out

def stimulus(rng, cycle, params, prev):
    return {"load": int(rng.random() < 0.08), "din": rng.getrandbits(params.get("WIDTH", 8)), "shift_en": int(rng.random() < 0.7), "sin": rng.getrandbits(1)}

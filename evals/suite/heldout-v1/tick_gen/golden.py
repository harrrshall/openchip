class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 12); self.phase = 0; self.tick = 0
    def reset(self):
        self.phase = 0; self.tick = 0
    def step(self, i):
        out = {"tick": self.tick, "phase": self.phase}
        d = i["divisor"]
        if not i["en"]:
            self.phase = 0; self.tick = 0
        elif d == 0 or self.phase >= d - 1:
            self.phase = 0; self.tick = 1
        else:
            self.phase = (self.phase + 1) & ((1 << self.W) - 1); self.tick = 0
        return out

_s = {"d": 3}
def stimulus(rng, cycle, params, prev):
    if cycle % 60 == 0:
        _s["d"] = rng.choice([0, 1, 2, 3, 7, 16, 100])
    return {"en": int(rng.random() < 0.9), "divisor": _s["d"]}

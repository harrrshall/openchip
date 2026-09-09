class Reference:
    def __init__(self, params):
        self.prev = 0; self.rise = 0; self.fall = 0
    def reset(self):
        self.prev = 0; self.rise = 0; self.fall = 0
    def step(self, i):
        out = {"rise": self.rise, "fall": self.fall}
        s = i["sig"] & 1
        self.rise = int(s == 1 and self.prev == 0)
        self.fall = int(s == 0 and self.prev == 1)
        self.prev = s
        return out

def stimulus(rng, cycle, params, prev):
    # hold levels for random durations so edges are sparse but frequent enough
    return {"sig": int(((cycle // rng.choice([1, 2, 3, 5])) % 2) == 0) if rng.random() < 0.5 else rng.getrandbits(1)}

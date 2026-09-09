class Reference:
    def __init__(self, params):
        self.hist = 0; self.det = 0
    def reset(self):
        self.hist = 0; self.det = 0
    def step(self, i):
        out = {"det": self.det}
        self.hist = ((self.hist << 1) | (i["din"] & 1)) & 0xF
        self.det = int(self.hist == 0b1011)
        return out

def stimulus(rng, cycle, params, prev):
    # bias toward 1s so the pattern occurs often
    return {"din": int(rng.random() < 0.65)}

class Reference:
    def __init__(self, params):
        self.last = 3
    def reset(self):
        self.last = 3
    def step(self, i):
        req = i["req"] & 0xF
        g = 0
        for k in range(1, 5):
            idx = (self.last + k) % 4
            if (req >> idx) & 1:
                g = 1 << idx
                break
        out = {"grant": g}
        if g:
            self.last = g.bit_length() - 1
        return out

def stimulus(rng, cycle, params, prev):
    return {"req": rng.choice([0xF, 0xF, 0x5, 0xA, rng.getrandbits(4), rng.getrandbits(4), 0])}

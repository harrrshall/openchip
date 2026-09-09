class Reference:
    def __init__(self, params): pass
    def reset(self): pass
    def step(self, i):
        r = i["req"] & 0xFF
        return {"valid": int(r != 0), "idx": (r.bit_length() - 1) if r else 0}

def stimulus(rng, cycle, params, prev):
    return {"req": rng.choice([0, 1, 0x80, 0x24, rng.getrandbits(8), rng.getrandbits(8), 1 << rng.randrange(8)])}

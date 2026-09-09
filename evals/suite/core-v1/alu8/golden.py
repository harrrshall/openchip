class Reference:
    def __init__(self, params):
        self.result = 0; self.zero = 0; self.carry = 0
    def reset(self):
        self.result = 0; self.zero = 0; self.carry = 0
    def step(self, i):
        out = {"result": self.result, "zero": self.zero, "carry": self.carry}
        a, b, op = i["a"] & 0xFF, i["b"] & 0xFF, i["op"] & 7
        c = 0
        if op == 0:
            s = a + b; r = s & 0xFF; c = (s >> 8) & 1
        elif op == 1:
            r = (a - b) & 0xFF; c = int(a < b)
        elif op == 2:
            r = a & b
        elif op == 3:
            r = a | b
        elif op == 4:
            r = a ^ b
        elif op == 5:
            r = (a << 1) & 0xFF
        elif op == 6:
            r = a >> 1
        else:
            r = a
        self.result, self.zero, self.carry = r, int(r == 0), c
        return out

def stimulus(rng, cycle, params, prev):
    a = rng.choice([0, 1, 0xFF, 0x80, 0x7F, rng.getrandbits(8), rng.getrandbits(8)])
    b = rng.choice([0, 1, 0xFF, a, rng.getrandbits(8), rng.getrandbits(8)])
    return {"a": a, "b": b, "op": rng.getrandbits(3)}

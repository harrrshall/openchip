class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 8); self.D = params.get("DEPTH", 16); self.q = []
    def reset(self):
        self.q = []
    def step(self, i):
        n = len(self.q)
        out = {"dout": self.q[0] if n else 0, "full": int(n == self.D), "empty": int(n == 0), "count": n}
        pop_ok = i["pop"] and n > 0
        push_ok = i["push"] and n < self.D
        if pop_ok:
            self.q.pop(0)
        if push_ok:
            self.q.append(i["din"] & ((1 << self.W) - 1))
        return out

def stimulus(rng, cycle, params, prev):
    phase = (cycle // 40) % 3
    if phase == 0:
        p_push, p_pop = 0.85, 0.15
    elif phase == 1:
        p_push, p_pop = 0.15, 0.85
    else:
        p_push, p_pop = 0.5, 0.5
    return {"push": int(rng.random() < p_push), "pop": int(rng.random() < p_pop), "din": rng.getrandbits(params.get("WIDTH", 8))}

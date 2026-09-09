class Reference:
    def __init__(self, params):
        self.N = params.get("N", 4); self.cnt = 0; self.dout = 0
    def reset(self):
        self.cnt = 0; self.dout = 0
    def step(self, i):
        out = {"dout": self.dout}
        d = i["din"] & 1
        if d != self.dout:
            if self.cnt >= self.N - 1:
                self.dout = d; self.cnt = 0
            else:
                self.cnt += 1
        else:
            self.cnt = 0
        return out

_lvl = {"v": 0, "hold": 0}
def stimulus(rng, cycle, params, prev):
    if _lvl["hold"] <= 0:
        _lvl["v"] ^= 1
        _lvl["hold"] = rng.choice([1, 2, 3, 4, 5, 8, 12])
    _lvl["hold"] -= 1
    return {"din": _lvl["v"]}

class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 8); self.cnt = 0
    def reset(self):
        self.cnt = 0
    def step(self, i):
        out = {"pwm_out": int(self.cnt < i["duty"]), "cnt": self.cnt}
        p = i["period"]
        if p == 0 or self.cnt >= p - 1:
            self.cnt = 0
        else:
            self.cnt = (self.cnt + 1) & ((1 << self.W) - 1)
        return out

_state = {"period": 20, "duty": 5}
def stimulus(rng, cycle, params, prev):
    if cycle % 50 == 0:
        _state["period"] = rng.choice([0, 1, 2, 5, 20, 37, 255])
        _state["duty"] = rng.getrandbits(params.get("WIDTH", 8))
    return {"period": _state["period"], "duty": _state["duty"]}

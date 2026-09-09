class Reference:
    def __init__(self, params):
        self.count = 0
    def reset(self):
        self.count = 0
    def step(self, i):
        out = {"count": self.count}
        if i["load"]:
            self.count = i["load_val"] & 0xFF
        elif i["en"]:
            self.count = (self.count + (1 if i["up"] else -1)) & 0xFF
        return out

def stimulus(rng, cycle, params, prev):
    return {"en": int(rng.random() < 0.8), "up": int(rng.random() < 0.6), "load": int(rng.random() < 0.05), "load_val": rng.getrandbits(8)}

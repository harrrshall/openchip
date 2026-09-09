class Reference:
    def __init__(self, params):
        self.W = params.get("WIDTH", 8); self.rem = 0; self.busy = 0; self.done = 0
    def reset(self):
        self.rem = 0; self.busy = 0; self.done = 0
    def step(self, i):
        out = {"busy": self.busy, "done": self.done, "remaining": self.rem}
        done_n = 0
        if self.busy:
            if self.rem == 1:
                self.rem = 0; self.busy = 0; done_n = 1
            else:
                self.rem = (self.rem - 1) & ((1 << self.W) - 1)
        elif i["start"]:
            if i["load_val"] == 0:
                done_n = 1
            else:
                self.rem = i["load_val"]; self.busy = 1
        self.done = done_n
        return out

def stimulus(rng, cycle, params, prev):
    return {"start": int(rng.random() < 0.25), "load_val": rng.choice([0, 1, 2, 3, rng.randint(1, 12), rng.randint(1, 40)])}

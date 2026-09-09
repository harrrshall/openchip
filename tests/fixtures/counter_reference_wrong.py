class Reference:
    """Deliberately wrong: returns the post-edge value of a registered output."""
    def __init__(self, params):
        self.count = 0
    def reset(self):
        self.count = 0
    def step(self, i):
        if i["load"]:
            self.count = i["load_val"] & 0xFF
        elif i["en"]:
            self.count = (self.count + (1 if i["up"] else -1)) & 0xFF
        return {"count": self.count}

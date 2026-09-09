from core.plugin_base import PluginBase

class CalcPlugin(PluginBase):
    def test(self):
        return {"result": 6666}

    def add(self, a: float = 0, b: float = 0):
        return {"result": a + b}

    def sub(self, a: float = 0, b: float = 0):
        return {"result": a - b}

    def mul(self, a: float = 0, b: float = 0):
        return {"result": a * b}
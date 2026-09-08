from core.plugin_base import BasePlugin

class CalcPlugin(BasePlugin):
    def add(self, a: float = 0, b: float = 0):
        return {"result": a + b}

    def sub(self, a: float = 0, b: float = 0):
        return {"result": a - b}

    def mul(self, a: float = 0, b: float = 0):
        return {"result": a * b}
from core.plugin_base import PluginBase, plugin_route


class CalcPlugin(PluginBase):
    @plugin_route("GET")
    def test(self):
        return {"result": 6666}

    @plugin_route("GET")
    def add(self, a: float = 0, b: float = 0):
        return {"result": a + b}

    def sub(self, a: float = 0, b: float = 0):
        return {"result": a - b}

    @plugin_route("POST")
    def mul(self, a: float = 0, b: float = 0):
        return {"result": a * b}

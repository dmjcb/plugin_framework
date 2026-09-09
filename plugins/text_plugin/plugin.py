from pydantic import BaseModel

from core.plugin_base import PluginBase
from plugins.calc_plugin.plugin import CalcPlugin

class RepeatRequest(BaseModel):
    text: str
    times: int = 1


class TextPlugin(PluginBase):
    def upper(self, text: str = "hello"):
        return {"text": text.upper()}

    def repeat(self, data: RepeatRequest):
        return {"text": data.text * data.times}

    def use_calc(self, a: float = 0, b: float = 0):
        """
        跨插件调用示例：
        本插件通过 context 获取已加载的 calc 插件，
        并调用其 add 和 sub 方法。
        """
        calc: CalcPlugin = self.context.get_plugin("calc")
        return {
            "a": a,
            "b": b,
            "add": calc.add(a, b),
            "sub": calc.sub(a, b)
        }
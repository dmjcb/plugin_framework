from typing import TYPE_CHECKING

from pydantic import BaseModel

from core.plugin_base import PluginBase, plugin_route

if TYPE_CHECKING:
    from plugins.calc_plugin.calc_plugin import CalcPlugin


class RepeatRequest(BaseModel):
    text: str
    times: int = 1


class TextPlugin(PluginBase):
    @plugin_route("GET")
    def upper(self, text: str = "hello"):
        return {"text": text.upper()}

    @plugin_route("POST")
    def repeat(self, data: RepeatRequest):
        return {"text": data.text * data.times}

    @plugin_route("POST", "/process-json")
    def process_json(self, data: dict):
        """接收 POST 请求中的 JSON 数据，简单处理后返回。

        请求示例：
        {
            "message": "  hello codex  "
        }
        """
        message = str(data.get("message", "")).strip().upper()
        return {
            "received": data,
            "result": message,
        }

    @plugin_route("GET", "/use-calc")
    def use_calc(self, a: float = 0, b: float = 0):
        """
        跨插件调用示例：
        本插件通过 context 获取已加载的 calc 插件，
        并调用其 add 和 sub 方法。
        """
        calc: "CalcPlugin" = self.context.get_plugin("calc")
        return {
            "a": a,
            "b": b,
            "add": calc.add(a, b),
            "sub": calc.sub(a, b)
        }

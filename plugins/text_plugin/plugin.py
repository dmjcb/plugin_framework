# -*- coding: utf-8 -*-
from pydantic import BaseModel

from core.plugin_base import BasePlugin


class RepeatRequest(BaseModel):
    text: str
    times: int = 1


class TextPlugin(BasePlugin):
    """自定义文本处理插件"""

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
        calc = self.context.get_plugin("calc")
        return {
            "a": a,
            "b": b,
            "add": calc.add(a, b),
            "sub": calc.sub(a, b)
        }
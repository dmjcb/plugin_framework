from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager


class PluginBase:
    def __init__(self):
        self.name: Optional[str] = None
        self.context: Optional["PluginManager"] = None

    def initialize(self, context):
        """
        插件初始化函数。
        context 为 PluginManager 实例，可用来调用其他插件。
        """
        self.context = context

    def shutdown(self):
        """服务关闭时调用，可扩展"""
        pass

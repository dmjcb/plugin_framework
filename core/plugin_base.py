from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager


def plugin_route(
    method: str,
    path: Optional[str] = None,
) -> Callable[[Callable], Callable]:
    """声明插件方法对应的 HTTP 路由。

    未指定 path 时使用被装饰函数的名称。path 是插件内的相对路径，
    PluginManager 会自动添加插件名称前缀。
    """
    http_method = method.upper()
    if http_method not in {"GET", "POST"}:
        raise ValueError("插件路由仅支持 GET 或 POST")
    if path is not None and not isinstance(path, str):
        raise TypeError("插件路由 path 必须是字符串或 None")

    def decorator(func: Callable) -> Callable:
        routes = list(getattr(func, "__plugin_routes__", ()))
        routes.append({"method": http_method, "path": path})
        func.__plugin_routes__ = tuple(routes)
        return func

    return decorator


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

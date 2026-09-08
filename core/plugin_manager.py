import importlib.util
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginManager:
    def __init__(self, plugin_dir: str):
        self.plugin_dir = Path(plugin_dir)
        self.plugins = {}
        self._manifests = {}

        self.context = self

    def discover(self):
        """
        自动发现指定目录下所有 plugin.json
        这里使用 rglob,因此支持嵌套目录
        """
        if not self.plugin_dir.exists():
            raise FileNotFoundError(f"插件目录不存在: {self.plugin_dir}")

        for manifest_path in self.plugin_dir.rglob("plugin.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                name = manifest.get("name")
                if not name:
                    logger.warning("忽略缺少 name 的配置文件: %s", manifest_path)
                    continue

                manifest["_dir"] = str(manifest_path.parent)
                self._manifests[name] = manifest
                logger.info("发现插件: %s (%s)", name, manifest_path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("读取插件配置失败 %s: %s", manifest_path, exc)

        return self._manifests

    def load_all(self):
        """加载所有已发现插件"""
        if not self._manifests:
            self.discover()

        for name in self._manifests:
            self.load_plugin(name)

        return self.plugins

    def load_plugin(self, name: str):
        """动态加载单个插件"""
        if name not in self._manifests:
            raise KeyError(f"插件 {name} 不存在")

        manifest = self._manifests[name]
        entry = Path(manifest["_dir"]) / manifest.get("entry", "__init__.py")
        class_name = manifest.get("class")

        if not entry.exists():
            raise FileNotFoundError(f"插件入口文件不存在: {entry}")
        if not class_name:
            raise RuntimeError(f"插件 {name} 未配置 class 字段")

        # 构造唯一且合法的模块名
        safe_name = re.sub(r"\W", "_", name)
        module_name = f"plugin_{safe_name}"

        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件模块: {entry}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plugin_cls = getattr(module, class_name)
        plugin = plugin_cls()

        plugin.name = name
        self.plugins[name] = plugin

        logger.info("成功加载插件: %s", name)
        return plugin

    def initialize_all(self):
        """
        为所有插件注入 context, 并调用插件自身的 initialize 方法。
        分两步保证所有插件都已加载且统一可访问。
        """
        for name, plugin in self.plugins.items():
            plugin.name = name
            plugin.context = self.context

        for plugin in self.plugins.values():
            init_fn = getattr(plugin, "initialize", None)
            if callable(init_fn):
                init_fn(self.context)

    def register_routes(self, app):
        """
        根据 plugin.json 中 routes 配置，将插件公开函数注册为 FastAPI 接口。
        """
        for plugin_name, manifest in self._manifests.items():
            plugin = self.plugins.get(plugin_name)
            if plugin is None:
                logger.warning("插件 %s 未加载，跳过路由注册", plugin_name)
                continue

            for route in manifest.get("routes", []):
                function_name = route.get("function")
                method = route.get("method", "GET").upper()
                path = route.get("path")

                if not function_name or not path:
                    logger.warning("插件 %s 存在无效路由配置", plugin_name)
                    continue

                func = getattr(plugin, function_name, None)
                if not callable(func):
                    raise AttributeError(
                        f"插件 {plugin_name} 中找不到可调用函数: {function_name}"
                    )

                route_handler = getattr(app, method.lower(), None)
                if route_handler is None:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")

                route_handler(
                    path,
                    tags=[plugin_name],
                    name=f"{plugin_name}_{function_name}"
                )(func)

                logger.info("注册路由 %s %s -> %s.%s", method, path, plugin_name, function_name)

    def get_plugin(self, name: str):
        """获取插件实例"""
        if name not in self.plugins:
            raise KeyError(f"插件 {name} 未加载，已加载插件: {list(self.plugins)}")
        return self.plugins[name]

    def call(self, plugin_name: str, method_name: str, *args, **kwargs):
        """调用指定插件的公开方法"""
        plugin = self.get_plugin(plugin_name)
        method = getattr(plugin, method_name)
        return method(*args, **kwargs)

    def list_plugins(self):
        """返回所有已加载插件名称"""
        return list(self.plugins)

import os
import json
import importlib
import asyncio
import logging

from fastapi import Request, HTTPException
from starlette.concurrency import run_in_threadpool
from core.plugin_base import PluginBase
from typing import Dict, Any

logger = logging.getLogger(__name__)


class PluginContext:
    """插件上下文，setup 时传给插件"""
    def __init__(self, manager, config):
        self.manager = manager
        self.config = config


class PluginManager:
    def __init__(self, fastapi_app, plugins_dir: str = "plugins"):
        """
        :param fastapi_app: FastAPI 实例，插件接口会注册到该实例上
        :param plugins_dir: 插件目录，默认为项目根目录下的 plugins
        """
        self.app = fastapi_app
        self.plugins_dir = plugins_dir
        self.plugins: Dict[str, PluginBase] = {}
        self.plugin_meta: Dict[str, dict] = {}
        self._registered_routes: Dict[str, list] = {}
        self._registered_route_set = set()

    # ---------- 扫描 ----------
    def discover_plugins(self):
        """扫描插件目录，返回所有合法的插件元信息字典列表"""
        result = []
        if not os.path.exists(self.plugins_dir):
            logger.warning("插件目录不存在: %s", self.plugins_dir)
            return result

        for entry in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, entry)
            json_path = os.path.join(plugin_path, "plugin.json")

            if os.path.isdir(plugin_path) and os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    meta["dir"] = entry
                    result.append(meta)
                except Exception as e:
                    logger.error("读取插件配置失败 %s: %s", json_path, e)
        return result

    # ---------- 加载单个插件 ----------
    def load_plugin(self, meta: dict):
        """根据配置动态导入模块并实例化插件类"""
        name = meta.get("name", meta.get("dir"))
        entry = meta.get("entry", "main")
        class_name = meta.get("class", "Plugin")

        if name in self.plugins:
            logger.warning("插件 %s 已存在，跳过", name)
            return

        # 例如: plugins.example_plugin.main
        module_name = f"{self.plugins_dir}.{meta['dir']}.{entry}"
        try:
            module = importlib.import_module(module_name)
            plugin_class = getattr(module, class_name)
            instance = plugin_class()

            # 注入基本信息
            instance.plugin_name = name
            instance.manager = self
            instance.plugin_config = meta.get("config", {})

            self.plugins[name] = instance
            self.plugin_meta[name] = meta
            logger.info("插件加载成功: %s", name)
        except Exception as e:
            logger.exception("加载插件 %s 失败: %s", name, e)

    # ---------- 加载所有插件 ----------
    def load_all_plugins(self):
        """加载 plugins 目录下所有 enabled 的插件"""
        all_metas = self.discover_plugins()

        # 第一阶段：实例化插件，注册到 self.plugins，但暂不 setup
        for meta in all_metas:
            if meta.get("enabled", True):
                self.load_plugin(meta)

        # 第二阶段：全部实例化完成后，统一 setup，这样插件间互相调用更安全
        for name, plugin in self.plugins.items():
            try:
                ctx = PluginContext(self, self.plugin_meta[name].get("config", {}))
                plugin.setup(ctx)
            except Exception as e:
                logger.exception("插件 setup 失败: %s", name)

        # 第三阶段：注册 FastAPI 路由
        for name in self.plugins:
            self._register_plugin_api(name)

    # ---------- 动态注册 FastAPI ----------
    def _register_plugin_api(self, plugin_name: str):
        """将插件的所有公开功能方法注册为 FastAPI 的 POST 接口"""
        plugin = self.plugins[plugin_name]
        self._registered_routes[plugin_name] = []
        prefix = f"/api/plugin/{plugin_name}"

        for method_name in dir(plugin):
            # 过滤私有方法和固定接口
            if method_name.startswith("_") or method_name in ("setup", "teardown"):
                continue

            attr = getattr(plugin, method_name)
            if not callable(attr):
                continue

            path = f"{prefix}/{method_name}"
            endpoint = self._create_api_endpoint(attr)

            # 注册 FastAPI 路由
            self.app.add_api_route(path=path, endpoint=endpoint, methods=["POST"], name=f"{plugin_name}_{method_name}")
            self._registered_routes[plugin_name].append(path)
            logger.info("注册 API: POST %s", path)

    @staticmethod
    def _create_api_endpoint(func):
        """将插件方法包装成一个 FastAPI endpoint。

        浏览器/客户端通过 JSON Body 传入参数，body 的 key 与方法参数名对应。
        """
        async def endpoint(request: Request):
            body = {}
            raw = await request.body()
            if raw:
                try:
                    data = await request.json()
                except Exception:
                    raise HTTPException(status_code=400, detail="请求体必须是合法 JSON")
                if isinstance(data, dict):
                    body = data
                else:
                    raise HTTPException(status_code=400, detail="JSON 请求体必须是字典")

            # 兼容同步和异步功能函数
            if asyncio.iscoroutinefunction(func):
                result = await func(**body)
            else:
                result = await run_in_threadpool(func, **body)

            return {"code": 0, "message": "success", "data": result}

        return endpoint

    # ---------- 跨模块调用 ----------
    def call_plugin(self, plugin_name: str, method_name: str, *args, **kwargs):
        """
        调用另一个插件的功能函数。
        例如在插件 A 中调用插件 B 的 func:
            result = self.manager.call_plugin("B", "func", x=1)
        """
        if plugin_name not in self.plugins:
            raise KeyError(f"插件 {plugin_name} 未加载")

        plugin = self.plugins[plugin_name]
        func = getattr(plugin, method_name, None)
        if func is None or not callable(func):
            raise AttributeError(f"插件 {plugin_name} 没有可调用的方法 {method_name}")

        return func(*args, **kwargs)

    # ---------- 卸载插件 ----------
    def unload_plugin(self, plugin_name: str):
        """卸载插件：调用 teardown、移除插件实例、移除 FastAPI 路由"""
        if plugin_name not in self.plugins:
            logger.warning("插件 %s 不存在，无法卸载", plugin_name)
            return

        plugin = self.plugins[plugin_name]
        try:
            plugin.teardown()
        except Exception as e:
            logger.exception("插件 teardown 失败: %s", plugin_name)

        # 移除路由
        paths = self._registered_routes.pop(plugin_name, [])
        if self.app and paths:
            path_set = set(paths)
            self.app.router.routes[:] = [
                r for r in self.app.router.routes
                if getattr(r, "path", None) not in path_set
            ]

        del self.plugins[plugin_name]
        del self.plugin_meta[plugin_name]
        logger.info("插件已卸载: %s", plugin_name)
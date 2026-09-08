# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI

from core.plugin_manager import PluginManager


def create_app() -> FastAPI:
    app = FastAPI(
        title="Python 插件化 FastAPI 框架",
        description="通过 plugin.json 自动发现并加载插件",
        version="1.0.0"
    )

    # 1. 扫描和加载插件
    manager = PluginManager(plugin_dir="./plugins")
    manager.load_all()

    # 2. 初始化插件
    manager.initialize_all()

    # 3. 注册插件公开接口
    manager.register_routes(app)

    # 4. 根路径提示
    @app.get("/")
    def root():
        return {
            "message": "Plugin FastAPI is running",
            "plugins": list(manager.plugins.keys())
        }

    # 将 manager 保存到 app 中方便调试
    app.state.plugin_manager = manager

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
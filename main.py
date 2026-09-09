import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI

from core.plugin_manager import PluginManager


def create_app() -> FastAPI:
    app = FastAPI(
        title="Python 插件化 FastAPI 框架",
        description="通过同名 JSON 发现插件，并使用装饰器注册路由",
        version="1.0.0"
    )

    manager = PluginManager(plugin_dir=ROOT / "plugins")
    manager.load_all()
    manager.initialize_all()
    manager.register_routes(app)

    @app.get("/")
    def root():
        return {
            "message": "Plugin FastAPI is running",
            "plugins": list(manager.plugins.keys())
        }

    app.state.plugin_manager = manager

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

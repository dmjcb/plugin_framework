from fastapi import FastAPI
from core.plugin_manager import PluginManager

# 创建 FastAPI 实例
app = FastAPI(title="Python 插件化框架", version="1.0.0")

# 初始化插件管理器并加载所有插件
manager = PluginManager(app, plugins_dir="plugins")
manager.load_all_plugins()


@app.get("/")
def index():
    return {
        "message": "Python 插件化框架运行中",
        "plugins": list(manager.plugins.keys())
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
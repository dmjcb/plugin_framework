class PluginBase:
    # 插件元信息，若 plugin.json 中为设置，可使用默认值
    plugin_name = "unnamed"
    plugin_version = "1.0.0"
    plugin_description = ""
    plugin_author = ""

    # 运行时由 PluginManager 填充
    manager = None
    plugin_config = {}

    def setup(self, context):
        """
        固定接口 1: 插件加载后调用, 用于初始化。
        context 中包含 manager 和当前插件的 config。
        """
        self.manager = context.manager
        self.plugin_config = context.config

    def teardown(self):
        """
        固定接口 2: 插件卸载前调用, 用于释放资源。
        """
        pass
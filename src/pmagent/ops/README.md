# launchd 定时任务

当前运行时通过 `pmagent install-launchd` 直接生成 plist 文件。
本目录仅保留说明文档，不再携带静态 plist 模板副本，避免与代码中的真实模板发生漂移。

## 命令

安装日报任务：

```bash
pmagent install-launchd daily-digest --hour 9 --minute 0
```

安装每周例行：

```bash
pmagent install-launchd weekly-routine --weekday 1 --hour 9 --minute 30
```

对应执行命令：

- 日报：`pmagent digest`
- 周例行：`pmagent weekly`

# longbridge2tg

一个轻量 Python 常驻服务：读取 Longbridge 个人账户的股票仓位、最新行情和账户余额，并在多个东八区时间点发送到指定 Telegram chat。

只使用 `AsyncTradeContext.stock_positions()`、`AsyncTradeContext.account_balance()`、`AsyncQuoteContext.static_info()` 和 `AsyncQuoteContext.quote()` 这些只读接口；项目不包含下单或改单逻辑。

## 配置

复制示例配置并填入真实凭据：

```bash
cp config.example.yaml config.yaml
```

程序按以下顺序选择配置文件：

1. `--config /path/to/config.yaml`
2. 环境变量 `LB2TG_CONFIG`
3. 当前目录下的 `config.yaml`

Linux/macOS 上建议限制权限：

```bash
chmod 600 config.yaml
```

`telegram.chat_id` 是允许控制 bot 并接收汇报的唯一 chat。个人 chat 的数字 ID 可以通过 Telegram 上的 `@userinfobot` 查看。其他来源的消息会被忽略并记录警告日志。

## 运行

```bash
python -m venv .venv
. .venv/bin/activate
pip install .
python -m longbridge2tg --config ./config.yaml
```

首次运行时定时任务默认关闭。先向 bot 发送：

```text
/start_task
```

支持的命令：

- `/report_test`: 立即获取并发送一次账户仓位；不改变定时开关。
- `/start_task`: 启动每日定时任务。
- `/stop_task`: 停止每日定时任务。

服务每次重启后会自动开启每日定时任务；如需临时停止，使用 `/stop_task`。

报告样例：

```text
## 📊 账户仓位
**持仓：78.3%**
**现金：20.7%**

## 📈 持仓排序

| 名称 | 代码 | 占比 | 状态 |
|:-----|:-----|-----:|:----:|
| 超威半导体 | AMD | 31.9% | 🟢 盈利 |
| 特斯拉 | TSLA | 26.0% | 🔴 亏损 |
```

报告通过 Telegram Rich Messages 以 Markdown 表格渲染；证券名优先使用 `name_cn`，美国代码会去掉 `.US` 后缀。当前百分比基于同币种的持仓市值和 `net_assets` 计算；如果持仓包含多种币种，服务会拒绝汇总并记录日志，而不是使用未确认的汇率估算。

## VPS 部署

参考 [deploy/longbridge2tg.service](deploy/longbridge2tg.service)。常见安装路径如下：

```bash
sudo mkdir -p /etc/longbridge2tg /opt/longbridge2tg
sudo cp config.example.yaml /etc/longbridge2tg/config.yaml
sudo chown -R longbridge2tg:longbridge2tg /etc/longbridge2tg /opt/longbridge2tg
sudo chmod 600 /etc/longbridge2tg/config.yaml
```

然后启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now longbridge2tg.service
journalctl -u longbridge2tg.service -f
```

## 测试

```bash
pip install '.[dev]'
pytest -q
```

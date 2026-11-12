# guitar-coach

面向吉他初学者的实时跟弹练习软件：对着谱弹，每一个音立刻给出对错反馈。本仓库对应 [rofaster/guitarsoftware](https://github.com/rofaster/guitarsoftware) 的第一版。

默认是等待模式、0.7 倍速、宽松判定，入门谱为开放弦练习。六弦独立拾音器是判断「按了哪根弦」的主路径，但第一次使用不必接拾音器，只用音高也可以练。

## 环境

- Python 3.10 或更高
- 推荐用 [uv](https://docs.astral.sh/uv/) 管理依赖
- 核心依赖是 `numpy`；接麦克风或拾音器时再安装 `sounddevice`

```bash
uv sync
```

## 快速开始

```bash
uv run python -m guitarcoach.web
```

浏览器打开 http://127.0.0.1:8765 。不指定谱面时，默认加载内置空弦练习（`scores/open-strings.json`）。

接真实输入设备：

```bash
# 把 N 换成输入设备编号
uv run --with sounddevice python -m guitarcoach.web --device N

# 六弦独立拾音器（通道 0 = 1 弦高音 E，通道 5 = 6 弦低音 E）
uv run --with sounddevice python -m guitarcoach.web --device N --hex
```

6 声道 WAV 会自动按拾音器处理，不必再加 `--hex`。

用文件回放（不接乐器）：

```bash
uv run python -m guitarcoach.web --score scores/open-strings.json --wav path/to/take.wav
```

生成错弦示范录音时，空弦谱请用 `--shift-string -1`（往更粗的弦、大约第 5 品；低音 E 不动）。空弦上使用 `--shift-string 1` 会变成负品位，录音不会变，命令会给出警告：

```bash
uv run python -m guitarcoach.hex --out open-wrong-string.wav --shift-string -1
```

蓝牙输入，或测得延迟达到 120 ms 及以上，会降级为只看音高、不计时值。也可以用 `--bluetooth` 或 `--latency-ms` 显式指定。

速度可用 `--speed` 调整，范围 0.5–1.0，默认 0.7。

## 练习规则（第一版）

- **等待模式**（默认）：弹对才前进。若已检出弦且弦不对，音符黄闪并标「弦位不同」，光标留在原音，弹对弦再走；没有弦号的输入仍只看音高。
- **跟弹模式**：只标黄、不打断、不计分；弦位提示不影响准确率。
- **判定档**：默认宽松（±80 音分，时间窗 −200/+350 ms）。另有标准档和严格档。
- **宽松档准确率**：hit / (hit + wrong_pitch)；漏音、弦位提示、跳过另列。
- **节拍器**：默认关闭。

裁决包括：hit、wrong_pitch、wrong_string、missed、skipped。

## 测试

```bash
uv run python -m unittest discover -s tests -v
```

第一版验收时 101 个测试通过。

## 项目结构

```
src/guitarcoach/    引擎与 Web 界面（`ui/index.html`，无构建、无 CDN）
scores/             JSON 谱面（默认空弦练习）
tests/              单元测试
docs/               音乐规格与前端接口
tools/              校准与诊断脚本
```

谱面中间表示使用 midi、start/dur（秒）、string 1–6、fret 0–24、tempo、拍号、小节和 phrase_id。接口说明见 `docs/frontend-api.md` 与 `docs/frontend-api-hex.md`，判定规格见 `docs/v1-music-spec.md`。

检测链路是频谱通量起音、YIN 音高、三帧投票，再加谐波/非谐波能量比纠正八度。端到端检测延迟约 100–120 ms（测试要求小于 130 ms）。产品方案曾以 80 ms 为目标，为保住三帧投票的音高稳定性，这是有意的取舍。

音色分弦的分类机制有测试覆盖，但准确率无法用合成音频验证，必须在真实吉他上校准后再量。第一版弦位识别以六弦拾音器为主。

## 已知限制

- 相邻音间隔小于 200 ms 时检出不可靠（约对应 100 BPM 的十六分音符；默认 0.7 倍速下通常碰不到）。
- 第一版不含桌面应用壳，需要手动启动服务并打开浏览器。
- 第一版不含 Guitar Pro / MusicXML 导入、拾音器通道映射向导，以及真机拾音器标定。

## 版权说明

本仓库只提供练习引擎和内置入门谱。不托管他人曲谱，不用大模型生成整份乐谱，也不从付费墙抓谱。

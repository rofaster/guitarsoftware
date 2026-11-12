# 前端对接说明（后端 v1.1）

后端：`src/guitarcoach/web.py`，纯标准库 HTTP + SSE。前端现在只有一个文件 `src/guitarcoach/ui/index.html`，由 `GET /` 直接返回，可以整体重写，也可以拆成多文件（拆了告诉我，我加静态路由）。音乐规则以 `docs/v1-music-spec.md` 为准。

## 启动

```
.\.venv\Scripts\python.exe -m guitarcoach.web --wav <录音.wav>     # 回放录音
.\.venv\Scripts\python.exe -m guitarcoach.web --device <N>          # 实时麦克风/声卡
```
需要先设 `$env:PYTHONPATH='src'`。打开 http://127.0.0.1:8765，加 `?auto` 会自动开始。
测试录音：`backup\smoke_v11.py` 里有合成内置谱录音的写法。

## GET /score

```json
{ "title": "G 弦音阶走句", "tempo": 80.0, "meter": [4,4], "beats_per_bar": 4, "bar_seconds": 3.0,
  "notes": [{"name":"G3","midi":55,"string":3,"fret":0,"start":0.0,"dur":0.75,"bar":0,"phrase_id":0}, ...],
  "issues": [{"code":"range","message":"超出常用音域（MIDI 30）","index":3,"bar":0}] }
```
- `bar` 从 0 开始，显示时加 1。小节线画在 bar 变化处，phrase_id 变化处可以画粗一点。
- `issues` 是谱面校验结果，只标不改。有 index 的标在那个音上（黄色虚框），没有 index 的是整小节问题。空数组表示「谱面检查通过」。

## GET /events（SSE，同一时间只允许一条，第二条返回 429）

查询参数：
| 参数 | 含义 |
|---|---|
| `from` | 从第几个音开始（暂停后继续就传当前光标） |
| `speed` | 0.5–1.0，默认 0.7 |
| `mode` | `follow`（跟弹）或 `wait`（等待）；启动默认见 `/score.defaults`，现为 `wait` |
| `skip_from` | `[skip_from, from)` 这些音回报为 `skipped`（快进用） |
| `loop_a` `loop_b` | A-B 循环，传小节号（0 起），两个都传才生效 |

切模式、改速度、跳转、改循环：前端关掉当前 EventSource，用新参数重新连，`from` 传当前光标。后端不会清颜色，颜色由前端自己保留。暂停 = 关连接，光标不动。

事件（`data:` 一行 JSON）：
| type | 字段 | 前端要做的 |
|---|---|---|
| `hello` | mode, speed, from, loop, score | 可忽略 |
| `count_in` | beats, seconds | 跟弹起步前 1 拍预备，可做倒数动画 |
| `detection` | time, name, midi, cents, latency_ms | 实时显示听到的音、音分偏差、延迟 |
| `verdict` | index, status, cents, delta_ms | 给第 index 个音上色，光标移到 index+1 |
| `flash` | index, cents, status, 可能有 string/fret/midi | 等待模式弹错：该音黄闪一下，光标不动。`status` 为 `wrong_pitch` 或 `wrong_string`（有弦号且弦不对时留下，弹对弦再走） |
| `suggest_back` | reason(`streak`/`bar_rate`), bar, target | 出非阻塞提示条「退回上一小节？」[退回][继续]；点退回就从 target 重连，并清掉 target 之后的颜色；不点 6 秒左右自动收起=继续；进入新小节也收起 |
| `loop` | index | A-B 回到 A：清掉 A..B 的颜色，光标到 index |
| `done` | | 本段结束，显示三项统计 |

status 与文案、颜色（宽松档，**永不标红**）：
| status | 文案 | 颜色 |
|---|---|---|
| hit | 对 | 绿 |
| wrong_pitch | 音高不准 | 黄 |
| wrong_string | 弦位不同 | 黄（仅提示） |
| missed | 漏了 | 灰 |
| skipped | 已跳过 | 暗灰，不进统计 |

## 统计（前端按每个音最新 status 自己算）

- 本段准确率 = hit / (hit + wrong_pitch)（wrong_string 音高是对的，当 hit 算）
- 另列：音高偏差（wrong_pitch 数）、漏音（missed 数）、弦位提示（wrong_string 数）。不打总分。

## 进度控制（全部按小节）

- 后退：在小节中间就回本小节开头，已在开头就回上一小节；清掉目标之后的颜色。
- 快进：跳到下一小节开头，跳过的未判音标 skipped，重连时带 `skip_from`。
- 进度条：按小节打点，拖动时显示「第 N 小节」，松手吸附到小节起点。
- A-B：设 A / 设 B 取光标所在小节，B<A 自动交换。
- 跟弹/等待开关：从当前待弹音生效，不回跳、不清颜色。
- 等待模式下下一个音要淡入预览，不要藏谱。

现有 `index.html` 已经实现了以上全部逻辑，只是样式简陋，可以当参考实现。



## 弦号与品格（六路拾音器）

detection / verdict 在有把握时带上实际按到的位置，没有就省略该字段，现有字段不变。

| 字段 | 出现在 | 含义 |
|---|---|---|
| `string` | detection, verdict（命中了一个音时） | 实际按到的弦，1–6（1 是最细的高音 E） |
| `fret` | 同上，仅当弦 + 音高能算出合法品位时 | 实际品位，0–24 |
| `midi` | detection 里本来就有；verdict 在听到音时也会带 | 实际听到的 MIDI |

`flash`（等待模式弹错）同样可能带 `string` / `fret` / `midi`，以及 `status`（`wrong_pitch` 或 `wrong_string`）。漏音、跳过的 verdict 不带这些字段。

`hello` 增加 `profile`，目前是 `"loose"`（宽松档），不要写死文案。

跟弹模式下，音高对但弦错了，宽松档标 `wrong_string`（黄、弦位不同），不算错、光标前进。等待模式下，检测带了弦号且和弦谱不一致：同样黄闪，但光标留在原音，弹对弦再走。音高不准仍是 `wrong_pitch`。不另增事件类型。

### 不插硬件的模拟输入

六路 WAV：声道 0 = 1 弦（高音 E），声道 5 = 6 弦（低音 E）。6 声道文件会自动按拾音器处理，单声道 / 立体声仍是只判音高、不带弦号。

```
$env:PYTHONPATH='src'
# 按谱面正确的弦渲染一条六路录音
.\.venv\Scripts\python.exe -m guitarcoach.hex --out takes\open-strings.wav
# 空弦练习请用 -1（往更粗的弦、大约第 5 品）。+1 在空弦上会变成负品位，录音和正确的一样。
# 低音 E 保持原弦。
.\.venv\Scripts\python.exe -m guitarcoach.hex --shift-string -1 --out takes\open-wrong-string.wav
.\.venv\Scripts\python.exe -m guitarcoach.web --wav takes\open-strings.wav
```

真机六路拾音器：`--device N --hex`。代码里也可以直接用 `hex_source(plucks, total)` 得到内存里的六路音源，无需写文件。


## tuning

`/score` 和 `hello.score` 里有 `tuning`：弦号（字符串键 `"1"`–`"6"`）到空弦 MIDI。标准调弦是 `{"1": 64, "2": 59, "3": 55, "4": 50, "5": 45, "6": 40}`（E4 B3 G3 D3 A2 E2）。品位 = 听到的 midi - tuning[string]。

## 初版默认与输入降级

`/score` 和 `hello` 都带 `defaults`：`{"mode": "wait", "speed": 0.7, "profile": "loose"}`。前端启动时请用这个，不要再写死跟弹。

`/score.input` 和 `hello.input` 描述当前输入策略：
`{name, pitch_only, judge_onset, judge_string, warning_code, warning, latency_ms}`。
`warning` 已是中文，有则显示即可。蓝牙或延迟 ≥120 ms 时 `name` 为 `degraded-bluetooth`，`judge_onset` 为 false：只判音高、不标漏音、不判节奏。启动参数：`--bluetooth` 或 `--latency-ms 180`；设备名带 Bluetooth / AirPods 也会自动降级。

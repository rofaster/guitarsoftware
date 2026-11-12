

## 弦号与品格（六路拾音器）

detection / verdict 在有把握时带上实际按到的位置，没有就省略该字段，现有字段不变。

| 字段 | 出现在 | 含义 |
|---|---|---|
| `string` | detection, verdict（命中了一个音时） | 实际按到的弦，1–6（1 是最细的高音 E） |
| `fret` | 同上，仅当弦 + 音高能算出合法品位时 | 实际品位，0–24 |
| `midi` | detection 里本来就有；verdict 在听到音时也会带 | 实际听到的 MIDI |

`flash`（等待模式弹错）同样可能带 `string` / `fret` / `midi`。漏音、跳过的 verdict 不带这些字段。

`hello` 增加 `profile`，目前是 `"loose"`（宽松档），不要写死文案。

判定语义不变：音高对但弦错了，宽松档标 `wrong_string`（黄、弦位不同），不算错、不暂停。音高不准仍是 `wrong_pitch`。两套状态已经分开，不另增事件类型。

### 不插硬件的模拟输入

六路 WAV：声道 0 = 1 弦（高音 E），声道 5 = 6 弦（低音 E）。6 声道文件会自动按拾音器处理，单声道 / 立体声仍是只判音高、不带弦号。

```
$env:PYTHONPATH='src'
# 按谱面正确的弦渲染一条六路录音
.\ .venv\Scripts\python.exe -m guitarcoach.hex --out takes\g-hex.wav
# 同一音高改到相邻弦上，用来测「弦位不同」
.\ .venv\Scripts\python.exe -m guitarcoach.hex --shift-string 1 --out takes\g-wrong-string.wav
.\ .venv\Scripts\python.exe -m guitarcoach.web --wav takes\g-hex.wav
```

真机六路拾音器：`--device N --hex`。代码里也可以直接用 `hex_source(plucks, total)` 得到内存里的六路音源，无需写文件。

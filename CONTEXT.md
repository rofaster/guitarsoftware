# 项目上下文（压缩版）

> 2026-11-12：第一版已验收并准备推送到 GitHub。对外说明以仓库根目录 README.md 为准；下文部分条目（如测试数量、限制）可能早于第一版，请以 README 为准。


> 用途：跨会话续接。完整讨论见桌面 `吉他谱智能采集与实时跟弹软件-产品方案-v0.2.md`。

## 〇、快照

| 项 | 值 |
|---|---|
| 代码位置 | `C:\Users\ASUS\guitar-coach` |
| 测试 | **101 项全绿**（`python -m unittest discover -s tests`） |
| 已完成 | 第一版已验收（练习闭环、hex 弦位、等待模式默认） |
| 演示 | `python -m guitarcoach.web --score out/score.json --wav out/take.wav` → `http://127.0.0.1:8765/?auto` |
| 最后更新 | 2026-11-12 |

## 一、产品一句话

输入歌名找谱 → 接吉他 → 弹一个音屏幕亮一个音并判对错 → 卡住可退回。核心价值是**逐音即时反馈**，不是曲谱数量。

## 二、已定决策（产品负责人拍板）

| 决策 | 结论 |
|---|---|
| 曲谱来源 | 全网检索 + 大模型解析；红线：只索引不托管、LLM 不生成整谱 |
| 判定默认档 | **宽松**：±80 音分、−200/+350 ms、弦位只提示不计分、宁可漏判不可误判 |
| 输入方式 | 音频接口 / USB 麦 / 内置麦 / 蓝牙（自动降级）/ MIDI 吉他 |

## 三、进度

| 轮次 | 内容 | 状态 |
|---|---|---|
| 方案 | v0.1 → v0.2（LLM 管线、版权边界、判定参数、多输入矩阵） | 定稿 |
| 1 | IR、YIN、频谱通量起音、宽松判定、KS 合成、CLI | 完成 |
| 2 | WAV IO、JSON 谱面、设备路由、三档对照 | 完成 |
| 3 | 谐波比纠八度（偏差 1217→141 音分） | 完成 |
| 4 | 自适应分析窗：**假设证伪**，重叠边界确认为 200 ms | 完成（负结果） |
| 5 | 实时流 StreamDetector + 音频源 + live CLI（延迟 100–120 ms） | 完成 |
| 6 | Web UI：HTTP + SSE + 单页谱面 | 完成 |
| 7 | 分弦：音色指纹 + 指法约束 + 校准工具 | 完成（准确率待真机验证） |
| 8 | 真机校准验证 **或** 桌面壳打包 | 待定 |

## 四、代码地图

```
src/guitarcoach/
  ir.py         Note/Score/Detection、弦品↔MIDI
  score_io.py   JSON 谱面读写
  audio_io.py   WAV 读写（纯标准库）
  detect.py     频谱通量起音 + YIN + 三帧投票 + 谐波比纠八度
  judge.py      LOOSE/STANDARD/STRICT、逐音裁决、wrong_string、报告
  input.py      设备 → 判定策略（返回 warning_code，文案由 UI 本地化）
  synth.py      Karplus-Strong（音分纠偏重采样 + 弦径亮度/环路阻尼）
  strings.py    分弦：音色特征 / 质心分类器 / 候选位置 / 指法排序 / profile 存取
  live.py       流式检测器 + live CLI（逐块增量）
  audio_input.py 设备枚举 / FileSource（测试替身）/ DeviceSource
  web.py        HTTP + SSE + LiveJudge（顺序匹配）
  ui/index.html 谱面页（单文件、无构建、无 CDN）
  cli.py        合成 / 文件 / 设备 三模式
tests/          53 项（judge/octave/pipeline/stream/web/strings）
tools/          probe_overlap / probe_attack / probe_low / probe_timbre / probe_decay / calibrate
out/            示例谱面、录音、弦位 profile（可删）
```

## 五、实测指标（合成数据 44.1 kHz）

| 场景 | 起音 | 判定 | 最大偏差 |
|---|---|---|---|
| 熟练 + 1 走音 + 1 迟到 500 ms | 8/8 | 75%（6 对 / 1 错 / 1 漏） | +109 音分 |
| 新手 ±160 ms 抖动 | 8/8 | 宽松 62% / 标准 50% / 严格 25% | +141 音分 |
| 实时流 | 8/8 | 与离线**完全一致** | — |

延迟：端到端 **100–120 ms**（20 ms 起音偏移 + 45 ms 投票尾 + 35 ms 分析帧）。方案目标 80 ms，为保精度有意放宽。

## 六、当前限制

1. **相邻音 <200 ms 不可靠**（0.08–0.15 s 报第三音或漏检，≥0.20 s 正常）。对应 100 BPM 十六分音符，0.7 倍速练习碰不到。正解是谱减或复音估计。
2. **分弦准确率未经真机验证**：合成器的弦径模型不足以拉开音色差异（质心差 0.005、衰减比跨度 ≤0.04），分类器机制已测，准确率必须在真琴上量。
3. **无桌面壳**：需手动起服务、开浏览器。
4. **无真实曲谱导入验证**：JSON 谱面格式已定，但还没接过 Guitar Pro / MusicXML。

## 七、已排除的弯路（不要重走）

| 尝试 | 结果 |
|---|---|
| 吸附最强谱峰 | 拨弦强峰常是 2/3 次谐波，正确音被拉高八度 |
| 谐波求和 + 1.35 倍余量 | 同样拉高，准确率 75%→62% |
| 按间隔自适应窗口 / 贴起音短窗 | 边界不变；短窗让低音高八度（E2 丢失、A2→A3、D3→D4） |
| 用合成音频验证音色分弦 | 自欺：调到"能分"只是在证明自己的模型 |
| **有效**：谐波/非谐波能量比 | 真基频填满 k·f0，(k+0.5)·f0 近乎为空；低八度只填偶数槽 |

## 八、下一步（建议顺序）

1. **真机校准验证**（推荐）：录 6 段空弦 → `tools/calibrate.py` 生成 profile → 弹已知弦位音阶验证 → 拿到真实分弦准确率。不验证就打包，只是个漂亮的空壳。
2. **桌面壳打包**：Tauri/Electron 套壳，解决麦克风权限、进程管理、双击启动。
3. 曲谱导入：Guitar Pro / MusicXML → 现有 JSON IR。
4. 谱减 / 复音估计：把 200 ms 边界压到 100 ms 以内（仅在需要快速音阶时做）。

## 九、命令

```bash
# 离线判定（两段合成演奏，三档对照）
uv run --with numpy python -m guitarcoach.cli

# 实时流（WAV 当麦克风回放）
uv run --with numpy python -m guitarcoach.live --wav out/take.wav --score out/score.json

# 网页谱面
uv run --with numpy python -m guitarcoach.web --score out/score.json --wav out/take.wav

# 设备判定策略 / 生成示例数据
uv run --with numpy python -m guitarcoach.cli --device bluetooth
uv run --with numpy python -m guitarcoach.cli --save-demo out

# 分弦校准（每弦一段录音）
uv run --with numpy python tools/calibrate.py --out out/string-profile.json \
    --string 6 e2.wav --string 5 a2.wav --string 4 d3.wav \
    --string 3 g3.wav --string 2 b3.wav --string 1 e4.wav

# 测试
uv run --with numpy python -m unittest discover -s tests -v
```
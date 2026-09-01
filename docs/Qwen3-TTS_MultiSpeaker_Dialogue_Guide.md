# Qwen3-TTS 多角色对话音频生成方案

> ⚠️ **DEPRECATED / DISABLED** ⚠️
>
> 当前版本（回退 Qwen3-TTS）此集成已关闭：
> - 后端 `backend/app/tts_service.py` 模块主体已包入 `if False:`
> - `/api/tts/*` 端点已在 `backend/app/main.py` 用 `if False:` 注释
> - 前端 `TimelinePanel.tsx` 的 TTS 卡片渲染已注释
> - `requirements.txt` / `Dockerfile` / `docker-compose.yml` / `.env.example` 里的 Qwen3-TTS 依赖与 GPU 配置已注释
>
> 本文档保留作为恢复参考;不要按本文档重新启用,而应先看代码注释决定是否回滚相关改动。

> 基于本地 Qwen3-TTS 模型，将 ASR 转录文本还原为多角色真人对话音频

---

## 一、方案概述

| 项目 | 说明 |
|------|------|
| **目标** | 将 ASR JSON 中的 84 段对话，按角色分配不同音色，生成完整音频 |
| **模型** | `Qwen3-TTS-12Hz-1.7B-CustomVoice`（本地已部署） |
| **输出格式** | WAV / FLAC，24kHz 单声道 |
| **总时长** | 约 4 分 28 秒（与原 ASR 时间轴对齐） |
| **适用场景** | 播客还原、有声内容制作、AI 对话演示 |

> **重要前提**: Qwen3-TTS 是文本转语音（TTS）模型，能精确复现台词内容；而 MiniMax H3 是文生音频（Audio Diffusion），只能生成氛围音效，**不能念出台词**。**

---

## 二、环境准备

### 2.1 安装依赖

```bash
pip install torch soundfile pydub numpy scipy

# 如果缺少 qwen_tts 官方库
pip install git+https://github.com/QwenLM/Qwen3-TTS.git
```

### 2.2 确认本地模型路径

根据你的截图，本地模型路径结构如下（请根据实际路径修改）:

```
你的模型根目录/
├── Qwen3-TTS-12Hz-1.7B-Base/          # 基础模型（可选）
├── Qwen3-TTS-12Hz-1.7B-CustomVoice/   # 主要使用: 支持多音色
├── Qwen3-TTS-12Hz-1.7B-VoiceDesign/   # 语音设计（自定义音色）
├── Qwen3-TTS-25HZ/                    # 高采样率版本
└── Qwen3-TTS-Tokenizer-12Hz/          # Tokenizer
```

**本方案使用 `Qwen3-TTS-12Hz-1.7B-CustomVoice`**，因为它内置了多个预训练 speaker，适合直接分配角色。**

---

## 三、第一步: 查询可用音色

在运行主脚本前，先执行以下代码确认模型支持的内置 speaker:

```python
import torch
from qwen_tts import Qwen3TTSModel

MODEL_PATH = r"你的路径\Qwen3-TTS-12Hz-1.7B-CustomVoice"

model = Qwen3TTSModel.from_pretrained(
    MODEL_PATH,
    device_map="cuda:0",
    dtype=torch.bfloat16,
)

print("可用 Speakers:", model.get_supported_speakers())
print("可用 Languages:", model.get_supported_languages())
```

### 常见内置 Speaker 参考

| Speaker | 风格描述 | 建议分配 |
|---------|---------|---------|
| `Ryan` | 沉稳成熟男声 | 老严（资深分析师） |
| `Ethan` | 年轻活力男声 | 阿强（养殖户） |
| `Vivian` | 知性优雅女声 | 静姐（研究员） |
| `Adam` | 干脆利落男声 | 阿斌（行业老手） |
| `Emma` | 温柔女声 | 备用 |
| `Olivia` | 活泼女声 | 备用 |

> 根据实际查询结果调整 `ROLE_MAP` 中的映射。**

---

## 四、第二步: 主生成脚本

创建文件 `generate_dialogue.py`，内容如下:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3-TTS 多角色对话音频生成器"""

import json
import torch
import soundfile as sf
import numpy as np
from qwen_tts import Qwen3TTSModel

# ==================== 用户配置区 ====================

MODEL_PATH = r"D:\Models\Qwen3-TTS-12Hz-1.7B-CustomVoice"
ASR_JSON = r"196375cd9181441698b26d29d8.asr.json"
OUTPUT_WAV = r"dialogue_output.wav"
TARGET_SR = 24000

ROLE_MAP = {
    "laoyan":    "Ryan",   # 老严: 沉稳男声
    "xiaoqiang": "Ethan",  # 阿强: 年轻男声
    "jingjie":   "Vivian", # 静姐: 知性女声
    "abin":      "Adam",   # 阿斌: 干练男声
}

ROLE_INSTRUCT = {
    "laoyan":    "用沉稳、权威的语气，像资深农业分析师一样说话",
    "xiaoqiang": "用略带焦虑、朴实的语气，像基层养殖户一样说话",
    "jingjie":   "用冷静、理性的语气，像数据研究员一样说话",
    "abin":      "用干脆、直接的语气，像行业老手一样说话",
}

# ==================== 函数定义 ====================

def load_model(model_path):
    """加载 Qwen3-TTS 模型"""
    print(f"正在加载模型: {model_path}")
    model = Qwen3TTSModel.from_pretrained(
        model_path,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    print("模型加载完成")
    return model


def read_asr(asr_path):
    """读取 ASR JSON 文件"""
    with open(asr_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments = data.get("segments", [])
    print(f"读取到 {len(segments)} 个音频片段")
    return segments


def generate_silence(duration_ms, sr=24000):
    """生成指定时长的静音"""
    samples = int(sr * (duration_ms / 1000.0))
    return np.zeros(samples, dtype=np.float32)


def resample_audio(audio, orig_sr, target_sr):
    """音频重采样"""
    if orig_sr == target_sr:
        return audio
    from scipy import signal
    num_samples = int(len(audio) * target_sr / orig_sr)
    return signal.resample(audio, num_samples).astype(np.float32)


def generate_segment(model, text, speaker, instruct=None):
    """生成单段语音"""
    kwargs = {
        "text": text,
        "language": "Chinese",
        "speaker": speaker,
    }
    if instruct:
        kwargs["instruct"] = instruct
    wavs, sr = model.generate_custom_voice(**kwargs)
    wav = wavs[0]
    if sr != TARGET_SR:
        wav = resample_audio(wav, sr, TARGET_SR)
    else:
        wav = wav.astype(np.float32)
    return wav


def main():
    model = load_model(MODEL_PATH)
    segments = read_asr(ASR_JSON)
    audio_parts = []

    for i, seg in enumerate(segments):
        speaker_id = seg.get("speaker_id", "")
        speaker_name = seg.get("speaker", "未知")
        text = seg.get("text", "").strip()
        duration_ms = seg.get("end_ms", 0) - seg.get("start_ms", 0)

        if speaker_id == '__system__' or not text:
            silence = generate_silence(duration_ms, TARGET_SR)
            audio_parts.append((silence, duration_ms))
            print(f"[{i+1:3d}/{len(segments)}] [{speaker_name}] 静音 {duration_ms}ms")
            continue

        speaker = ROLE_MAP.get(speaker_id, 'Ryan')
        instruct = ROLE_INSTRUCT.get(speaker_id, None)
        print(f"[{i+1:3d}/{len(segments)}]  [{speaker_name}({speaker})] {text[:40]}...")

        try:
            wav = generate_segment(model, text, speaker, instruct)
            audio_parts.append((wav, duration_ms))
        except Exception as e:
            print(f"    生成失败: {e}")
            silence = generate_silence(duration_ms, TARGET_SR)
            audio_parts.append((silence, duration_ms))

    print("\n正在拼接音频...")
    final_audio = np.concatenate([part[0] for part in audio_parts])
    sf.write(OUTPUT_WAV, final_audio, TARGET_SR)
    total_sec = len(final_audio) / TARGET_SR
    print(f"\n完成!")
    print(f"   输出文件: {OUTPUT_WAV}")
    print(f"   总时长: {int(total_sec//60)}分{int(total_sec%60)}秒")
    print(f"   采样率: {TARGET_SR}Hz")
    print(f"   样本数: {len(final_audio):,}")


if __name__ == "__main__":
    main()
```

---

## 五、第三步: 运行

```bash
python generate_dialogue.py
```

### 预期输出

```
正在加载模型: D:\Models\Qwen3-TTS-12Hz-1.7B-CustomVoice
模型加载完成
读取到 84 个音频片段
[  1/ 84] [系统] 静音 1000ms
[  2/ 84] [系统] 静音 3291ms
[  3/ 84] [系统] 静音 2025ms
[  4/ 84]  [老严(Ryan)] FAO刚出7月数据，食品价格指数131.1...
[  5/ 84]  [老严(Ryan)] 别看同比只高1%，小麦单月涨了5.8%...
[  6/ 84]  [阿强(Ethan)] 我家饲料厂豆粕玉米占成本六成...
...
[ 84/ 84] [系统] 静音 4789ms

正在拼接音频...

完成!
   输出文件: dialogue_output.wav
   总时长: 4分28秒
   采样率: 24000Hz
   样本数: 6,434,088
```

---

## 六、进阶: 自定义角色音色

如果内置 speaker 不满意，可以用 `Qwen3-TTS-12Hz-1.7B-VoiceDesign` 模型创建专属音色:

```python
from qwen_tts import Qwen3TTSModel

vd_model = Qwen3TTSModel.from_pretrained(
    r"你的路径\Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    device_map="cuda:0",
    dtype=torch.bfloat16,
)

speaker_emb = vd_model.design_speaker(
    description="一位五十多岁的资深农业分析师，声音低沉有力，语速适中，带有权威感",
    language="Chinese",
)

vd_model.save_speaker(speaker_emb, "laoyan_custom.pt")
```

然后在主脚本中加载自定义音色:

```python
speaker_emb = model.load_speaker("laoyan_custom.pt")
wavs, sr = model.generate_custom_voice(
    text="FAO刚出7月数据...",
    language="Chinese",
    speaker_embedding=speaker_emb,
)
```

---

## 七、常见问题

### Q1: 显存不足（OOM）怎么办?

**方案 A**: 降低精度
```python
dtype=torch.float16  # 或 float32（CPU 运行）
```

**方案 B**: 换用更小模型
```python
MODEL_PATH = r"你的路径\Qwen3-TTS-12Hz-0.6B-CustomVoice"
```

**方案 C**: 使用 CPU
```python
device_map="cpu"
```

### Q2: 生成音频语速不对怎么办?

Qwen3-TTS 不支持直接控制语速。如需调整，可在生成后用 `pydub` 变速:

```python
from pydub import AudioSegment

audio = AudioSegment.from_wav("dialogue_output.wav")
# 加速 10%
audio_fast = audio._spawn(audio.raw_data, overrides={
    "frame_rate": int(audio.frame_rate * 1.1)
}).set_frame_rate(audio.frame_rate)
audio_fast.export("dialogue_fast.wav", format="wav")
```

### Q3: 如何给每个角色克隆真人声音?

使用 `VoiceClonePromptNode`（ComfyUI）或 Python 中的 `generate_voice_clone`:

```python
# reference_audio = "laoyan_reference.wav"

wavs, sr = model.generate_voice_clone(
    text="FAO刚出7月数据...",
    language="Chinese",
    reference_audio=reference_audio,
)
```

### Q4: 系统提示音也想配音?

将 `__system__` 的处理逻辑改为正常生成，并分配一个特殊 speaker:

```python
ROLE_MAP = {
    "__system__": "Emma",  # 旁白女声
    "laoyan": "Ryan",
    # ...
}
```

---

## 八、文件清单

| 文件 | 说明 |
|------|------|
| `generate_dialogue.py` | 主生成脚本（本文档中的代码） |
| `196375cd9181441698b26d29d8.asr.json` | ASR 源文件 |
| `dialogue_output.wav` | 生成的对话音频 |

---

## 九、与 ComfyUI 方案对比

| 维度 | Python 脚本（本方案） | ComfyUI + Qwen-TTS 节点 |
|------|----------------------|------------------------|
| **片段数** | 84 段无压力 | 节点连线繁琐，适合 <20 段 |
| **时间轴控制** | 精确按 ASR 时间轴 | 难以精确对齐 |
| **批量处理** | 一键运行 | 需手动配置每个节点 |
| **可视化调试** | 纯代码 | 节点可视化 |
| **适合场景** | 长对话、播客、有声书 | 短片段演示、效果测试 |

---

> **建议**: 先用 Python 脚本生成完整音频，如需调整某几句话的音色，再用 ComfyUI 单独生成替换。**
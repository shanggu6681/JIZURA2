#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JIZURA 歌词识别工具 — 基于 faster-whisper
将音乐文件识别为带时间戳的歌词，生成 SRT / LRC / TXT 文件

用法:
    python transcribe_lyrics.py <音乐文件路径> [选项]
    或将音乐文件拖到 "识别歌词.bat" 上
"""

import os
import sys
import time
import argparse
from pathlib import Path

# ─── 颜色输出 ───────────────────────────────────────
class C:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'

def cprint(color, text):
    """带颜色的打印（Windows 也兼容）"""
    try:
        # 启用 Windows ANSI 支持
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        pass
    print(color + text + C.RESET)

# ─── 格式化时间 ─────────────────────────────────────
def fmt_time(seconds):
    """秒数 → 分:秒"""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def fmt_srt_time(seconds):
    """秒数 → SRT 时间格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def fmt_lrc_time(seconds):
    """秒数 → LRC 时间格式 MM:SS.xx"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    centis = int((seconds - int(seconds)) * 100)
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"

# ─── 输出格式生成 ───────────────────────────────────
def segments_to_srt(segments):
    """将识别结果转为 SRT 格式"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.start if hasattr(seg, 'start') else seg['start']
        end = seg.end if hasattr(seg, 'end') else seg['end']
        text = seg.text if hasattr(seg, 'text') else seg['text']
        text = text.strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{fmt_srt_time(start)} --> {fmt_srt_time(end)}")
        lines.append(text)
        lines.append('')
    return '\n'.join(lines)

def segments_to_lrc(segments, title='', artist=''):
    """将识别结果转为 LRC 格式"""
    lines = []
    if title:
        lines.append(f"[ti:{title}]")
    if artist:
        lines.append(f"[ar:{artist}]")
    for seg in segments:
        start = seg.start if hasattr(seg, 'start') else seg['start']
        text = seg.text if hasattr(seg, 'text') else seg['text']
        text = text.strip()
        if not text:
            continue
        lines.append(f"[{fmt_lrc_time(start)}]{text}")
    return '\n'.join(lines)

def segments_to_txt(segments):
    """将识别结果转为纯文本（每行一句）"""
    lines = []
    for seg in segments:
        text = seg.text if hasattr(seg, 'text') else seg['text']
        text = text.strip()
        if text:
            lines.append(text)
    return '\n'.join(lines)

# ─── 主识别函数 ─────────────────────────────────────
def transcribe(audio_path, model_size='small', language=None,
               vad_filter=True, beam_size=5, output_dir=None):
    """
    识别音频文件中的歌词

    参数:
        audio_path: 音频文件路径
        model_size: 模型大小 (tiny, base, small, medium, large-v3)
        language: 语言代码 (zh, ja, en, ko, None=自动)
        vad_filter: 是否启用语音活动检测（推荐）
        beam_size: beam search 大小（越大越准但越慢）
        output_dir: 输出目录，None 则同目录

    返回:
        dict: {srt_path, lrc_path, txt_path, segments, language, duration}
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        cprint(C.RED, f"错误：找不到文件 {audio_path}")
        sys.exit(1)

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = audio_path.parent

    base_name = audio_path.stem

    cprint(C.CYAN + C.BOLD, f"\n{'='*60}")
    cprint(C.CYAN + C.BOLD, f"  🎵 JIZURA 歌词识别工具")
    cprint(C.CYAN + C.BOLD, f"{'='*60}")
    cprint(C.WHITE, f"  文件: {audio_path.name}")
    cprint(C.WHITE, f"  模型: {model_size}")
    cprint(C.WHITE, f"  语言: {'自动检测' if not language else language}")
    cprint(C.WHITE, f"  VAD : {'开启' if vad_filter else '关闭'}")
    cprint(C.CYAN + C.BOLD, f"{'='*60}\n")

    # 1. 加载模型
    cprint(C.YELLOW, "⏳ 正在加载识别模型...")
    cprint(C.MAGENTA, f"   （首次使用会自动下载模型文件，请耐心等待）")
    start_time = time.time()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        cprint(C.RED, "❌ 缺少 faster-whisper 库")
        cprint(C.YELLOW, "   请先运行: pip install faster-whisper")
        sys.exit(1)

    # 自动选择计算设备
    try:
        import torch
        if torch.cuda.is_available():
            device = 'cuda'
            compute_type = 'float16'
            cprint(C.GREEN, f"   ✅ 使用 GPU 加速 ({torch.cuda.get_device_name(0)})")
        else:
            device = 'cpu'
            compute_type = 'int8'
            cprint(C.YELLOW, "   ⚠️  未检测到 NVIDIA 显卡，使用 CPU（速度较慢）")
    except:
        device = 'cpu'
        compute_type = 'int8'
        cprint(C.YELLOW, "   ⚠️  未检测到 CUDA，使用 CPU（速度较慢）")

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        cprint(C.RED, f"❌ 模型加载失败: {e}")
        sys.exit(1)

    load_time = time.time() - start_time
    cprint(C.GREEN, f"   ✅ 模型加载完成（{load_time:.1f}秒）\n")

    # 2. 识别
    cprint(C.YELLOW, "🎤 正在识别歌词...")
    cprint(C.MAGENTA, "   （时间取决于音频长度和模型大小）")

    start_time = time.time()
    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=vad_filter,
            beam_size=beam_size,
            vad_parameters=dict(
                min_silence_duration_ms=500,  # 最小静音时长
                speech_pad_ms=200,           # 语音前后留白
            ),
            word_timestamps=False,
            condition_on_previous_text=True,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            no_speech_threshold=0.5,
        )
    except Exception as e:
        cprint(C.RED, f"❌ 识别失败: {e}")
        sys.exit(1)

    # 收集所有片段
    segments = []
    seg_count = 0
    last_update = 0

    for segment in segments_iter:
        segments.append(segment)
        seg_count += 1
        # 每 5 秒更新一次进度
        elapsed = time.time() - start_time
        if elapsed - last_update > 2:
            last_update = elapsed
            cur_time = fmt_time(segment.start)
            cprint(C.WHITE, f"   ⏱  已识别到 {cur_time} ... {seg_count} 行", end='\r')

    transcribe_time = time.time() - start_time
    detected_lang = info.language if hasattr(info, 'language') else (language or 'unknown')
    duration = info.duration if hasattr(info, 'duration') else 0

    cprint(C.WHITE, " " * 60)  # 清除进度行
    cprint(C.GREEN, f"   ✅ 识别完成！共 {seg_count} 行")
    cprint(C.GREEN, f"   🕐 识别语言: {detected_lang}")
    cprint(C.GREEN, f"   ⏱  用时: {transcribe_time:.1f} 秒")
    if duration:
        cprint(C.GREEN, f"   🎵 音频时长: {fmt_time(duration)}")
        cprint(C.GREEN, f"   📊 速度: {duration/transcribe_time:.1f}x 实时速度")
    print()

    # 3. 生成输出文件
    cprint(C.YELLOW, "📝 生成字幕文件...")

    srt_content = segments_to_srt(segments)
    lrc_content = segments_to_lrc(segments, title=base_name)
    txt_content = segments_to_txt(segments)

    srt_path = output_dir / f"{base_name}.srt"
    lrc_path = output_dir / f"{base_name}.lrc"
    txt_path = output_dir / f"{base_name}_歌词.txt"

    srt_path.write_text(srt_content, encoding='utf-8')
    lrc_path.write_text(lrc_content, encoding='utf-8')
    txt_path.write_text(txt_content, encoding='utf-8')

    cprint(C.GREEN, f"   ✅ SRT 字幕: {srt_path}")
    cprint(C.GREEN, f"   ✅ LRC 歌词: {lrc_path}")
    cprint(C.GREEN, f"   ✅ 纯文本  : {txt_path}")
    print()

    # 4. 显示预览
    cprint(C.CYAN + C.BOLD, "📋 识别结果预览（前 10 行）:")
    cprint(C.CYAN, "-" * 60)
    for i, seg in enumerate(segments[:10]):
        t = fmt_lrc_time(seg.start)
        cprint(C.WHITE, f"  [{t}] {seg.text.strip()[:50]}")
    if len(segments) > 10:
        cprint(C.MAGENTA, f"  ... 共 {len(segments)} 行")
    cprint(C.CYAN, "-" * 60)
    print()

    cprint(C.GREEN + C.BOLD, "🎉 全部完成！")
    cprint(C.WHITE, f"   打开 JIZURA → 点「导入字幕」→ 选择 .srt 文件即可")
    print()

    return {
        'srt_path': str(srt_path),
        'lrc_path': str(lrc_path),
        'txt_path': str(txt_path),
        'segments': segments,
        'language': detected_lang,
        'duration': duration,
    }

# ─── 命令行入口 ─────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='JIZURA 歌词识别工具 — 用 Whisper 识别音乐中的歌词',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python transcribe_lyrics.py 歌曲.mp3
  python transcribe_lyrics.py 歌曲.mp3 --model medium --language zh
  python transcribe_lyrics.py 歌曲.mp3 --model large-v3 --language ja

模型大小选择:
  tiny     - 极快，准确率一般   (~75MB)
  base     - 较快，准确率尚可   (~145MB)
  small    - 推荐，均衡之选     (~466MB)
  medium   - 较慢，准确率高     (~1.5GB)
  large-v3 - 最慢，准确率最高   (~3GB)
        """
    )
    parser.add_argument('audio', nargs='?', help='音频文件路径 (mp3/wav/m4a/flac 等)')
    parser.add_argument('--model', '-m', default='small',
                        choices=['tiny', 'base', 'small', 'medium', 'large-v3'],
                        help='识别模型大小 (默认: small)')
    parser.add_argument('--language', '-l', default=None,
                        choices=['zh', 'ja', 'en', 'ko', 'es', 'fr', 'de'],
                        help='指定语言 (默认自动检测)')
    parser.add_argument('--no-vad', action='store_true',
                        help='禁用 VAD 语音活动检测')
    parser.add_argument('--output', '-o', default=None,
                        help='输出目录 (默认: 音频同目录)')
    parser.add_argument('--beam-size', type=int, default=5,
                        help='beam search 大小 (默认: 5，越大越准越慢)')

    args = parser.parse_args()

    # 没有参数时交互式输入
    if not args.audio:
        cprint(C.CYAN + C.BOLD, "\n🎵 JIZURA 歌词识别工具")
        cprint(C.WHITE, "   请将音乐文件拖到此窗口，然后按回车")
        cprint(C.WHITE, "   或直接输入文件路径：")
        audio_input = input("\n  路径: ").strip().strip('"').strip("'")
        if not audio_input:
            cprint(C.RED, "❌ 未指定文件")
            sys.exit(1)
        args.audio = audio_input

        # 交互式选择模型
        cprint(C.WHITE, "\n   选择模型大小：")
        cprint(C.WHITE, "   1) tiny   - 最快，准确率低")
        cprint(C.WHITE, "   2) base   - 较快，准确率尚可")
        cprint(C.GREEN, "   3) small  - 【推荐】均衡之选")
        cprint(C.WHITE, "   4) medium - 较慢，准确率高")
        cprint(C.WHITE, "   5) large-v3 - 最慢，准确率最高")
        choice = input("\n  选择 (默认 3): ").strip()
        model_map = {'1': 'tiny', '2': 'base', '3': 'small', '4': 'medium', '5': 'large-v3'}
        if choice in model_map:
            args.model = model_map[choice]

        # 交互式选择语言
        cprint(C.WHITE, "\n   选择语言：")
        cprint(C.WHITE, "   1) 自动检测")
        cprint(C.WHITE, "   2) 中文")
        cprint(C.WHITE, "   3) 日语")
        cprint(C.WHITE, "   4) 英语")
        cprint(C.WHITE, "   5) 韩语")
        lang_choice = input("\n  选择 (默认 1): ").strip()
        lang_map = {'1': None, '2': 'zh', '3': 'ja', '4': 'en', '5': 'ko'}
        if lang_choice in lang_map:
            args.language = lang_map[lang_choice]

    transcribe(
        audio_path=args.audio,
        model_size=args.model,
        language=args.language,
        vad_filter=not args.no_vad,
        beam_size=args.beam_size,
        output_dir=args.output,
    )

if __name__ == '__main__':
    main()

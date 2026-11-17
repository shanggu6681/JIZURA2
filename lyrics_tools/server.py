#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JIZURA 歌词识别后端服务
提供 HTTP API 给前端页面调用，实现网页内一键识别歌词
"""

import os
import sys
import time
import shutil
import threading
import tempfile
import traceback
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

# 静态文件目录 = server.py 的上一级（JIZURA 根目录）
STATIC_DIR = Path(__file__).parent.parent.resolve()

# 模型目录 = 安装目录下的 models/
# 只有便携版/安装版里确实存在 models 目录时，才改用本地模型并离线运行；
# 普通开发环境（无 models 目录）保持默认行为：用系统缓存、允许联网。
MODELS_DIR = STATIC_DIR / 'models'
_PORTABLE = (MODELS_DIR / 'huggingface').is_dir() or (MODELS_DIR / 'torch').is_dir()
if _PORTABLE:
    os.environ.setdefault('TORCH_HOME', str(MODELS_DIR / 'torch'))
    os.environ.setdefault('HF_HOME', str(MODELS_DIR / 'huggingface'))
    os.environ.setdefault('HUGGINGFACE_HUB_CACHE', str(MODELS_DIR / 'huggingface' / 'hub'))
    os.environ.setdefault('HF_HUB_OFFLINE', '1')

# ─── 自动查找并配置 ffmpeg ─────────────────────────
def _setup_ffmpeg():
    """自动查找 ffmpeg 并添加到 PATH，确保 faster-whisper 能用"""
    # 已经能找到就不用找了
    if shutil.which('ffmpeg') and shutil.which('ffprobe'):
        return True
    
    # 优先查找安装目录下的 bin\（便携版/安装版）
    search_paths = [
        str(Path(__file__).parent.parent / 'bin'),
        r'C:\ffmpeg\bin',
        r'C:\ffmpeg-8.1.1-full_build\bin',
        r'C:\ffmpeg-7.0-full_build\bin',
        r'C:\ffmpeg-6.0-full_build\bin',
        r'C:\Program Files\ffmpeg\bin',
        r'C:\Program Files (x86)\ffmpeg\bin',
        str(Path.home() / 'scoop' / 'shims'),
        str(Path.home() / 'AppData' / 'Local' / 'Microsoft' / 'WinGet' / 'Packages' / 'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe'),
    ]
    
    # 从 PATH 里反推（有些情况 PATH 里有但子进程找不到）
    path_dirs = os.environ.get('PATH', '').split(os.pathsep)
    for d in path_dirs:
        if 'ffmpeg' in d.lower() and d not in search_paths:
            search_paths.append(d)
    
    for p in search_paths:
        ffmpeg_exe = Path(p) / 'ffmpeg.exe'
        ffprobe_exe = Path(p) / 'ffprobe.exe'
        if ffmpeg_exe.exists() and ffprobe_exe.exists():
            # 把这个目录加到 PATH 最前面
            os.environ['PATH'] = str(Path(p)) + os.pathsep + os.environ.get('PATH', '')
            # 同时设置环境变量给 faster-whisper
            os.environ['FFMPEG_BINARY'] = str(ffmpeg_exe)
            return True
    
    # 搜索整个 C 盘（慢，但保险）
    try:
        for root, dirs, files in os.walk(r'C:\\', topdown=True):
            # 跳过系统目录
            dirs[:] = [d for d in dirs if d.lower() not in 
                       ('windows', 'system32', 'syswow64', '$recycle.bin', 
                        'programdata', 'appdata', 'program files (x86)')
                       and not d.startswith('.')]
            if 'ffmpeg.exe' in files and 'ffprobe.exe' in files:
                ffmpeg_dir = root
                os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')
                return True
    except Exception:
        pass
    
    return False

_ffmpeg_ok = _setup_ffmpeg()

app = Flask(__name__)
CORS(app)

# 设置最大上传文件大小为 200MB（一首歌的 mp3 一般 5-15MB，flac 可能更大）
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# 文件太大时的错误处理
@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': '文件太大了（超过 200MB），请使用较小的音频文件'}), 413

# ─── 全局状态 ───────────────────────────────────────
_model = None
_model_size = None
_model_lock = threading.Lock()

_transcribe_status = {
    'running': False,
    'progress': 0,
    'current_time': 0,
    'total_time': 0,
    'segments_done': 0,
    'status': 'idle',  # idle, loading, transcribing, done, error
    'message': '',
    'result': None,
    'error': None,
}
_status_lock = threading.Lock()

# ─── 工具函数 ───────────────────────────────────────
def set_status(**kwargs):
    global _transcribe_status
    with _status_lock:
        _transcribe_status.update(kwargs)

def get_status():
    with _status_lock:
        return dict(_transcribe_status)

def fmt_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def fmt_lrc_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    centis = int((seconds - int(seconds)) * 100)
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"

def segments_to_output(segments, audio_name=''):
    """将识别片段转换为 SRT/LRC/TXT"""
    srt_lines = []
    lrc_lines = []
    txt_lines = []
    
    if audio_name:
        lrc_lines.append(f"[ti:{Path(audio_name).stem}]")
    
    for i, seg in enumerate(segments, 1):
        text = seg['text'].strip() if isinstance(seg, dict) else seg.text.strip()
        start = seg['start'] if isinstance(seg, dict) else seg.start
        end = seg['end'] if isinstance(seg, dict) else seg.end
        
        if not text:
            continue
        
        srt_lines.append(str(i))
        srt_lines.append(f"{fmt_srt_time(start)} --> {fmt_srt_time(end)}")
        srt_lines.append(text)
        srt_lines.append('')
        
        lrc_lines.append(f"[{fmt_lrc_time(start)}]{text}")
        txt_lines.append(text)
    
    return {
        'srt': '\n'.join(srt_lines),
        'lrc': '\n'.join(lrc_lines),
        'txt': '\n'.join(txt_lines),
        'count': len(txt_lines),
    }

def _detect_gpu():
    """检测是否有可用的 GPU（优先用 ctranslate2 自带检测）"""
    try:
        import ctranslate2
        # ctranslate2 支持的设备列表里有 cuda 就是有 GPU
        devices = getattr(ctranslate2, 'get_supported_devices', lambda: [])()
        if 'cuda' in devices:
            return True
        # 直接试试能不能创建 cuda 模型（最准确）
        try:
            from faster_whisper import WhisperModel
            m = WhisperModel('tiny', device='cuda', compute_type='float16')
            del m
            return True
        except Exception:
            return False
    except Exception:
        pass
    
    # 备选：用 torch 检测
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        pass
    
    return False

def _get_gpu_name():
    """获取 GPU 名称"""
    try:
        import ctranslate2
        # 从 ctranslate2 拿不到 GPU 名称，用 nvidia-smi 查
        import subprocess
        result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader,nounits'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0].strip()
    except Exception:
        pass
    
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    
    return 'NVIDIA GPU'

# ─── 模型加载 ───────────────────────────────────────
def load_model(model_size='small'):
    global _model, _model_size
    
    with _model_lock:
        if _model is not None and _model_size == model_size:
            return _model
        
        set_status(status='loading', message=f'正在加载模型 {model_size}...')
        
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError('缺少 faster-whisper，请先运行: pip install faster-whisper')
        
        # 自动选择设备（优先 GPU）
        has_gpu = _detect_gpu()
        if has_gpu:
            device = 'cuda'
            compute_type = 'float16'
            gpu_name = _get_gpu_name()
            set_status(message=f'使用 GPU: {gpu_name}（float16）')
        else:
            device = 'cpu'
            compute_type = 'int8'
            set_status(message='使用 CPU（速度较慢）')
        
        # 优先从安装目录加载模型（便携版/安装版）
        local_model = MODELS_DIR / f'whisper-{model_size}'
        if local_model.exists():
            _model = WhisperModel(str(local_model), device=device, compute_type=compute_type)
        else:
            _model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _model_size = model_size

        return _model


# ─── Demucs 人声分离 ─────────────────────────────────
_demucs_model = None
_demucs_lock = threading.Lock()

def _detect_demucs_gpu():
    """检测 demucs 是否能用 GPU"""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

def load_demucs_model(model_name='htdemucs'):
    """加载 Demucs 人声分离模型"""
    global _demucs_model
    
    with _demucs_lock:
        # 检查是否已加载（用 model_name 比较）
        if _demucs_model is not None and getattr(_demucs_model, '_model_name', None) == model_name:
            return _demucs_model
        
        set_status(status='separating', progress=0, message='正在加载人声分离模型...')
        
        try:
            import torch
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
        except ImportError:
            # 自动安装 torch + demucs（首次使用人声分离时触发）
            set_status(status='separating', progress=0, 
                      message='首次使用人声分离，正在自动安装依赖（torch+demucs）...\n体积较大，请耐心等待几分钟...')
            
            import subprocess
            import sys as _sys
            
            # 检测 NVIDIA GPU
            has_nvidia = False
            try:
                _r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=5)
                has_nvidia = _r.returncode == 0 and _r.stdout.strip()
            except Exception:
                pass
            
            # 安装 torch + torchaudio
            if has_nvidia:
                set_status(message='检测到 NVIDIA GPU，正在安装 GPU 版 torch...')
                subprocess.run([_sys.executable, '-m', 'pip', 'install', 'torch', 'torchaudio',
                               '--index-url', 'https://download.pytorch.org/whl/cu124'], check=True)
            else:
                set_status(message='未检测到 NVIDIA GPU，正在安装 CPU 版 torch...')
                subprocess.run([_sys.executable, '-m', 'pip', 'install', 'torch', 'torchaudio'], check=True)
            
            # 安装 demucs
            set_status(message='正在安装 demucs...')
            subprocess.run([_sys.executable, '-m', 'pip', 'install', 'demucs'], check=True)
            
            set_status(message='依赖安装完成，正在加载模型...')
            
            # 重新导入
            import torch
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
        
        has_gpu = _detect_demucs_gpu()
        device = 'cuda' if has_gpu else 'cpu'
        
        model = get_model(model_name)
        model.to(device)
        model.eval()
        
        # 保存元信息
        model._model_name = model_name
        model._device = device
        model._has_gpu = has_gpu
        # 获取 sources 列表（BagOfModels 通过 .sources 属性访问）
        model._sources_list = list(model.sources)
        
        _demucs_model = model
        return model

def separate_vocals(audio_path, output_dir=None, model_name='htdemucs'):
    """
    使用 Demucs 分离人声和伴奏
    返回人声文件路径
    """
    import tempfile
    
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='demucs_')
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    model = load_demucs_model(model_name)
    device = getattr(model, '_device', 'cpu')
    has_gpu = getattr(model, '_has_gpu', False)
    
    set_status(
        status='separating',
        progress=5,
        message=f'正在分离人声（{"GPU" if has_gpu else "CPU"}）...',
    )
    
    try:
        import torch
        import torchaudio
        import subprocess
        import numpy as np
        from demucs.apply import apply_model

        # 用 ffmpeg 解码音频（不依赖 torchcodec）
        ffmpeg_exe = shutil.which('ffmpeg') or os.environ.get('FFMPEG_BINARY', 'ffmpeg')
        result = subprocess.run(
            [ffmpeg_exe, '-i', str(audio_path),
             '-f', 'f32le', '-acodec', 'pcm_f32le',
             '-ac', '2', '-ar', '44100',
             '-v', 'quiet', '-'],
            capture_output=True
        )
        if not result.stdout:
            raise RuntimeError(f'ffmpeg 解码失败: {result.stderr.decode("utf-8", errors="replace")[:500]}')
        data = np.frombuffer(result.stdout, dtype=np.float32).copy()
        wav = torch.from_numpy(data).reshape(-1, 2).t()
        sr = 44100
        # 确保是立体声
        if wav.dim() == 1:
            wav = wav.unsqueeze(0).repeat(2, 1)
        elif wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        
        # 重采样到模型需要的采样率
        model_sr = getattr(model, 'samplerate', None)
        if model_sr is None:
            # BagOfModels: 从第一个子模型获取
            if hasattr(model, 'models') and len(model.models) > 0:
                model_sr = model.models[0].samplerate
            else:
                model_sr = 44100  # 默认值
        
        if sr != model_sr:
            resampler = torchaudio.transforms.Resample(sr, model_sr)
            wav = resampler(wav)
            sr = model_sr
        
        # 增加 batch 维度: [channels, samples] -> [batch, channels, samples]
        wav = wav.unsqueeze(0)
        
        # 应用模型
        set_status(status='separating', progress=20, message='正在分离人声...')
        
        with torch.no_grad():
            sources = apply_model(model, wav, device=device, split=True, overlap=0.25)
        
        set_status(status='separating', progress=80, message='正在保存人声...')
        
        # sources shape: [batch, sources, channels, samples]
        # htdemucs 的 sources 顺序: drums, bass, other, vocals
        sources_list = getattr(model, '_sources_list', list(model.sources))
        vocal_idx = sources_list.index('vocals') if 'vocals' in sources_list else -1
        
        if vocal_idx < 0:
            raise RuntimeError(f'模型没有人声轨道，可用轨道: {sources_list}')
        
        vocals = sources[0, vocal_idx]  # [channels, samples]
        
        # 保存人声文件（用 wave 模块，不依赖 torchcodec）
        import wave
        vocal_path = output_dir / 'vocals.wav'
        vocals_np = vocals.cpu().numpy()
        # 转为 16-bit PCM
        vocals_int16 = np.clip(vocals_np * 32767, -32768, 32767).astype(np.int16)
        n_channels = vocals_int16.shape[0]
        # 交错声道: [channels, samples] -> [samples, channels] -> flatten
        interleaved = vocals_int16.T.reshape(-1)
        with wave.open(str(vocal_path), 'wb') as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(interleaved.tobytes())
        
        set_status(status='separating', progress=95, message='人声分离完成！')
        
        return str(vocal_path)
        
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"人声分离失败: {e}")
        print(tb_str)
        raise

# ─── 识别线程 ───────────────────────────────────────
def transcribe_worker(audio_path, model_size, language, do_vocal_sep=False, demucs_model='htdemucs'):
    original_audio = audio_path
    vocal_file = None
    
    try:
        # 如果需要先分离人声
        if do_vocal_sep:
            set_status(
                status='separating',
                progress=0,
                message='准备分离人声...',
            )
            vocal_file = separate_vocals(audio_path, model_name=demucs_model)
            audio_path = vocal_file
        
        model = load_model(model_size)
        
        set_status(
            status='transcribing',
            progress=5,
            message='正在识别歌词...',
            segments_done=0,
        )
        
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            beam_size=5,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
            word_timestamps=False,
            condition_on_previous_text=True,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            no_speech_threshold=0.5,
        )
        
        segments = []
        total_dur = info.duration if hasattr(info, 'duration') else 0
        
        for segment in segments_iter:
            segments.append({
                'start': segment.start,
                'end': segment.end,
                'text': segment.text,
            })
            
            # 更新进度
            if total_dur > 0:
                base_progress = 45 if do_vocal_sep else 5
                progress_range = 50 if do_vocal_sep else 90
                progress = min(95, int((segment.end / total_dur) * progress_range) + base_progress)
                set_status(
                    progress=progress,
                    current_time=segment.end,
                    total_time=total_dur,
                    segments_done=len(segments),
                )
        
        # 生成输出
        output = segments_to_output(segments, Path(original_audio).name)
        
        set_status(
            status='done',
            progress=100,
            message=f'识别完成！共 {output["count"]} 行',
            segments_done=output['count'],
            running=False,
            result={
                'srt': output['srt'],
                'lrc': output['lrc'],
                'txt': output['txt'],
                'count': output['count'],
                'language': info.language if hasattr(info, 'language') else language,
                'duration': total_dur,
                'used_vocal_separation': do_vocal_sep,
            },
            error=None,
        )
        
        # 清理临时文件
        try:
            os.unlink(original_audio)
        except:
            pass
        try:
            if vocal_file and os.path.exists(vocal_file):
                os.unlink(vocal_file)
                # 清理父目录
                vocal_dir = Path(vocal_file).parent
                if vocal_dir.name.startswith('demucs_'):
                    import shutil
                    shutil.rmtree(vocal_dir, ignore_errors=True)
        except:
            pass
        
    except Exception as e:
        tb_str = traceback.format_exc()
        print(tb_str)  # 打印到控制台
        set_status(
            status='error',
            message=f'识别失败: {str(e)}',
            error=str(e),
            running=False,
            traceback=tb_str,  # 保存完整堆栈供调试
        )
        # 清理临时文件
        try:
            os.unlink(original_audio)
        except:
            pass
        try:
            if vocal_file and os.path.exists(vocal_file):
                os.unlink(vocal_file)
        except:
            pass

# ─── API 路由 ───────────────────────────────────────

@app.route('/api/health')
def health():
    """健康检查"""
    # 检查 demucs 是否可用
    demucs_available = False
    demucs_gpu = False
    try:
        import demucs
        demucs_available = True
        demucs_gpu = _detect_demucs_gpu()
    except Exception:
        pass
    
    return jsonify({
        'ok': True,
        'model_loaded': _model is not None,
        'model_size': _model_size,
        'demucs_available': demucs_available,
        'demucs_gpu': demucs_gpu,
        'demucs_loaded': _demucs_model is not None,
    })

@app.route('/api/status')
def status():
    """获取识别状态"""
    return jsonify(get_status())

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """开始识别（支持上传文件或本地路径）"""
    try:
        # 检查 ffmpeg
        if not _ffmpeg_ok:
            return jsonify({'error': '找不到 ffmpeg！请安装 ffmpeg 后再使用 AI 识别。下载地址：https://www.gyan.dev/ffmpeg/builds/'}), 400
        
        st = get_status()
        if st['status'] not in ('idle', 'done', 'error'):
            return jsonify({'error': '正在识别中，请稍候...'}), 400
        
        # 重置状态
        set_status(
            running=True,
            progress=0,
            current_time=0,
            total_time=0,
            segments_done=0,
            status='loading',
            message='准备中...',
            result=None,
            error=None,
        )
        
        audio_path = None
        
        # 处理文件上传
        if 'file' in request.files:
            f = request.files['file']
            if not f or not f.filename:
                set_status(status='error', message='没有上传文件', error='no file')
                return jsonify({'error': '没有上传文件'}), 400
            
            # 保存到临时文件
            suffix = Path(f.filename).suffix or '.mp3'
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            f.save(tmp.name)
            tmp.close()
            audio_path = tmp.name
            
            # 检查文件大小
            file_size = Path(audio_path).stat().st_size
            if file_size < 1024:  # 小于 1KB 肯定有问题
                os.unlink(audio_path)
                set_status(status='error', message='文件太小，可能上传失败', error='file too small')
                return jsonify({'error': '文件太小，可能上传失败'}), 400
            
        elif request.json and 'path' in request.json:
            # 本地路径（用于测试或同机调用）
            audio_path = request.json['path']
            if not Path(audio_path).exists():
                set_status(status='error', message=f'找不到文件: {audio_path}', error='file not found')
                return jsonify({'error': f'找不到文件: {audio_path}'}), 400
        else:
            set_status(status='error', message='请上传音频文件', error='no file')
            return jsonify({'error': '请上传音频文件'}), 400
        
        model_size = request.form.get('model', 'small') if request.form else (
            request.json.get('model', 'small') if request.json else 'small'
        )
        language = request.form.get('language') if request.form else (
            request.json.get('language') if request.json else None
        )
        # 人声分离选项
        separate_vocals_param = request.form.get('separate_vocals', 'false') if request.form else (
            str(request.json.get('separate_vocals', False)) if request.json else 'false'
        )
        do_vocal_sep = separate_vocals_param.lower() in ('true', '1', 'yes', 'on')
        
        demucs_model = request.form.get('demucs_model', 'htdemucs') if request.form else (
            request.json.get('demucs_model', 'htdemucs') if request.json else 'htdemucs'
        )
        
        # 验证模型参数
        valid_models = {'tiny', 'base', 'small', 'medium', 'large-v3'}
        if model_size not in valid_models:
            model_size = 'small'
        
        # 启动识别线程
        t = threading.Thread(
            target=transcribe_worker,
            args=(audio_path, model_size, language, do_vocal_sep, demucs_model),
            daemon=True
        )
        t.start()
        
        return jsonify({
            'ok': True,
            'message': '开始识别',
            'model': model_size,
            'separate_vocals': do_vocal_sep,
        })
    
    except Exception as e:
        traceback.print_exc()
        err_msg = f'启动识别失败: {str(e)}'
        set_status(status='error', message=err_msg, error=str(e))
        return jsonify({'error': err_msg}), 500

@app.route('/api/reset', methods=['POST'])
def reset():
    """重置状态"""
    set_status(
        running=False,
        progress=0,
        current_time=0,
        total_time=0,
        segments_done=0,
        status='idle',
        message='',
        result=None,
        error=None,
    )
    return jsonify({'ok': True})

@app.route('/api/models')
def list_models():
    """返回可用的模型列表"""
    return jsonify({
        'models': [
            {'id': 'tiny', 'name': 'tiny', 'size': '~75MB', 'speed': '极快', 'accuracy': '一般'},
            {'id': 'base', 'name': 'base', 'size': '~145MB', 'speed': '快', 'accuracy': '尚可'},
            {'id': 'small', 'name': 'small', 'size': '~466MB', 'speed': '中等', 'accuracy': '推荐', 'default': True},
            {'id': 'medium', 'name': 'medium', 'size': '~1.5GB', 'speed': '慢', 'accuracy': '高'},
            {'id': 'large-v3', 'name': 'large-v3', 'size': '~3GB', 'speed': '很慢', 'accuracy': '最高'},
        ]
    })

# 根路径：重定向到中文首页
@app.route('/')
def root():
    return redirect('/zh-hans/', code=302)

# 静态文件：直接从 STATIC_DIR 提供（优先于通配符，/api/ 路径由上面的路由处理）
@app.route('/<path:filepath>')
def serve_static(filepath):
    # API 请求不在这里处理
    if filepath.startswith('api/'):
        return jsonify({'error': 'not found'}), 404
    
    # 目录路径 → 找 index.html
    full_path = STATIC_DIR / filepath
    if full_path.is_dir():
        full_path = full_path / 'index.html'
    
    if full_path.exists() and full_path.is_file():
        return send_from_directory(str(full_path.parent), full_path.name)
    
    return 'Not Found', 404

# ─── 主入口 ─────────────────────────────────────────
def main():
    port = int(os.environ.get('JIZURA_PORT', 8080))
    host = os.environ.get('JIZURA_HOST', '127.0.0.1')
    
    print("=" * 60)
    print("  JIZURA 歌词识别服务")
    print("=" * 60)
    print(f"  地址: http://{host}:{port}")
    print(f"  页面: http://{host}:{port}/zh-hans/")
    
    # ffmpeg 状态
    if _ffmpeg_ok:
        import shutil
        ff = shutil.which('ffmpeg')
        print(f"  ffmpeg: 已找到 ({ff})")
    else:
        print(f"  ffmpeg: 未找到（AI 识别将无法使用）")
    
    # 检查 Demucs 人声分离（注意：必须在 faster-whisper 之前初始化 PyTorch，避免 cuDNN 冲突）
    demucs_available = False
    demucs_gpu = False
    try:
        import demucs
        demucs_gpu = _detect_demucs_gpu()
        demucs_available = True
        print(f"  人声分离: 已安装（Demucs htdemucs，{'GPU加速' if demucs_gpu else 'CPU模式'}）")
    except ImportError:
        print(f"  人声分离: 未安装（可选，pip install demucs torchaudio）")
    
    # 检查 GPU（faster-whisper，必须在 demucs/PyTorch 之后检查，避免 cuDNN 冲突）
    has_gpu = _detect_gpu()
    if has_gpu:
        gpu_name = _get_gpu_name()
        print(f"  GPU: {gpu_name}（已启用 CUDA 加速）")
    else:
        print(f"  GPU: 未检测到，将使用 CPU（较慢）")
    
    print("=" * 60)
    print()
    
    app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == '__main__':
    main()

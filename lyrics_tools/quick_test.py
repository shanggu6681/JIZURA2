# -*- coding: utf-8 -*-
import requests, time

test_file = r"D:\AItools\GPT-SoVITS-v2pro-20250604\douyin-mcp-server\extracted_audio\7641989988095102258_20260628_102444.mp3"

# 重置
requests.post('http://127.0.0.1:8080/api/reset')

# 开始识别
with open(test_file, 'rb') as f:
    files = {'file': ('test.mp3', f, 'audio/mpeg')}
    data = {'model': 'tiny', 'language': 'zh'}
    resp = requests.post('http://127.0.0.1:8080/api/transcribe', files=files, data=data, timeout=30)
print(f'启动: {resp.status_code}')
print(resp.text[:200])
print()

# 等待完成
for i in range(30):
    time.sleep(1)
    st = requests.get('http://127.0.0.1:8080/api/status').json()
    if st['status'] == 'done':
        cnt = st['result']['count']
        print(f'完成！{cnt} 行')
        break
    if st['status'] == 'error':
        print(f'错误: {st["error"]}')
        break
    if i % 5 == 0:
        print(f'  进度: {st["progress"]}% - {st["message"]}')

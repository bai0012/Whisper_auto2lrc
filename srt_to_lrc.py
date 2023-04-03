import os
import re
import sys

def srt_to_lrc(srt_path):
    # 读取srt文件
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    # 使用正则表达式提取出每行字幕的时间轴和内容
    pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n'
    matches = re.findall(pattern, srt_content, re.DOTALL)

    # 将时间轴转换为lrc格式
    lrc_content = ''
    for i, match in enumerate(matches):
        start_time = match[1].replace(',', '.')
        lrc_content += f'[{start_time}] {match[3]}'

        # 如果不是最后一行字幕，则需要添加换行符
        if i != len(matches) - 1:
            lrc_content += '\n'

    # 将lrc内容写入同名文件，但后缀名为.lrc
    lrc_path = os.path.splitext(srt_path)[0] + '.lrc'
    with open(lrc_path, 'w', encoding='utf-8') as f:
        f.write(lrc_content)

    # 删除原srt文件
    os.remove(srt_path)

if __name__ == '__main__':
    # 从命令行参数中获取srt文件路径
    srt_path = sys.argv[1]

    # 调用srt_to_lrc函数进行转换和删除操作
    srt_to_lrc(srt_path)

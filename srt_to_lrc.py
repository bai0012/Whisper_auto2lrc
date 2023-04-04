import sys
import os

def srt_to_lrc(srt_file_path):
    lrc_file_path = srt_file_path.replace('.srt', '.lrc')
    with open(srt_file_path, 'r', encoding='utf-8-sig') as srt_file, \
         open(lrc_file_path, 'w', encoding='utf-8-sig') as lrc_file:
        lines = srt_file.readlines()
        for i in range(0, len(lines), 4):
            time_start, time_end = lines[i+1].strip().split(' --> ')
            time_start = convert_time(time_start)
            time_end = convert_time(time_end)
            lrc_file.write(f"[{time_start}]{lines[i+2]}")
            lrc_file.write(f"[{time_end}]\n")

    os.remove(srt_file_path)
    #print(f'Successfully converted {srt_file_path} to {lrc_file_path}')

def convert_time(time_string):
    time_parts = time_string.split(':')
    minutes = int(time_parts[0]) * 60 + int(time_parts[1])
    seconds = float(time_parts[2].replace(',', '.'))
    return f"{minutes:02d}:{seconds:05.2f}"

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Wrong!')
    else:
        srt_to_lrc(sys.argv[1])

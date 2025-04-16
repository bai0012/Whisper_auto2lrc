import sys
import os
from pathlib import Path
import re

# Regex to parse SRT time: HH:MM:SS,ms
SRT_TIME_REGEX = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})')

def convert_srt_time_to_lrc(time_string):
    """Converts SRT time format (HH:MM:SS,ms) to LRC time format [MM:SS.xx]."""
    match = SRT_TIME_REGEX.match(time_string)
    if not match:
        # Handle potential variations or errors if necessary
        # For simplicity, assume valid format for now
        return "00:00.00" # Default or raise error

    h, m, s, ms = map(int, match.groups())

    total_seconds = h * 3600 + m * 60 + s + ms / 1000.0

    lrc_minutes = int(total_seconds // 60)
    lrc_seconds = total_seconds % 60

    # Format seconds to MM:SS.xx (centiseconds)
    # {:05.2f} ensures leading zero for seconds < 10 and two decimal places
    lrc_time_str = f"{lrc_minutes:02d}:{lrc_seconds:05.2f}"
    return lrc_time_str

def srt_to_lrc(srt_file_path: Path):
    """
    Converts an SRT subtitle file to a standard LRC lyrics file.
    Only uses the start time of each subtitle line.
    Deletes the source SRT file upon successful conversion.

    Args:
        srt_file_path (Path): Path object for the input SRT file.

    Returns:
        Path: Path object for the created LRC file, or None if conversion failed.
    """
    if not srt_file_path.is_file():
        print(f"Error: SRT file not found at {srt_file_path}", file=sys.stderr)
        return None

    # Output LRC file will be in the same directory as the SRT (temp dir)
    lrc_file_path = srt_file_path.with_suffix('.lrc')

    try:
        # Use utf-8, try utf-8-sig if BOM is present
        encoding_to_try = 'utf-8'
        try:
            with open(srt_file_path, 'r', encoding=encoding_to_try) as infile:
                srt_content = infile.read()
        except UnicodeDecodeError:
            encoding_to_try = 'utf-8-sig' # Try again with BOM handling
            with open(srt_file_path, 'r', encoding=encoding_to_try) as infile:
                 srt_content = infile.read()

        # Split into blocks (index, time, text, blank line)
        # Handle potential \r\n or \n line endings
        blocks = srt_content.strip().split('\n\n')
        if len(blocks) == 1 and '\r\n\r\n' in srt_content:
            blocks = srt_content.strip().split('\r\n\r\n')


        with open(lrc_file_path, 'w', encoding='utf-8') as lrc_file: # Write standard utf-8
            for block in blocks:
                lines = block.strip().splitlines()
                if len(lines) >= 3: # Need at least index, time, text
                    # Line 1 is index (ignore)
                    # Line 2 contains timecodes
                    time_line = lines[1]
                    # Text can span multiple lines (lines[2:])
                    text_content = " ".join(lines[2:]).strip()

                    if '-->' in time_line:
                        time_start_str = time_line.split('-->')[0].strip()
                        lrc_time = convert_srt_time_to_lrc(time_start_str)
                        # Write LRC line: [MM:SS.xx]Text
                        lrc_file.write(f"[{lrc_time}]{text_content}\n")

        # Conversion successful, delete original SRT
        try:
            srt_file_path.unlink()
        except OSError as e:
            print(f"Warning: Could not delete source SRT file {srt_file_path}: {e}", file=sys.stderr)

        # print(f'Successfully converted {srt_file_path.name} to {lrc_file_path.name}')
        return lrc_file_path

    except Exception as e:
        print(f"Error converting {srt_file_path.name} to LRC: {e}", file=sys.stderr)
        # Attempt to clean up partially written LRC file if error occurred
        if lrc_file_path.exists():
            try:
                lrc_file_path.unlink()
            except OSError:
                 pass # Ignore cleanup error
        return None


# --- Command Line Interface (for testing srt_to_lrc.py directly) ---
if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python srt_to_lrc.py <path_to_srt_file>')
        sys.exit(1)
    else:
        input_path = Path(sys.argv[1])
        result_path = srt_to_lrc(input_path)
        if result_path:
             print(f"Conversion successful. LRC file saved to: {result_path}")
             sys.exit(0)
        else:
             print("Conversion failed.")
             sys.exit(1)
import subprocess
import re
import time

import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

video_channel = CompressedVideoChannel("/video")


def extract_nal_units(buffer):
    # Match both 3-byte and 4-byte start codes using a lookahead regex
    pattern = re.compile(b"(?=(\x00\x00\x01|\x00\x00\x00\x01))")
    starts = [m.start() for m in pattern.finditer(buffer)]
    nal_units = []

    for i in range(len(starts)):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else len(buffer)
        nal = buffer[start:end]
        if len(nal) > 4:
            nal_units.append(nal)

    # Return NALs and the buffer tail (could be incomplete NAL)
    if starts:
        return nal_units, buffer[starts[-1] :]
    else:
        return [], buffer


def nal_type(nal):
    # Supports both 3-byte and 4-byte start codes
    if nal.startswith(b"\x00\x00\x00\x01"):
        return nal[4] & 0x1F
    elif nal.startswith(b"\x00\x00\x01"):
        return nal[3] & 0x1F
    return None


def mjpeg_to_h264_stream(url):
    cmd = [
        "ffmpeg",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        url,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-g",
        "30",
        "-keyint_min",
        "30",
        "-sc_threshold",
        "0",
        "-force_key_frames",
        "expr:gte(t,n_forced*1)",
        "-x264-params",
        "repeat-headers=1",
        "-f",
        "h264",
        "-loglevel",
        "quiet",
        "pipe:1",
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**7)

    buffer = b""
    sps = None
    pps = None
    access_unit = []

    def nal_type(nal):
        return nal[4] & 0x1F if len(nal) > 4 else None

    def flush_unit():
        if access_unit:
            full_frame = b"".join(access_unit)
            ts = Timestamp.from_epoch_secs(time.time())
            msg = CompressedVideo(timestamp=ts, data=full_frame, format="h264")
            video_channel.log(msg)
            access_unit.clear()
            yield msg

    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk

        nal_units, buffer = extract_nal_units(buffer)

        for nal in nal_units:
            t = nal_type(nal)
            print(f"NAL prefix: {nal[:5].hex()} → type: {t}")

            if t == 7:
                sps = nal
            elif t == 8:
                pps = nal
            elif t in (1, 5):
                # Start of a new access unit = flush previous
                yield from flush_unit()

                if t == 5:  # IDR
                    print("🎯 IDR frame found")
                    access_unit.extend([sps, pps])  # prepend SPS/PPS
                access_unit.append(nal)
            else:
                # Append slice or filler to current AU
                access_unit.append(nal)

    yield from flush_unit()
    process.stdout.close()
    process.wait()


if __name__ == "__main__":
    foxglove.set_log_level("DEBUG")

    # Log to both MCAP and Foxglove Web
    file_name = "quickstart-python.mcap"
    writer = foxglove.open_mcap(file_name)
    server = foxglove.start_server()

    url = "http://oxos-test-server:8081/camera/video/overview"
    for i, frame in enumerate(mjpeg_to_h264_stream(url)):
        print(None)

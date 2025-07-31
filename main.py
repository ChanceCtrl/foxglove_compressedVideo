import subprocess
import time
import re

import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

video_channel = CompressedVideoChannel("/video")


def nal_type(nal):
    if nal.startswith(b"\x00\x00\x00\x01"):
        return nal[4] & 0x1F
    elif nal.startswith(b"\x00\x00\x01"):
        return nal[3] & 0x1F
    return None


def extract_nal_units(buffer):
    pattern = re.compile(b"(?=(\x00\x00\x01|\x00\x00\x00\x01))")
    starts = [m.start() for m in pattern.finditer(buffer)]
    nal_units = []
    for i in range(len(starts)):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else len(buffer)
        nal = buffer[start:end]
        if nal.startswith(b"\x00\x00\x01"):
            nal = b"\x00" + nal
        if len(nal) > 4:
            nal_units.append(nal)
    tail = buffer[starts[-1]:] if starts else buffer
    return nal_units, tail


def stream_h264(url):
    cmd = [
        "ffmpeg",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-i", url,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-g", "30",
        "-keyint_min", "30",
        "-sc_threshold", "0",
        "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-x264-params", "repeat-headers=1:aud=1",  # Important
        "-f", "h264",
        "-loglevel", "quiet",
        "pipe:1",
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**7)
    buffer = b""
    access_unit = []
    sps, pps = None, None
    last_flush_time = time.time()
    flush_interval = 0.5

    def flush():
        nonlocal access_unit, last_flush_time
        if access_unit:
            data = b''.join(access_unit)
            ts = Timestamp.from_epoch_secs(time.time())
            msg = CompressedVideo(
                timestamp=ts,
                frame_id="camera",
                data=data,
                format="h264"
            )
            video_channel.log(msg)
            print(f"Frame sent ({len(data)} bytes, {len(access_unit)} NALs)")
            access_unit.clear()
            last_flush_time = time.time()

    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk
        nal_units, buffer = extract_nal_units(buffer)

        for nal in nal_units:
            t = nal_type(nal)
            if t is None:
                continue

            if t == 7:
                sps = nal
            elif t == 8:
                pps = nal
            elif t == 9:
                flush()  # End of previous access unit
                continue
            elif t == 5:  # IDR
                # Begin new access unit with SPS/PPS
                access_unit = []
                access_unit.extend(filter(None, [sps, pps]))
                access_unit.append(nal)
            else:
                access_unit.append(nal)

        # Optional: timeout-based flush if AUD missing
        if access_unit and (time.time() - last_flush_time) > flush_interval:
            flush()

    flush()
    process.stdout.close()
    process.wait()


if __name__ == "__main__":
    foxglove.set_log_level("DEBUG")
    writer = foxglove.open_mcap("quickstart-python.mcap")
    server = foxglove.start_server()

    url = "http://oxos-test-server:8081/camera/video/overview"

    for _ in stream_h264(url):
        pass

import subprocess
import re
import time

import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

video_channel = CompressedVideoChannel("/video")


def nal_type(nal):
    # Supports both 3-byte and 4-byte start codes
    if nal.startswith(b"\x00\x00\x00\x01"):
        return nal[4] & 0x1F
    elif nal.startswith(b"\x00\x00\x01"):
        return nal[3] & 0x1F
    return None


def extract_nal_units(buffer):
    # Match 3 or 4 byte start codes, but always normalize to 4-byte start code in output NAL units
    pattern = re.compile(b"(?=(\x00\x00\x01|\x00\x00\x00\x01))")
    starts = [m.start() for m in pattern.finditer(buffer)]
    nal_units = []

    for i in range(len(starts)):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else len(buffer)
        nal = buffer[start:end]

        # Normalize start code to 4 bytes
        if nal.startswith(b"\x00\x00\x01"):
            nal = b"\x00" + nal  # prepend zero to make 4-byte start code

        if len(nal) > 4:
            nal_units.append(nal)

    # Return NALs and tail buffer (could be incomplete)
    if starts:
        return nal_units, buffer[starts[-1] :]
    else:
        return [], buffer


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

    def flush_frame():
        nonlocal access_unit
        if access_unit:
            full_data = b"".join(access_unit)
            ts = Timestamp.from_epoch_secs(time.time())
            msg = CompressedVideo(
                timestamp=ts, frame_id="camera", data=full_data, format="h264"
            )
            video_channel.log(msg)
            yield msg
        access_unit = []

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
            print(f"NAL prefix: {nal[:5].hex()} → type: {t}")

            if t == 7:  # SPS
                sps = nal
                continue
            elif t == 8:  # PPS
                pps = nal
                continue
            elif t == 9:  # AUD
                # flush current frame on AUD
                yield from flush_frame()
                # skip AUD itself
                continue
            elif t == 6:  # SEI
                # skip SEI to avoid issues
                continue
            elif t == 5:  # IDR keyframe
                # flush any previous frame first
                yield from flush_frame()
                # prepend SPS and PPS to keyframe
                access_unit.extend(filter(None, [sps, pps]))
                access_unit.append(nal)
                # flush this keyframe immediately
                yield from flush_frame()
                continue
            else:
                # non-IDR VCL or other NALs
                access_unit.append(nal)

    # Final flush on end of stream
    yield from flush_frame()

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

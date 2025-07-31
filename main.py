import subprocess
import time

import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

video_channel = CompressedVideoChannel("/video")


def mjpeg_to_h264_stream(url):
    cmd = [
        "ffmpeg",
        "-i",
        url,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-x264-params",
        "keyint=30:min-keyint=30:scenecut=0:repeat-headers=1",
        "-f",
        "h264",
        "-loglevel",
        "quiet",
        "pipe:1",
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**7)

    start_code = b"\x00\x00\x00\x01"
    buffer = b""
    access_unit = []

    def nal_type(nal):
        return nal[4] & 0x1F  # Extract NAL type from 1st byte after start code

    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk

        while True:
            first = buffer.find(start_code)
            if first == -1:
                break
            second = buffer.find(start_code, first + 4)
            if second == -1:
                break

            nal = buffer[first:second]
            buffer = buffer[second:]
            t = nal_type(nal)

            # If this is a new slice, flush previous access unit first
            if t in (1, 5):  # non-IDR or IDR
                if access_unit:
                    frame_data = b"".join(access_unit)
                    timestamp = Timestamp.from_epoch_secs(time.time())
                    msg = CompressedVideo(
                        timestamp=timestamp, data=frame_data, format="h264"
                    )
                    video_channel.log(msg)
                    yield msg
                    access_unit = []

            access_unit.append(nal)

    # Flush final frame
    if access_unit:
        frame_data = b"".join(access_unit)
        timestamp = Timestamp.from_epoch_secs(time.time())
        msg = CompressedVideo(timestamp=timestamp, data=frame_data, format="h264")
        video_channel.log(msg)
        yield msg

    process.stdout.close()
    process.wait()


if __name__ == "__main__":
    foxglove.set_log_level("DEBUG")

    # We'll log to both an MCAP file, and to a running Foxglove app via a server.
    file_name = "quickstart-python.mcap"
    writer = foxglove.open_mcap(file_name)
    server = foxglove.start_server()

    url = "http://oxos-test-server:8081/camera/video/overview"
    for i, frame in enumerate(mjpeg_to_h264_stream(url)):
        print(frame)
        print("\n\n")

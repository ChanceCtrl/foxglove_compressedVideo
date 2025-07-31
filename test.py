import subprocess
import datetime

class CompressedVideo:
    def __init__(self, timestamp, frame_id, data, format):
        self.timestamp = timestamp
        self.frame_id = frame_id
        self.data = data
        self.format = format

    def __repr__(self):
        return f"<CompressedVideo timestamp={self.timestamp} frame_id={self.frame_id} format={self.format} data_len={len(self.data)}>"

def mjpeg_to_h264_stream(url, frame_id='camera_optical_center', format='h264'):
    """
    Use ffmpeg to read MJPEG stream and transcode to raw H264 Annex B.
    Then parse H264 stream by NAL units and yield CompressedVideo frames.
    """
    # FFmpeg command:
    # - Input: MJPEG stream from URL
    # - Output: raw H264 Annex B stream to stdout
    # - Copy audio disabled, video transcoded to H264
    cmd = [
        'ffmpeg',
        '-i', url,
        '-an',  # disable audio
        '-c:v', 'libx264',
        '-preset', 'ultrafast',  # low latency
        '-f', 'h264',
        '-loglevel', 'quiet',
        'pipe:1'
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**7)

    start_code = b'\x00\x00\x00\x01'
    buffer = b""

    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk

        # parse NAL units in buffer
        while True:
            first = buffer.find(start_code)
            if first == -1:
                break
            second = buffer.find(start_code, first + 4)
            if second == -1:
                # incomplete NAL unit, wait for more data
                break

            nal_unit = buffer[first:second]
            buffer = buffer[second:]

            timestamp = datetime.datetime.utcnow()
            yield CompressedVideo(timestamp, frame_id, nal_unit, format)

    process.stdout.close()
    process.wait()


if __name__ == '__main__':
    url = "http://oxos-test-server:8081/camera/video/overview"
    for i, frame in enumerate(mjpeg_to_h264_stream(url)):
        print(frame)
        if i >= 10:
            break

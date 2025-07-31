import time
import cv2
import av
import io
import requests
import numpy as np
import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

# Set up Foxglove channel
video_channel = CompressedVideoChannel("/video")


def mjpeg_stream_to_h264(url):
    # Open MJPEG stream using requests
    stream = requests.get(url, stream=True)
    if stream.status_code != 200:
        raise RuntimeError(f"Failed to open MJPEG stream: {stream.status_code}")

    bytes_buffer = bytearray()

    # Set up H.264 encoder
    output = io.BytesIO()
    container = av.open(output, mode="w", format="h264")

    # We delay stream creation until we know frame size
    stream_initialized = False
    av_stream = None

    print("[INFO] Connected to MJPEG stream.")

    try:
        for chunk in stream.iter_content(chunk_size=1024):
            bytes_buffer.extend(chunk)
            start = bytes_buffer.find(b"\xff\xd8")  # SOI
            end = bytes_buffer.find(b"\xff\xd9")  # EOI

            if start != -1 and end != -1 and end > start:
                jpg_data = bytes_buffer[start : end + 2]
                bytes_buffer = bytes_buffer[end + 2 :]

                # Decode JPEG to ndarray
                frame = cv2.imdecode(
                    np.frombuffer(jpg_data, dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is None:
                    continue

                # Initialize stream dimensions only once
                if not stream_initialized:
                    h, w, _ = frame.shape
                    av_stream = container.add_stream("h264", rate=30)
                    av_stream.width = w
                    av_stream.height = h
                    av_stream.pix_fmt = "yuv420p"
                    av_stream.options = {
                        "tune": "zerolatency",
                        "preset": "medium",   # Better compression, slower encoding
                        "g": "60",            # GOP size = 60 frames (1 keyframe every 2 seconds at 30fps)
                        "bf": "0",      
                        "flags": "+low_delay"
                    }
                    stream_initialized = True

                # Convert to RGB for PyAV
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                video_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")

                # Encode to H264
                packets = av_stream.encode(video_frame)
                for packet in packets:
                    yield bytes(packet)

                # Optional throttle
                time.sleep(1 / 30)
    finally:
        # Flush remaining
        if av_stream:
            for packet in av_stream.encode():
                yield bytes(packet)
        container.close()


def stream_h264_from_webcam():
    # Open webcam
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam")

    # Setup PyAV in-memory encoding to H.264
    output = io.BytesIO()
    container = av.open(output, mode="w", format="h264")
    stream = container.add_stream("h264", rate=30)
    stream.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    stream.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stream.pix_fmt = "yuv420p"

    # Add this:
    stream.options = {
        "tune": "zerolatency",
        "preset": "ultrafast",
        "g": "1",  # GOP size = 1 => every frame is a keyframe
        "bf": "0",  # No B-frames
        "flags": "+low_delay",
    }

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Convert to RGB for PyAV
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            video_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")

            # Encode frame to H264
            packets = stream.encode(video_frame)

            for packet in packets:
                yield bytes(packet)

            # Optional: throttle (30 FPS)
            time.sleep(1 / 30)
    finally:
        # Flush and cleanup
        for packet in stream.encode():
            yield bytes(packet)

        container.close()
        cap.release()


if __name__ == "__main__":
    foxglove.set_log_level("DEBUG")
    writer = foxglove.open_mcap("mjpeg-h264-log.mcap")
    server = foxglove.start_server()

    url = "http://oxos-test-server:8081/camera/video/overview"

    for raw_h264_data in mjpeg_stream_to_h264(url):
        ts = Timestamp.from_epoch_secs(time.time())
        video_channel.log(
            CompressedVideo(timestamp=ts, data=raw_h264_data, format="h264")
        )

    # for raw_h264_data in stream_h264_from_webcam():
    #     ts = Timestamp.from_epoch_secs(time.time())
    #     video_channel.log(
    #         CompressedVideo(timestamp=ts, data=raw_h264_data, format="h264")
    #     )

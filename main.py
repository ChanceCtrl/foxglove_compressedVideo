import time
import cv2
import av
import io
import foxglove
from foxglove.channels import CompressedVideoChannel
from foxglove.schemas import CompressedVideo, Timestamp

# Set up Foxglove channel
video_channel = CompressedVideoChannel("/video")

def stream_h264_from_webcam():
    # Open webcam
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam")

    # Setup PyAV in-memory encoding to H.264
    output = io.BytesIO()
    container = av.open(output, mode='w', format='h264')
    stream = container.add_stream("h264", rate=30)
    stream.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    stream.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stream.pix_fmt = 'yuv420p'
    
    # Add this:
    stream.options = {
        "tune": "zerolatency",
        "preset": "ultrafast",
        "g": "1",  # GOP size = 1 => every frame is a keyframe
        "bf": "0",  # No B-frames
        "flags": "+low_delay"
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
    writer = foxglove.open_mcap("webcam-h264-log.mcap")
    server = foxglove.start_server()

    for raw_h264_data in stream_h264_from_webcam():
        ts = Timestamp.from_epoch_secs(time.time())
        video_channel.log(
            CompressedVideo(timestamp=ts, data=raw_h264_data, format="h264")
        )

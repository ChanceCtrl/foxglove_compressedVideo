import cv2
import av
import io

# Open webcam
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise RuntimeError("Could not open webcam")

# Set up encoder and output buffer
output = io.BytesIO()
codec = 'h264'

# Create an in-memory container to write raw H.264
output_container = av.open(output, mode='w', format='h264')
stream = output_container.add_stream(codec, rate=30)
stream.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
stream.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
stream.pix_fmt = 'yuv420p'

frame_count = 0
max_frames = 30  # You can increase this

encoded_data = bytearray()

print("[INFO] Capturing and encoding frames...")

while frame_count < max_frames:
    ret, frame = cap.read()
    if not ret:
        break

    # Convert BGR (OpenCV) to RGB (PyAV expects RGB input)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    video_frame = av.VideoFrame.from_ndarray(frame_rgb, format='rgb24')
    for packet in stream.encode(video_frame):
        encoded_data.extend(bytes(packet))
    
    frame_count += 1

# Flush encoder
for packet in stream.encode():
    encoded_data.extend(bytes(packet))

output_container.close()
cap.release()

print(f"[INFO] Captured and encoded {frame_count} frames.")

# Now decode raw H.264 data back to frames
print("[INFO] Decoding raw H.264 data...")
decoded_container = av.open(io.BytesIO(encoded_data), format='h264')

frame_number = 0
for frame in decoded_container.decode(video=0):
    img = frame.to_ndarray(format='bgr24')
    cv2.imshow("Decoded Frame", img)
    if cv2.waitKey(30) & 0xFF == ord('q'):
        break
    frame_number += 1

print(f"[INFO] Decoded {frame_number} frames.")
cv2.destroyAllWindows()

"""Tiny redistributable encoded silence, generated from 4410 zero PCM samples.

Generated with flac and FFmpeg/libmp3lame; encoders are not test/runtime dependencies.
The input is synthetic silence; these fixtures contain no copyrighted recording.
"""

import base64
import zlib

FLAC = zlib.decompress(
    base64.b64decode(
        b"eJxL80l0ZmBgUBJgEABS3AwMvFxHHD4wMAhavSqPXPZC8Nl9nYjaoO1TF5q1MDBoKADVFKWmpRal5iWnKuRkJrn5OD"
        b"orGOqZ6hkoGBkYmRoYGRoClTD8/3GSg2EqkKG49/+PSg5GRssNQM5XNgBswB7O"
    )
)

MP3 = zlib.decompress(
    base64.b64decode(
        b"eJz7/zvgCAPzAQbGJQwMDAoMDCYNDAwsPo6+riZ6BqGkAHL00AD8/x10JLYZzT9kmTSIPLRw1EODGAw7DwEARCRUHQ"
        b"=="
    )
)

#!/usr/bin/env python

import traceback
import cv2
import gi
import numpy as np
from multiprocessing import Lock, Array
import ctypes

gi.require_version('Gst', '1.0')
from gi.repository import Gst


class GStreamerVideoSink():
    """BlueRov video capture class constructor
    Attributes:
        port (int): Video UDP port
        video_codec (string): Source h264 parser
        video_decode (string): Transform YUV (12bits) to BGR (24bits)
        video_pipe (object): GStreamer top-level pipeline
        video_sink (object): Gstreamer sink element
        video_sink_conf (string): Sink configuration
        video_source (string): Udp source ip and port
    """

    def __init__(self, params):
        """Summary
        Args:
            port (int, optional): UDP port
        """
        Gst.init(None)

        multicast_ip = params["ai_video_streamer"]["multicast_ip"]
        port = str(params["ai_video_streamer"]["port"])
        self._width = params['ai_video_streamer']['capture_width']
        self._height = params['ai_video_streamer']['capture_height']

        self._frame = None
        self._mutex = Lock()

        self.video_source = \
            f'udpsrc multicast-group={multicast_ip} ' \
            f'auto-multicast=true port={port}'
        self.video_codec = \
            '! application/x-rtp,encoding-name=JPEG,payload=26 ' \
            '! rtpjpegdepay ! jpegdec'
        self.video_decode = \
            '! decodebin ! videoconvert ' \
            '! video/x-raw,format=(string)BGR ! videoconvert'
        self.video_sink_conf = \
            '! appsink emit-signals=true sync=false drop=true'

        self.video_pipe = None
        self.video_sink = None

        self._image_size = (self._width, self._height, 3)
        arr_size = self._width * self._height * 3
        self._shared_arr = Array(ctypes.c_uint8, arr_size)
        # self.video_capture_image = np.frombuffer(
        #     self._shared_arr.get_obj(),
        #     dtype=np.uint8)
        # self.video_capture_image = \
        #     np.reshape(self.video_capture_image, self._image_size)

        self._run()

    def _start_gst(self, config=None):
        """
        Start gstreamer pipeline and sink
        """
        command = ' '.join(config)
        self.video_pipe = Gst.parse_launch(command)
        self.video_pipe.set_state(Gst.State.PLAYING)

        # On every restart the appsink's name's suffix number increments
        # by one: appsink0, appsink1, appsink2, ...
        for i in range(100):
            self.video_sink = self.video_pipe.get_by_name(f'appsink{i}')
            if self.video_sink is not None:
                # print(f"Using appsink{i}")
                break

        if self.video_sink is None:
            raise Exception("video_sink is NONE")

    @staticmethod
    def _gst_to_opencv(sample):
        """
        Transform byte array into np array
        Args:
            sample (TYPE): Description
        Returns:
            TYPE: Description
        """
        buf = sample.get_buffer()
        caps = sample.get_caps()
        array = np.ndarray(
            (
                caps.get_structure(0).get_value('height'),
                caps.get_structure(0).get_value('width'),
                3
            ),
            buffer=buf.extract_dup(0, buf.get_size()), dtype=np.uint8)
        return array

    def _crop_center(self, image, cropped_width, cropped_height):
        height, width, _ = image.shape
        startx = int((width - cropped_width) / 2)
        starty = int((height - cropped_height) / 2)

        stopx = startx + cropped_width
        stopy = starty + cropped_height
        image = image[starty:stopy, startx:stopx, :]
        return image

    def _resize(self, image, width, height):
        return cv2.resize(image, (width, height))

    def frame(self):
        """
        Get Frame
        Returns : numpy.array(int8)
            Image as a numpy array
        """
        with self._mutex:
            return np.copy(self._frame)

    def frame_available(self):
        """
        Check if frame is available
        Returns : boolean
            true if frame is available otherwise false
        """
        with self._mutex:
            available = type(self._frame) != type(None)
        return available

    def stop(self):
        if self.video_pipe is not None:
            self.video_pipe.set_state(Gst.State.NULL)
            self.video_pipe = None
            self.video_sink = None
            self._mutex = None

    def _run(self):
        """
        Get frame to update _frame
        """
        try:
            self._image_size = (self._width, self._height, 3)
            self._frame = np.frombuffer(
                self._shared_arr.get_obj(),
                dtype=np.uint8)
            self._frame = \
                np.reshape(self._frame, self._image_size)

            self._start_gst(
                [
                    self.video_source,
                    self.video_codec,
                    self.video_decode,
                    self.video_sink_conf
                ])
            self.video_sink.connect('new-sample', self._callback)
        except Exception as error:
            print(f'Got unexpected exception in "main" Message: {error}')

    def _callback(self, sink):
        sample = sink.emit('pull-sample')
        new_frame = self._gst_to_opencv(sample)
        with self._mutex:
            try:
                self._frame[:] = new_frame
            except ValueError as error:
                traceback.print_exc()
                print('\n=====\n'
                      'Got unexpected exception in "GStreamerVideoSink"'
                      f'Message: {error}\n=====\n')
                raise Exception(
                    "\n=====\nCan't get image. Maybe the incoming image "
                    f"size is different than {self._width}x{self._height} "
                    "which was expected\n=====\n")

        return Gst.FlowReturn.OK


# Main for testing video connection. Run with below command executed in
# project's root folder. Make sure 'params-prod.yaml' file has
# 'ai_video_streamer' group and correct parameters set.
# python -m reallife_camera_source.gstreamer_video_sink
if __name__ == '__main__':
    from utils.utils import parse_options
    # Create the video object
    # Add port= if is necessary to use a different one
    params = parse_options("params-prod.yaml")
    video = GStreamerVideoSink(params)

    while True:
        # Wait for the next frame
        if not video.frame_available():
            continue

        frame = video.frame()
        cv2.imshow('frame', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

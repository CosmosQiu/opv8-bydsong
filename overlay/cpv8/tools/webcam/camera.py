import av  
import cv2  
import os  
import threading  
import concurrent.futures  
import numpy as np  
from openpilot.tools.webcam import lens  

# OpenCV 默认按核数开线程池做 MJPEG 解码；PC 版 op 还要同时跑 modeld/controlsd，
# 线程池抢满 8 核会把整机拖到 load 20+，反而让 modeld 掉帧。限制一下。
cv2.setNumThreads(int(os.getenv("CV2_THREADS", "4")))
try:  
    import pyopencl as cl  
    import pyopencl.array as cl_array  
    OPENCL_AVAILABLE = True  
except ImportError:  
    OPENCL_AVAILABLE = False  
    print("PyOpenCL not available, falling back to CPU processing")  
  
class Camera:  
    def __init__(self, cam_type_state, stream_type, camera_id):  
        try:  
            camera_id = int(camera_id)  
        except ValueError: # allow strings, ex: /dev/video0  
            pass  
        self.cam_type_state = cam_type_state  
        self.stream_type = stream_type  
        self.cur_frame_id = 0  
  
        self.container = av.open(camera_id)  
        assert self.container.streams.video, f"Can't open video stream for camera {camera_id}"  
        self.video_stream = self.container.streams.video[0]  
        self.W = self.video_stream.codec_context.width  
        self.H = self.video_stream.codec_context.height  
  
    @classmethod  
    def bgr2nv12(self, bgr):  
        frame = av.VideoFrame.from_ndarray(bgr, format='bgr24')  
        return frame.reformat(format='nv12').to_ndarray()  
  
    def read_frames(self):  
        for frame in self.container.decode(self.video_stream):  
            img = frame.to_rgb().to_ndarray()[:,:, ::-1] # convert to bgr24  
            yuv = Camera.bgr2nv12(img)  
            yield yuv.data.tobytes()  
        self.container.close()  
  
class CameraMJPG:  
    def __init__(self, cam_type_state, stream_type, camera_id, width=None, height=None, fps=None, lens_file=None):  
        try:  
            camera_id = int(camera_id)  
        except ValueError:  
            pass  
  
        # 分辨率/帧率可按摄像头单独指定（PC 版多摄挂同一条 USB 总线时必需）
        self.req_width = int(width) if width else 1920
        self.req_height = int(height) if height else 1080
        self.req_fps = float(fps) if fps else 20

        self.cap = cv2.VideoCapture(camera_id)  
        if not self.cap.isOpened():  
            raise IOError(f"无法打开摄像头设备 {camera_id}")  
  
        # 优先尝试设置 MJPG 格式（高分辨率 + 高帧率）  
        self._configure_camera_format("MJPG")  
        actual_format = self._get_current_format()  
        print("数据格式: ", actual_format)  
  
        # 获取实际设置的FPS并打印  
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)  
        print(f"摄像头初始化后的FPS设置: {self.fps}")  
  
        # 获取分辨率  
        self.W = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))  
        self.H = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))  
        # 可选：鱼眼去畸变（只广角用）。必须在 BGR 阶段做，转成 NV12 后就没法 remap 了。
        # openpilot 的广角通路是纯针孔模型（get_warp_matrix 只有 3x3 单应），
        # 不做这一步的话喂给模型的几何是错的。
        self.undistort = lens.build(self.W, self.H, lens_file or None) if lens_file is not None else None
        if self.undistort is not None:
            print(f"去畸变已启用: {self.W}x{self.H} lens_file={lens_file}")
        self.cur_frame_id = 0  
        self.cam_type_state = cam_type_state  
        self.stream_type = stream_type  
        self.current_format = actual_format  # 记录当前格式用于后续处理  
  
        # 处理模式控制：single_thread, multi_thread, opencl  
        self.processing_mode = os.getenv("MJPG_PROCESSING_MODE", "single_thread")  
        self.num_threads = int(os.getenv("MJPG_THREADS", "4"))  
          
        print(f"MJPG处理模式: {self.processing_mode}")  
        if self.processing_mode == "multi_thread":  
            print(f"多线程数量: {self.num_threads}")  
          
        # 根据模式初始化相应资源  
        self._init_processing_resources()  
  
    def _configure_camera_format(self, target_fourcc):  
        """尝试设置摄像头的FourCC格式"""  
        fourcc = cv2.VideoWriter_fourcc(*target_fourcc)  
        self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)  
        self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)  
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req_width)  # 优先选择最高分辨率  
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req_height)  
        self.cap.set(cv2.CAP_PROP_FPS, self.req_fps)  
  
    def _get_current_format(self):  
        """获取当前实际格式"""  
        fourcc_code = int(self.cap.get(cv2.CAP_PROP_FOURCC))  
        return ''.join([chr((fourcc_code >> 8 * i) & 0xFF) for i in range(4)])  
  
    def _init_processing_resources(self):  
        """根据处理模式初始化资源"""  
        self.thread_pool = None  
        self.opencl_available = False  
          
        if self.processing_mode == "multi_thread":  
            self.thread_pool = concurrent.futures.ThreadPoolExecutor(  
                max_workers=self.num_threads  
            )  
            print(f"多线程处理器初始化完成，线程数: {self.num_threads}")  
        elif self.processing_mode == "opencl":  
            self._init_opencl()  
  
    def _init_opencl(self):  
        """初始化 OpenCL 资源"""  
        if not OPENCL_AVAILABLE:  
            print("PyOpenCL 不可用，回退到单线程 CPU 处理")  
            self.processing_mode = "single_thread"  
            return  
              
        try:  
            self.ctx = cl.create_some_context()  
            self.queue = cl.CommandQueue(self.ctx)  
            self._setup_opencl_kernels()  
            self.opencl_available = True  
            print("OpenCL 初始化成功")  
        except Exception as e:  
            print(f"OpenCL 初始化失败，回退到单线程 CPU 处理: {e}")  
            self.processing_mode = "single_thread"  
            self.opencl_available = False  
  
    def _setup_opencl_kernels(self):  
        """设置 OpenCL 内核"""  
        # 基于现有的 rgb_to_nv12.cl 内核，修改为 BGR 到 NV12  
        kernel_source = f"""  
        #define RGB_TO_Y(r, g, b) ((((mul24(b, 13) + mul24(g, 65) + mul24(r, 33)) + 64) >> 7) + 16)  
        #define RGB_TO_U(r, g, b) ((mul24(b, 56) - mul24(g, 37) - mul24(r, 19) + 0x8080) >> 8)  
        #define RGB_TO_V(r, g, b) ((mul24(r, 56) - mul24(g, 47) - mul24(b, 9) + 0x8080) >> 8)  
        #define AVERAGE(x, y, z, w) ((convert_ushort(x) + convert_ushort(y) + convert_ushort(z) + convert_ushort(w) + 1) >> 1)  
          
        __kernel void bgr_to_nv12(__global uchar const * const bgr,  
                                  __global uchar * out_yuv)  
        {{  
            const int dx = get_global_id(0);  
            const int dy = get_global_id(1);  
            const int col = dx * 2;  
            const int row = dy * 2;  
              
            if (col >= {self.W} || row >= {self.H}) return;  
              
            const int bgr_stride = {self.W} * 3;  
            const int y_size = {self.W} * {self.H};  
              
            // 处理 2x2 像素块  
            for (int r = 0; r < 2 && (row + r) < {self.H}; r++) {{  
                for (int c = 0; c < 2 && (col + c) < {self.W}; c++) {{  
                    int bgr_idx = (row + r) * bgr_stride + (col + c) * 3;  
                    int y_idx = (row + r) * {self.W} + (col + c);  
                      
                    uchar b = bgr[bgr_idx];  
                    uchar g = bgr[bgr_idx + 1];  
                    uchar r_val = bgr[bgr_idx + 2];  
                      
                    out_yuv[y_idx] = RGB_TO_Y(r_val, g, b);  
                }}  
            }}  
              
            // UV 分量 (2x2 块的平均值)  
            if (row % 2 == 0 && col % 2 == 0) {{  
                int uv_row = row / 2;  
                int uv_col = col / 2;  
                int uv_idx = y_size + uv_row * {self.W} + uv_col * 2;  
                  
                // 获取 2x2 块的像素值  
                int bgr_idx_00 = row * bgr_stride + col * 3;  
                int bgr_idx_01 = row * bgr_stride + (col + 1) * 3;  
                int bgr_idx_10 = (row + 1) * bgr_stride + col * 3;  
                int bgr_idx_11 = (row + 1) * bgr_stride + (col + 1) * 3;  
                  
                if ((col + 1) < {self.W} && (row + 1) < {self.H}) {{  
                    uchar b_avg = (bgr[bgr_idx_00] + bgr[bgr_idx_01] + bgr[bgr_idx_10] + bgr[bgr_idx_11]) / 4;  
                    uchar g_avg = (bgr[bgr_idx_00 + 1] + bgr[bgr_idx_01 + 1] + bgr[bgr_idx_10 + 1] + bgr[bgr_idx_11 + 1]) / 4;  
                    uchar r_avg = (bgr[bgr_idx_00 + 2] + bgr[bgr_idx_01 + 2] + bgr[bgr_idx_10 + 2] + bgr[bgr_idx_11 + 2]) / 4;  
                      
                    out_yuv[uv_idx] = RGB_TO_U(r_avg, g_avg, b_avg);  
                    out_yuv[uv_idx + 1] = RGB_TO_V(r_avg, g_avg, b_avg);  
                }}  
            }}  
        }}  
        """  
          
        self.program = cl.Program(self.ctx, kernel_source).build()  
        self.bgr_to_nv12_kernel = self.program.bgr_to_nv12  
  
    @staticmethod
    def _bgr_to_nv12(bgr_frame):
        """BGR -> NV12（visionipc 要求的格式）。

        用 cv2 的 SIMD 转换 + numpy 交织，比 av.VideoFrame.reformat 快约 6 倍
        （1080p 实测 49ms -> 8ms）。两路摄像头跑在同一个进程里时这是关键路径，
        用 av 版本时 1080p 只能跑到 10fps。输出与 av 路径逐像素等价
        （实测整图平均|差| 0.05）。
        """
        h, w = bgr_frame.shape[:2]
        if h % 2 or w % 2:  # 奇数尺寸走原来的通用路径
            frame = av.VideoFrame.from_ndarray(bgr_frame, format='bgr24')
            return frame.reformat(format='nv12').to_ndarray().data.tobytes()
        yuv = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)  # Y + U + V 平面
        nv12 = np.empty((h * 3 // 2, w), dtype=np.uint8)
        nv12[:h] = yuv[:h]
        uv = yuv[h:].reshape(2, h // 2, w // 2)
        dst = nv12[h:].reshape(h // 2, w // 2, 2)
        dst[:, :, 0] = uv[0]
        dst[:, :, 1] = uv[1]
        return nv12.tobytes()
    def _bgr_to_nv12_single(self, frame):  
        """单线程 BGR 到 NV12 转换"""  
        return self._bgr_to_nv12(frame)  
  
    def _process_frame_chunk(self, frame):  
        """多线程处理帧块"""  
        return self._bgr_to_nv12(frame)  
  
    def _bgr_to_nv12_multi(self, frame):  
        """多线程 BGR 到 NV12 转换"""  
        if self.thread_pool is None:  
            return self._bgr_to_nv12_single(frame)  
          
        # 提交到线程池处理  
        future = self.thread_pool.submit(self._process_frame_chunk, frame)  
        return future.result()  
  
    def _bgr_to_nv12_opencl(self, frame):  
        """OpenCL 加速 BGR 到 NV12 转换"""  
        if not self.opencl_available:  
            return self._bgr_to_nv12_single(frame)  
          
        try:  
            # 创建输入和输出缓冲区  
            frame_flat = frame.flatten().astype(np.uint8)  
            nv12_size = self.W * self.H * 3 // 2  
              
            frame_cl = cl.Buffer(self.ctx, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=frame_flat)  
            result_cl = cl.Buffer(self.ctx, cl.mem_flags.WRITE_ONLY, nv12_size)  
              
            # 执行内核  
            global_size = (self.W // 2, self.H // 2)  
            self.bgr_to_nv12_kernel(self.queue, global_size, None, frame_cl, result_cl)  
              
            # 读取结果  
            result = np.empty(nv12_size, dtype=np.uint8)  
            cl.enqueue_copy(self.queue, result, result_cl).wait()  
              
            return result.tobytes()  
        except Exception as e:  
            print(f"OpenCL 处理失败，回退到 CPU: {e}")  
            return self._bgr_to_nv12_single(frame)  
  
    def read_frames(self):  
        """根据处理模式读取帧并转换为 NV12"""  
        while True:  
            ret, frame = self.cap.read()  
            if not ret:  
                break  
  
            if self.current_format == "MJPG":  
                if frame.shape != (self.H, self.W, 3):  
                    raise ValueError("MJPG 解码后帧形状异常，请检查摄像头设置")  
  
            if self.undistort is not None:  
                frame = self.undistort.apply(frame)  
              
            # 根据处理模式选择不同的转换方法  
            if self.processing_mode == "single_thread":  
                yield self._bgr_to_nv12_single(frame)  
            elif self.processing_mode == "multi_thread":  
                yield self._bgr_to_nv12_multi(frame)  
            elif self.processing_mode == "opencl":  
                yield self._bgr_to_nv12_opencl(frame)  
            else:  
                # 默认回退到单线程  
                yield self._bgr_to_nv12_single(frame)  
          
        self.cap.release()  
  
    def __del__(self):  
        """清理资源"""  
        if hasattr(self, 'cap') and self.cap.isOpened():  
            self.cap.release()

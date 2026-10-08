"""ctypes wrapper for Allwinner NPU VIP Lite driver (libNBGlinker.so).

Exposes the vip_* C API directly to Python with proper type signatures.
"""

import ctypes
import os
from ctypes import (
    POINTER,
    Structure,
    Union,
    byref,
    c_char_p,
    c_float,
    c_int,
    c_int32,
    c_size_t,
    c_uint32,
    c_void_p,
)

# ── Constants ────────────────────────────────────────────────────────────────

VIP_SUCCESS = 0
VIP_ERROR_CANCELED = -15

# vip_buffer_format_e
VIP_BUFFER_FORMAT_FP32 = 0
VIP_BUFFER_FORMAT_FP16 = 1
VIP_BUFFER_FORMAT_UINT8 = 2
VIP_BUFFER_FORMAT_INT8 = 3
VIP_BUFFER_FORMAT_UINT16 = 4
VIP_BUFFER_FORMAT_INT16 = 5
VIP_BUFFER_FORMAT_INT32 = 8

# vip_buffer_quantize_format_e
VIP_BUFFER_QUANTIZE_NONE = 0
VIP_BUFFER_QUANTIZE_DYNAMIC_FIXED_POINT = 1
VIP_BUFFER_QUANTIZE_TF_ASYMM = 2

# vip_buffer_memory_type_e
VIP_BUFFER_MEMORY_TYPE_DEFAULT = 0
VIP_BUFFER_MEMORY_TYPE_HOST = 1
VIP_BUFFER_MEMORY_TYPE_DMA_BUF = 3

# vip_create_network_type_e
VIP_CREATE_NETWORK_FROM_NONE = 0
VIP_CREATE_NETWORK_FROM_FILE = 1
VIP_CREATE_NETWORK_FROM_MEMORY = 2

# vip_network_property_e
VIP_NETWORK_PROP_LAYER_COUNT = 0
VIP_NETWORK_PROP_INPUT_COUNT = 1
VIP_NETWORK_PROP_OUTPUT_COUNT = 2
VIP_NETWORK_PROP_MEMORY_POOL_SIZE = 6
VIP_NETWORK_PROP_SET_MEMORY_POOL = 65
VIP_NETWORK_PROP_SET_PRIORITY = 67

# vip_buffer_property_e
VIP_BUFFER_PROP_QUANT_FORMAT = 0
VIP_BUFFER_PROP_NUM_OF_DIMENSION = 1
VIP_BUFFER_PROP_SIZES_OF_DIMENSION = 2
VIP_BUFFER_PROP_DATA_FORMAT = 3
VIP_BUFFER_PROP_FIXED_POINT_POS = 4
VIP_BUFFER_PROP_TF_SCALE = 5
VIP_BUFFER_PROP_TF_ZERO_POINT = 6
VIP_BUFFER_PROP_NAME = 7

# vip_buffer_operation_type_e
VIP_BUFFER_OPER_TYPE_NONE = 0
VIP_BUFFER_OPER_TYPE_FLUSH = 1
VIP_BUFFER_OPER_TYPE_INVALIDATE = 2

# ── Opaque types ─────────────────────────────────────────────────────────────

vip_network = c_void_p
vip_buffer = c_void_p

# ── Union for quantization data ──────────────────────────────────────────────

class DFPData(Structure):
    _fields_ = [("fixed_point_pos", c_int32)]


class AffineData(Structure):
    _fields_ = [
        ("scale", c_float),
        ("zeroPoint", c_int32),
    ]


class QuantData(Union):
    _fields_ = [
        ("dfp", DFPData),
        ("affine", AffineData),
    ]


# ── vip_buffer_create_params_t ───────────────────────────────────────────────

class VipBufferCreateParams(Structure):
    _fields_ = [
        ("num_of_dims", c_uint32),
        ("sizes", c_uint32 * 6),
        ("data_format", c_int),
        ("quant_format", c_int),
        ("quant_data", QuantData),
        ("memory_type", c_uint32),
    ]


# ── Load NPU shared libraries ────────────────────────────────────────────────

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBS_DIR = os.path.join(_PKG_DIR, "libs")


def _detect_platform():
    """Find the first subdirectory under libs/ that contains libNBGlinker.so."""
    try:
        for name in sorted(os.listdir(_LIBS_DIR)):
            p = os.path.join(_LIBS_DIR, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "libNBGlinker.so")):
                return name
    except OSError:
        pass
    return "a733"


_PLATFORM = _detect_platform()
_SO_DIR = os.path.join(_LIBS_DIR, _PLATFORM)

_loaded = False


def _load_libs():
    """Load NPU shared libraries (libVIPhal.so then libNBGlinker.so)."""
    global _loaded, _lib
    if _loaded:
        return

    viphal = os.path.join(_SO_DIR, "libVIPhal.so")
    nbg = os.path.join(_SO_DIR, "libNBGlinker.so")

    # 1) HAL layer
    if os.path.isfile(viphal):
        ctypes.CDLL(viphal, mode=ctypes.RTLD_GLOBAL)
    else:
        ctypes.CDLL("libVIPhal.so", mode=ctypes.RTLD_GLOBAL)

    # 2) VIP API layer
    if os.path.isfile(nbg):
        _lib = ctypes.CDLL(nbg, mode=ctypes.RTLD_GLOBAL)
    else:
        _lib = ctypes.CDLL("libNBGlinker.so", mode=ctypes.RTLD_GLOBAL)

    _setup_signatures()
    _loaded = True


_lib = None


def _setup_signatures():
    """Define ctypes function signatures matching vip_lite.h."""

    # vip_status_e vip_init(void)
    _lib.vip_init.restype = c_int
    _lib.vip_init.argtypes = []

    # vip_status_e vip_destroy(void)
    _lib.vip_destroy.restype = c_int
    _lib.vip_destroy.argtypes = []

    # vip_uint32_t vip_get_version(void)
    _lib.vip_get_version.restype = c_uint32
    _lib.vip_get_version.argtypes = []

    # vip_status_e vip_create_network(const void *data, vip_uint32_t size_of_data,
    #                                  vip_create_network_type_e type, vip_network *network)
    _lib.vip_create_network.restype = c_int
    _lib.vip_create_network.argtypes = [c_char_p, c_uint32, c_int, POINTER(vip_network)]

    # vip_status_e vip_destroy_network(vip_network network)
    _lib.vip_destroy_network.restype = c_int
    _lib.vip_destroy_network.argtypes = [vip_network]

    # vip_status_e vip_prepare_network(vip_network network)
    _lib.vip_prepare_network.restype = c_int
    _lib.vip_prepare_network.argtypes = [vip_network]

    # vip_status_e vip_finish_network(vip_network network)
    _lib.vip_finish_network.restype = c_int
    _lib.vip_finish_network.argtypes = [vip_network]

    # vip_status_e vip_query_network(vip_network network, vip_enum property, void *value)
    _lib.vip_query_network.restype = c_int
    _lib.vip_query_network.argtypes = [vip_network, c_int, c_void_p]

    # vip_status_e vip_query_input(vip_network network, vip_uint32_t index,
    #                               vip_enum property, void *value)
    _lib.vip_query_input.restype = c_int
    _lib.vip_query_input.argtypes = [vip_network, c_uint32, c_int, c_void_p]

    # vip_status_e vip_query_output(vip_network network, vip_uint32_t index,
    #                                vip_enum property, void *value)
    _lib.vip_query_output.restype = c_int
    _lib.vip_query_output.argtypes = [vip_network, c_uint32, c_int, c_void_p]

    # vip_status_e vip_set_input(vip_network network, vip_uint32_t index, vip_buffer input)
    _lib.vip_set_input.restype = c_int
    _lib.vip_set_input.argtypes = [vip_network, c_uint32, vip_buffer]

    # vip_status_e vip_set_output(vip_network network, vip_uint32_t index, vip_buffer output)
    _lib.vip_set_output.restype = c_int
    _lib.vip_set_output.argtypes = [vip_network, c_uint32, vip_buffer]

    # vip_status_e vip_create_buffer(vip_buffer_create_params_t *create_param,
    #                                 vip_uint32_t size_of_param, vip_buffer *buffer)
    _lib.vip_create_buffer.restype = c_int
    _lib.vip_create_buffer.argtypes = [
        POINTER(VipBufferCreateParams), c_uint32, POINTER(vip_buffer)
    ]

    # vip_status_e vip_destroy_buffer(vip_buffer buffer)
    _lib.vip_destroy_buffer.restype = c_int
    _lib.vip_destroy_buffer.argtypes = [vip_buffer]

    # void *vip_map_buffer(vip_buffer buffer)
    _lib.vip_map_buffer.restype = c_void_p
    _lib.vip_map_buffer.argtypes = [vip_buffer]

    # vip_status_e vip_unmap_buffer(vip_buffer buffer)
    _lib.vip_unmap_buffer.restype = c_int
    _lib.vip_unmap_buffer.argtypes = [vip_buffer]

    # vip_status_e vip_flush_buffer(vip_buffer buffer, vip_buffer_operation_type_e type)
    _lib.vip_flush_buffer.restype = c_int
    _lib.vip_flush_buffer.argtypes = [vip_buffer, c_int]

    # vip_uint32_t vip_get_buffer_size(vip_buffer buffer)
    _lib.vip_get_buffer_size.restype = c_uint32
    _lib.vip_get_buffer_size.argtypes = [vip_buffer]

    # vip_status_e vip_run_network(vip_network network)
    _lib.vip_run_network.restype = c_int
    _lib.vip_run_network.argtypes = [vip_network]

    # vip_status_e vip_set_network(vip_network network, vip_enum property, void *value)
    _lib.vip_set_network.restype = c_int
    _lib.vip_set_network.argtypes = [vip_network, c_int, c_void_p]


def _check(ret, msg="VIP error"):
    """Raise if a VIP call did not return VIP_SUCCESS."""
    if ret != VIP_SUCCESS:
        raise RuntimeError(f"{msg}: status={ret}")


# ── High-level NPU context ───────────────────────────────────────────────────

class NpuContext:
    """Manages NPU driver init/destroy and network lifecycle."""

    def __init__(self):
        _load_libs()
        self._closed = False
        self.network = None  # vip_network handle
        self._input_buffers = []  # list of vip_buffer
        self._output_buffers = []  # list of vip_buffer
        self._output_counts = []  # number of elements per output
        self._output_formats = []  # data format per output
        self._output_quant = []  # quant format per output
        self._output_scales = []  # dequant scale per output
        self._output_zero_points = []  # dequant zero point per output
        self._output_fp_pos = []  # fixed point position per output

    # ── init / destroy ───────────────────────────────────────────

    def init(self):
        """Initialize NPU driver. Must be called once before anything else."""
        _check(_lib.vip_init(), "vip_init")

    def destroy(self):
        """Shut down NPU driver. No VIP calls afterward."""
        _lib.vip_destroy()
        self._closed = True

    # ── network lifecycle ────────────────────────────────────────

    def load_model(self, model_path: str):
        """Create a network from a .nb model file.

        Reads the model, creates VIP network object + I/O buffers,
        and prepares the network for inference.
        """
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"model not found: {model_path}")

        path_bytes = model_path.encode("utf-8")
        network = vip_network()
        _check(
            _lib.vip_create_network(
                c_char_p(path_bytes), 0, VIP_CREATE_NETWORK_FROM_FILE, byref(network)
            ),
            "vip_create_network",
        )
        self.network = network

        self._create_io_buffers()
        self._prepare()

    def _create_io_buffers(self):
        """Create input and output buffers for the current network.

        Mirrors NetworkItem::network_create_io_buffer() from npulib.cpp.
        """
        # --- inputs ---
        input_count = c_uint32()
        _check(
            _lib.vip_query_network(
                self.network, VIP_NETWORK_PROP_INPUT_COUNT, byref(input_count)
            ),
            "query input count",
        )
        n_inputs = input_count.value

        for i in range(n_inputs):
            param, size = self._query_buffer_props(self.network, is_input=True, idx=i)

            buf = vip_buffer()
            _check(
                _lib.vip_create_buffer(byref(param), ctypes.sizeof(param), byref(buf)),
                f"create input buffer {i}",
            )
            self._input_buffers.append(buf)

        # --- outputs ---
        output_count = c_uint32()
        _check(
            _lib.vip_query_network(
                self.network, VIP_NETWORK_PROP_OUTPUT_COUNT, byref(output_count)
            ),
            "query output count",
        )
        n_outputs = output_count.value

        for i in range(n_outputs):
            param, elem_count = self._query_buffer_props(self.network, is_input=False, idx=i)

            buf = vip_buffer()
            _check(
                _lib.vip_create_buffer(byref(param), ctypes.sizeof(param), byref(buf)),
                f"create output buffer {i}",
            )
            self._output_buffers.append(buf)
            self._output_counts.append(elem_count)

            # store format info for dequantization
            self._output_formats.append(param.data_format)
            self._output_quant.append(param.quant_format)
            self._output_scales.append(param.quant_data.affine.scale)
            self._output_zero_points.append(param.quant_data.affine.zeroPoint)
            self._output_fp_pos.append(param.quant_data.dfp.fixed_point_pos)

    @staticmethod
    def _query_buffer_props(network, is_input: bool, idx: int):
        """Query properties for an input or output at given index.

        Returns (VipBufferCreateParams, element_count).
        """
        fn = _lib.vip_query_input if is_input else _lib.vip_query_output
        label = "input" if is_input else "output"

        # Use local ctypes variables for query (byref requires ctypes instances)
        data_format = c_int()
        num_dims = c_uint32()
        quant_format = c_int()
        fixed_point_pos = c_int32()
        scale = c_float()
        zero_point = c_int32()

        _check(fn(network, idx, VIP_BUFFER_PROP_DATA_FORMAT, byref(data_format)),
               f"query {label} fmt")
        _check(fn(network, idx, VIP_BUFFER_PROP_NUM_OF_DIMENSION, byref(num_dims)),
               f"query {label} dims")

        param = VipBufferCreateParams()
        ctypes.memset(byref(param), 0, ctypes.sizeof(param))
        param.memory_type = VIP_BUFFER_MEMORY_TYPE_DEFAULT
        param.data_format = data_format.value
        param.num_of_dims = num_dims.value

        _check(fn(network, idx, VIP_BUFFER_PROP_SIZES_OF_DIMENSION, param.sizes),
               f"query {label} sizes")
        _check(fn(network, idx, VIP_BUFFER_PROP_QUANT_FORMAT, byref(quant_format)),
               f"query {label} quant")
        param.quant_format = quant_format.value

        if param.quant_format == VIP_BUFFER_QUANTIZE_DYNAMIC_FIXED_POINT:
            _check(fn(network, idx, VIP_BUFFER_PROP_FIXED_POINT_POS, byref(fixed_point_pos)),
                   f"query {label} fp_pos")
            param.quant_data.dfp.fixed_point_pos = fixed_point_pos.value
            param.quant_data.affine.scale = 1.0
            param.quant_data.affine.zeroPoint = 0
        elif param.quant_format == VIP_BUFFER_QUANTIZE_TF_ASYMM:
            _check(fn(network, idx, VIP_BUFFER_PROP_TF_SCALE, byref(scale)),
                   f"query {label} scale")
            _check(fn(network, idx, VIP_BUFFER_PROP_TF_ZERO_POINT, byref(zero_point)),
                   f"query {label} zero_point")
            param.quant_data.affine.scale = scale.value
            param.quant_data.affine.zeroPoint = zero_point.value
            param.quant_data.dfp.fixed_point_pos = 0

        element_count = 1
        for k in range(param.num_of_dims):
            element_count *= param.sizes[k]

        return param, element_count

    def _prepare(self):
        """Prepare the network for inference (heavy one-time operation)."""
        _check(_lib.vip_prepare_network(self.network), "vip_prepare_network")

    # ── IO setup ─────────────────────────────────────────────────

    def set_inputs_outputs(self):
        """Attach all input/output buffers to the network.

        Must be called before each vip_run_network.
        """
        for i, buf in enumerate(self._input_buffers):
            _check(_lib.vip_set_input(self.network, i, buf), f"set_input {i}")
        for i, buf in enumerate(self._output_buffers):
            _check(_lib.vip_set_output(self.network, i, buf), f"set_output {i}")

    # ── input data upload ────────────────────────────────────────

    def upload_input(self, idx: int, data: bytes):
        """Copy preprocessed data into an input buffer."""
        buf = self._input_buffers[idx]
        ptr = _lib.vip_map_buffer(buf)
        buf_size = _lib.vip_get_buffer_size(buf)
        copy_len = min(len(data), buf_size)
        ctypes.memmove(ptr, data, copy_len)
        _lib.vip_unmap_buffer(buf)

    def get_input_ptr(self, idx: int):
        """Map input buffer, return (pointer, size_in_bytes).

        Caller writes data, then must call flush_input(idx).
        """
        buf = self._input_buffers[idx]
        ptr = _lib.vip_map_buffer(buf)
        size = _lib.vip_get_buffer_size(buf)
        return ptr, size

    def flush_input(self, idx: int):
        """Unmap input buffer after writing (unmap also releases the mapping)."""
        _lib.vip_unmap_buffer(self._input_buffers[idx])

    def upload_input_direct(self, idx: int, data: bytes):
        """Map, write, and flush an input buffer in one call."""
        ptr, size = self.get_input_ptr(idx)
        copy_len = min(len(data), size)
        ctypes.memmove(ptr, data, copy_len)
        self.flush_input(idx)

    def upload_from_numpy(self, idx: int, arr):
        """Upload from a contiguous numpy array without .tobytes() copy."""
        import numpy as np
        ptr, size = self.get_input_ptr(idx)
        copy_len = min(arr.nbytes, size)
        ctypes.memmove(ptr, arr.ctypes.data_as(ctypes.c_void_p), copy_len)
        self.flush_input(idx)

    # ── run ───────────────────────────────────────────────────────

    def run(self):
        """Flush inputs, run the network, invalidate outputs."""
        for buf in self._input_buffers:
            _lib.vip_flush_buffer(buf, VIP_BUFFER_OPER_TYPE_FLUSH)

        _check(_lib.vip_run_network(self.network), "vip_run_network")

        for buf in self._output_buffers:
            _lib.vip_flush_buffer(buf, VIP_BUFFER_OPER_TYPE_INVALIDATE)

    # ── output retrieval ─────────────────────────────────────────

    def get_output_views(self):
        """Map all output buffers, return numpy float32 views (zero-copy).

        Returns list of np.ndarray views. Caller must call
        release_output_views() after postprocessing to unmap.
        """
        import numpy as np
        views = []
        for i, buf in enumerate(self._output_buffers):
            raw_ptr = _lib.vip_map_buffer(buf)
            count = self._output_counts[i]
            ptr = ctypes.cast(raw_ptr, POINTER(c_float))
            views.append(np.ctypeslib.as_array(ptr, shape=(count,)))
        return views

    def release_output_views(self):
        """Unmap all output buffers (call after get_output_views)."""
        for buf in self._output_buffers:
            _lib.vip_unmap_buffer(buf)

    def get_output_fp_nocopy(self, idx: int):
        """Map output buffer, return (float_ptr, element_count).

        Returns a ctypes pointer to float32 data. The mapping persists
        until release_output is called.
        """
        buf = self._output_buffers[idx]
        ptr = ctypes.cast(_lib.vip_map_buffer(buf), POINTER(c_float))
        return ptr, self._output_counts[idx]

    def release_output(self, idx: int):
        """Unmap an output buffer previously retrieved."""
        _lib.vip_unmap_buffer(self._output_buffers[idx])

    def get_output_float_array(self, idx: int):
        """Get a numpy float32 array from an output buffer.

        Handles dequantization from uint8/int8 formats.
        Uses numpy for zero-copy where possible.
        """
        import numpy as np

        buf = self._output_buffers[idx]
        raw_ptr = _lib.vip_map_buffer(buf)
        count = self._output_counts[idx]
        fmt = self._output_formats[idx]
        quant = self._output_quant[idx]
        scale = self._output_scales[idx]
        zero_point = self._output_zero_points[idx]
        fp_pos = self._output_fp_pos[idx]

        if fmt == VIP_BUFFER_FORMAT_FP32:
            ptr = ctypes.cast(raw_ptr, POINTER(c_float))
            result = np.ctypeslib.as_array(ptr, shape=(count,)).copy()
        elif fmt == VIP_BUFFER_FORMAT_UINT8:
            ptr = ctypes.cast(raw_ptr, POINTER(ctypes.c_uint8))
            raw = np.ctypeslib.as_array(ptr, shape=(count,))
            if quant == VIP_BUFFER_QUANTIZE_TF_ASYMM:
                result = (raw.astype(np.float32) - float(zero_point)) * float(scale)
            else:
                result = raw.astype(np.float32)
        elif fmt == VIP_BUFFER_FORMAT_INT8:
            ptr = ctypes.cast(raw_ptr, POINTER(ctypes.c_int8))
            raw = np.ctypeslib.as_array(ptr, shape=(count,))
            if quant == VIP_BUFFER_QUANTIZE_DYNAMIC_FIXED_POINT:
                result = raw.astype(np.float32) / float(1 << fp_pos)
            elif quant == VIP_BUFFER_QUANTIZE_TF_ASYMM:
                result = (raw.astype(np.float32) - float(zero_point)) * float(scale)
            else:
                result = raw.astype(np.float32)
        else:
            _lib.vip_unmap_buffer(buf)
            raise RuntimeError(f"unsupported output format: {fmt}")

        _lib.vip_unmap_buffer(buf)
        return result

    # ── cleanup ──────────────────────────────────────────────────

    def finish_network(self):
        """Finish the network (release prepare-time resources)."""
        if self.network is not None and not self._closed:
            _lib.vip_finish_network(self.network)

    def destroy_network(self):
        """Destroy network and all associated buffers."""
        if self._closed:
            return
        self._closed = True

        for buf in self._input_buffers:
            _lib.vip_destroy_buffer(buf)
        self._input_buffers.clear()

        for buf in self._output_buffers:
            _lib.vip_destroy_buffer(buf)
        self._output_buffers.clear()
        self._output_counts.clear()
        self._output_formats.clear()
        self._output_quant.clear()
        self._output_scales.clear()
        self._output_zero_points.clear()
        self._output_fp_pos.clear()

        if self.network is not None:
            _lib.vip_destroy_network(self.network)
            self.network = None

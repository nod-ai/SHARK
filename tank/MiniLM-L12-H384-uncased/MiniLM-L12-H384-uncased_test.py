from shark.iree_utils._common import check_device_drivers, device_driver_info
from shark.shark_inference import SharkInference
from shark.shark_downloader import download_tf_model
from shark.parser import shark_args

import iree.compiler as ireec
import unittest
import pytest
import numpy as np


class MiniLMModuleTester:
    def __init__(
        self,
        benchmark=False,
    ):
        self.benchmark = benchmark

    def create_and_check_module(self, dynamic, device):
        model, func_name, inputs, golden_out = download_tf_model(
            "microsoft/MiniLM-L12-H384-uncased"
        )
        shark_args.enable_tf32 = self.benchmark

        shark_module = SharkInference(
            model,
            func_name,
            device=device,
            mlir_dialect="mhlo",
            is_benchmark=self.benchmark,
        )
        if self.benchmark == True:
            shark_args.enable_tf32 = True
            shark_module.compile()
            rtol = 1e-01
            atol = 1e-02
            shark_module.shark_runner.benchmark_all_csv(
                (inputs),
                "microsoft/MiniLM-L12-H384-uncased",
                dynamic,
                device,
                "tensorflow",
            )
            shark_args.enable_tf32 = False

        else:
            shark_module.compile()
            rtol = 1e-02
            atol = 1e-03

        result = shark_module.forward(inputs)
        np.testing.assert_allclose(golden_out, result, rtol=rtol, atol=atol)


class MiniLMModuleTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def configure(self, pytestconfig):
        self.module_tester = MiniLMModuleTester(self)
        self.module_tester.benchmark = pytestconfig.getoption("benchmark")

    def test_module_static_cpu(self):
        dynamic = False
        device = "cpu"
        self.module_tester.create_and_check_module(dynamic, device)

    @pytest.mark.skipif(
        check_device_drivers("gpu"), reason=device_driver_info("gpu")
    )
    def test_module_static_gpu(self):
        dynamic = False
        device = "gpu"
        self.module_tester.create_and_check_module(dynamic, device)

    @pytest.mark.skipif(
        check_device_drivers("vulkan"), reason=device_driver_info("vulkan")
    )
    def test_module_static_vulkan(self):
        dynamic = False
        device = "vulkan"
        self.module_tester.create_and_check_module(dynamic, device)


if __name__ == "__main__":
    unittest.main()
